from __future__ import annotations

import argparse
import fcntl
import json
import os
import platform
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from types import FrameType
from typing import TextIO
from uuid import uuid4

SQUASHVISION_ROOT = Path(__file__).resolve().parent
BACKEND_ROOT = SQUASHVISION_ROOT / "backend"
WEB_ROOT = SQUASHVISION_ROOT / "web"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from squashvision.app import create_app
from squashvision.db import Database
from squashvision.jobs import ClaimLostError, JobQueue
from squashvision.model_assets import ModelAssetManager, ModelManifest
from squashvision.pipeline import AnalysisPipeline
from squashvision.settings import Settings
from squashvision.storage import LocalStorage
from squashvision.worker import Worker

LOOPBACK = "127.0.0.1"
_WORKER_HEARTBEAT = ".worker-heartbeat.json"
_LOCK_FILE = ".launcher.lock"


class LauncherError(RuntimeError):
    pass


@dataclass(slots=True)
class ChildProcess:
    name: str
    process: subprocess.Popen[str]
    relay: threading.Thread
    pgid: int


def parse_args(arguments: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the local SquashVision product on loopback.",
    )
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--api-port", type=int, default=8765)
    parser.add_argument("--web-port", type=int, default=5173)
    parser.add_argument("--static-dir", type=Path, default=WEB_ROOT / "dist")
    parser.add_argument("--dev", action="store_true", help="Run the Vite development server explicitly.")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--startup-timeout", type=float, default=45.0)
    parser.add_argument("--shutdown-timeout", type=float, default=10.0)
    parser.add_argument("--child", choices=("api", "worker"), help=argparse.SUPPRESS)
    parsed = parser.parse_args(arguments)
    parsed.host = LOOPBACK
    if not 1 <= parsed.api_port <= 65535 or not 1 <= parsed.web_port <= 65535:
        parser.error("ports must be between 1 and 65535")
    if parsed.startup_timeout <= 0 or parsed.shutdown_timeout <= 0:
        parser.error("timeouts must be positive")
    if parsed.data_dir is None:
        parsed.data_dir = Settings(host=LOOPBACK).data_dir
    return parsed


def _settings(args: argparse.Namespace) -> Settings:
    return Settings(
        data_dir=Path(args.data_dir),
        host=LOOPBACK,
        api_port=args.api_port,
        web_port=args.web_port,
    )


def _safe_log(value: object, *, data_dir: Path | None = None) -> str:
    text = str(value)
    if data_dir is not None:
        text = text.replace(str(data_dir), "<data-dir>")
    return "".join(character if character == "\t" or ord(character) >= 32 else "?" for character in text)


def _log_worker_iteration_failure(
    error: BaseException,
    *,
    data_dir: Path,
    worker_id: str,
    iteration: int,
) -> None:
    context = _safe_log(
        f"worker iteration {iteration} failed (worker {worker_id})",
        data_dir=data_dir,
    )
    rendered = "".join(
        traceback.format_exception(type(error), error, error.__traceback__)
    )
    safe_traceback = "\n".join(
        _safe_log(line, data_dir=data_dir) for line in rendered.splitlines()
    )
    print(f"{context}\n{safe_traceback}", file=sys.stderr, flush=True)


def _write_worker_heartbeat(path: Path, worker_id: str) -> None:
    payload = {
        "schemaVersion": 1,
        "state": "ready",
        "workerId": worker_id,
        "pid": os.getpid(),
        "heartbeatAt": datetime.now(timezone.utc).isoformat(),
    }
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def _run_api(args: argparse.Namespace) -> int:
    import uvicorn

    settings = _settings(args)
    static_dir = None if args.dev else Path(args.static_dir)
    app = create_app(settings, static_dir=static_dir, run_migrations=False)
    configuration = uvicorn.Config(
        app,
        host=LOOPBACK,
        port=args.api_port,
        access_log=False,
        log_level="info",
    )
    server = uvicorn.Server(configuration)
    server.run()
    return 0 if not server.should_exit or server.started else 1


def _run_worker(args: argparse.Namespace) -> int:
    settings = _settings(args)
    if settings.storage_root is None:
        raise LauncherError("storage root is not configured")
    database = Database.open(settings, migrate=False)
    storage = LocalStorage(settings.storage_root)
    queue = JobQueue(database, storage)
    model_assets = ModelAssetManager(database, storage)
    manifest = ModelManifest(model_assets)
    pipeline = AnalysisPipeline(
        storage_root=storage.root,
        database=database,
        model_manifest=manifest,
    )
    worker_id = f"local-{uuid4().hex}"
    worker = Worker(queue, worker_id, pipeline)
    stop = threading.Event()
    heartbeat_path = settings.data_dir / _WORKER_HEARTBEAT

    def request_stop(_signum: int, _frame: FrameType | None) -> None:
        stop.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    def maintain_idle_heartbeat() -> None:
        while not stop.is_set():
            try:
                queue.heartbeat(worker_id)
                _write_worker_heartbeat(heartbeat_path, worker_id)
            except Exception as error:
                print(
                    f"worker heartbeat failed: {_safe_log(type(error).__name__, data_dir=settings.data_dir)}",
                    flush=True,
                )
                stop.set()
                return
            stop.wait(2.0)

    keeper = threading.Thread(
        target=maintain_idle_heartbeat,
        name="squashvision-worker-heartbeat",
        daemon=True,
    )
    keeper.start()
    iteration = 0
    try:
        while not stop.is_set():
            iteration += 1
            try:
                worked = worker.run_once()
            except ClaimLostError:
                worked = True
            except Exception as error:
                _log_worker_iteration_failure(
                    error,
                    data_dir=settings.data_dir,
                    worker_id=worker_id,
                    iteration=iteration,
                )
                worked = True
            if not worked:
                stop.wait(1.0)
    finally:
        stop.set()
        keeper.join(timeout=3.0)
        database.engine.dispose()
    return 0


def _check_port_available(port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind((LOOPBACK, port))
        except OSError as error:
            raise LauncherError(f"loopback port {port} is unavailable") from error


class _AssetReferenceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.references: list[tuple[str, str]] = []

    def handle_starttag(
        self,
        tag: str,
        attributes: list[tuple[str, str | None]],
    ) -> None:
        values = {name.lower(): value for name, value in attributes}
        if tag.lower() == "script" and values.get("src") is not None:
            kind = (
                "module_script"
                if (values.get("type") or "").lower() == "module"
                else "script"
            )
            self.references.append((kind, str(values["src"])))
        if (
            tag.lower() == "link"
            and "stylesheet" in (values.get("rel") or "").lower().split()
            and values.get("href") is not None
        ):
            self.references.append(("stylesheet", str(values["href"])))


def validate_static_assets(static_dir: Path) -> Path:
    try:
        root = Path(static_dir).expanduser().resolve(strict=True)
        index = root / "index.html"
        index_info = index.lstat()
        if (
            index.is_symlink()
            or not stat.S_ISREG(index_info.st_mode)
            or index_info.st_size > 1024 * 1024
        ):
            raise OSError("index is not a bounded regular file")
        parser = _AssetReferenceParser()
        parser.feed(index.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise LauncherError(
            "built web assets are missing or unsafe; run the web build first"
        ) from error
    kinds = {kind for kind, _reference in parser.references}
    if "module_script" not in kinds or "stylesheet" not in kinds:
        raise LauncherError(
            "built web assets are incomplete; production module and stylesheet references are required"
        )
    for kind, reference in parser.references:
        if (
            not reference.startswith("/assets/")
            or "\\" in reference
            or "?" in reference
            or "#" in reference
            or any(
                ord(character) < 32 or ord(character) == 127
                for character in reference
            )
        ):
            raise LauncherError("referenced web asset path is unsafe")
        parts = PurePosixPath(reference.removeprefix("/")).parts
        if (
            not parts
            or parts[0] != "assets"
            or any(part in {"", ".", ".."} for part in parts)
            or (
                kind in {"script", "module_script"}
                and not reference.endswith(".js")
            )
            or (
                kind == "stylesheet"
                and not reference.endswith(".css")
            )
        ):
            raise LauncherError("referenced web asset path is unsafe")
        candidate = root.joinpath(*parts)
        try:
            current = root
            for part in parts[:-1]:
                current /= part
                info = current.lstat()
                if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(
                    info.st_mode
                ):
                    raise OSError("asset parent is unsafe")
            info = candidate.lstat()
            candidate.resolve(strict=True).relative_to(root)
            if candidate.is_symlink() or not stat.S_ISREG(info.st_mode):
                raise OSError("asset is not a regular file")
        except (OSError, ValueError) as error:
            raise LauncherError(
                "referenced web asset is missing or unsafe"
            ) from error
    return root


def probe_writable_directory(directory: Path, label: str) -> None:
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    probe = root / f".writable-{uuid4().hex}"
    descriptor: int | None = None
    try:
        descriptor = os.open(
            probe,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        os.write(descriptor, b"squashvision-write-probe")
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        directory_descriptor = os.open(root, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except OSError as error:
        raise LauncherError(
            f"the SquashVision {label} directory is not writable"
        ) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
        probe.unlink(missing_ok=True)


def probe_database_write(database: Database) -> None:
    connection = database.engine.connect()
    try:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        connection.exec_driver_sql(
            "UPDATE alembic_version SET version_num = version_num"
        )
        connection.rollback()
    except BaseException as error:
        connection.rollback()
        raise LauncherError(
            "the SquashVision database is not writable"
        ) from error
    finally:
        connection.close()


def _preflight(
    args: argparse.Namespace, stop: threading.Event | None = None
) -> Settings:
    if sys.version_info < (3, 12):
        raise LauncherError("Python 3.12 or newer is required")
    if platform.system() == "Darwin" and platform.machine() != "arm64":
        raise LauncherError("native arm64 Python is required on macOS")
    settings = _settings(args)
    data_dir = settings.data_dir.expanduser().resolve(strict=False)
    data_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(data_dir, 0o700)
    probe_writable_directory(data_dir, "data")
    if stop is not None and stop.is_set():
        return settings
    _check_port_available(args.api_port)
    if stop is not None and stop.is_set():
        return settings
    if args.dev:
        if args.web_port == args.api_port:
            raise LauncherError("development API and web ports must differ")
        _check_port_available(args.web_port)
    else:
        validate_static_assets(Path(args.static_dir))
    if stop is not None and stop.is_set():
        return settings
    try:
        import av  # noqa: F401
        import imageio_ffmpeg

        ffmpeg = Path(imageio_ffmpeg.get_ffmpeg_exe())
        if not ffmpeg.is_file() or not os.access(ffmpeg, os.X_OK):
            raise LauncherError("FFmpeg is not executable")
    except (ImportError, RuntimeError, OSError) as error:
        if isinstance(error, LauncherError):
            raise
        raise LauncherError("FFmpeg and PyAV are required") from error
    if stop is not None and stop.is_set():
        return settings
    database = Database.open(settings, migrate=True)
    try:
        probe_database_write(database)
    finally:
        database.engine.dispose()
    if stop is not None and stop.is_set():
        return settings
    if settings.storage_root is None:
        raise LauncherError("storage root is not configured")
    storage = LocalStorage(settings.storage_root)
    probe_writable_directory(storage.root, "storage")
    if stop is not None and stop.is_set():
        return settings
    return settings


def _acquire_lock(data_dir: Path) -> TextIO:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / _LOCK_FILE
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as error:
        raise LauncherError("launcher lock could not be opened safely") from error
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            raise LauncherError(
                "launcher lock must be a private regular file owned by the current user"
            )
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise LauncherError(
                "SquashVision is already running for this data directory"
            ) from error
        os.ftruncate(descriptor, 0)
        os.write(descriptor, f"{os.getpid()}\n".encode("ascii"))
        os.fsync(descriptor)
        return os.fdopen(descriptor, "r+", encoding="utf-8")
    except BaseException:
        os.close(descriptor)
        raise


def _child_environment() -> dict[str, str]:
    allowed = ("HOME", "PATH", "TMPDIR", "LANG", "LC_ALL", "SYSTEM_VERSION_COMPAT", "SQUASHVISION_PROFILE_METRICS")
    environment = {name: os.environ[name] for name in allowed if name in os.environ}
    environment["PYTHONUNBUFFERED"] = "1"
    return environment


def _relay_logs(name: str, stream: TextIO, data_dir: Path) -> None:
    try:
        for line in stream:
            print(f"[{name}] {_safe_log(line.rstrip(), data_dir=data_dir)}", flush=True)
    finally:
        stream.close()


def _spawn(
    name: str,
    arguments: list[str],
    data_dir: Path,
    *,
    environment_overrides: dict[str, str] | None = None,
) -> ChildProcess:
    environment = _child_environment()
    if environment_overrides is not None:
        environment.update(environment_overrides)
    process = subprocess.Popen(
        arguments,
        cwd=SQUASHVISION_ROOT.parents[1],
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        start_new_session=True,
    )
    try:
        pgid = os.getpgid(process.pid)
        session_id = os.getsid(process.pid)
    except ProcessLookupError as error:
        process.wait()
        raise LauncherError(
            f"{name} exited before its process group could be verified"
        ) from error
    if pgid != process.pid or session_id != process.pid:
        process.terminate()
        process.wait()
        raise LauncherError(f"{name} did not start in an owned process group")
    if process.stdout is None:
        os.killpg(pgid, signal.SIGTERM)
        process.wait()
        raise LauncherError(f"{name} log pipe could not be opened")
    relay = threading.Thread(
        target=_relay_logs,
        args=(name, process.stdout, data_dir),
        name=f"squashvision-{name}-logs",
        daemon=True,
    )
    relay.start()
    return ChildProcess(name, process, relay, pgid)


def _child_arguments(args: argparse.Namespace, child: str) -> list[str]:
    arguments = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--child", child,
        "--data-dir", str(Path(args.data_dir).resolve(strict=False)),
        "--api-port", str(args.api_port),
        "--web-port", str(args.web_port),
        "--static-dir", str(Path(args.static_dir).resolve(strict=False)),
        "--startup-timeout", str(args.startup_timeout),
        "--shutdown-timeout", str(args.shutdown_timeout),
        "--no-browser",
    ]
    if args.dev:
        arguments.append("--dev")
    return arguments


def _worker_ready(path: Path, pid: int, started_at: float) -> bool:
    try:
        if path.stat().st_mtime < started_at:
            return False
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    return payload.get("state") == "ready" and payload.get("pid") == pid


def _api_ready(port: int) -> bool:
    try:
        with urllib.request.urlopen(
            f"http://{LOOPBACK}:{port}/api/v1/health",
            timeout=0.5,
        ) as response:
            payload = json.load(response)
        return (
            response.status == 200
            and payload.get("status") in {"ready", "degraded"}
            and payload.get("ffmpeg", {}).get("status") == "ready"
        )
    except (OSError, ValueError, urllib.error.URLError):
        return False


def _port_ready(port: int) -> bool:
    try:
        with socket.create_connection((LOOPBACK, port), timeout=0.25):
            return True
    except OSError:
        return False


def _wait_for_readiness(
    children: list[ChildProcess],
    args: argparse.Namespace,
    started_at: float,
    stop: threading.Event,
) -> bool:
    deadline = time.monotonic() + args.startup_timeout
    heartbeat = Path(args.data_dir) / _WORKER_HEARTBEAT
    while time.monotonic() < deadline:
        if stop.is_set():
            return False
        failed = next(
            (child for child in children if child.process.poll() is not None),
            None,
        )
        if failed is not None:
            raise LauncherError(f"{failed.name} exited before readiness")
        api = next(child for child in children if child.name == "api")
        worker = next(child for child in children if child.name == "worker")
        api_ready = _api_ready(args.api_port)
        if stop.is_set():
            return False
        worker_ready = _worker_ready(
            heartbeat, worker.process.pid, started_at
        )
        if stop.is_set():
            return False
        web_ready = True
        if args.dev:
            web_ready = _port_ready(args.web_port)
            if stop.is_set():
                return False
        if (
            api.process.poll() is None
            and api_ready
            and worker_ready
            and web_ready
        ):
            return True
        if stop.wait(0.1):
            return False
    raise LauncherError("services did not become ready before the startup timeout")


def _verified_group_signal(child: ChildProcess, signum: int) -> None:
    if child.pgid <= 0 or child.pgid != child.process.pid:
        raise LauncherError(f"refusing to signal unowned {child.name} process group")
    try:
        os.killpg(child.pgid, signum)
    except ProcessLookupError:
        return


def _group_alive(child: ChildProcess) -> bool:
    child.process.poll()
    if child.pgid <= 0 or child.pgid != child.process.pid:
        raise LauncherError(f"refusing to inspect unowned {child.name} process group")
    try:
        os.killpg(child.pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _stop_children(children: list[ChildProcess], timeout: float) -> None:
    for child in children:
        _verified_group_signal(child, signal.SIGTERM)
    deadline = time.monotonic() + timeout
    while (
        any(_group_alive(child) for child in children)
        and time.monotonic() < deadline
    ):
        time.sleep(0.05)
    for child in children:
        if _group_alive(child):
            _verified_group_signal(child, signal.SIGKILL)
    for child in children:
        try:
            child.process.wait(timeout=2.0)
        except subprocess.TimeoutExpired as error:
            raise LauncherError(f"{child.name} could not be reaped") from error
    for child in children:
        child.relay.join(timeout=2.0)


def _run_launcher(args: argparse.Namespace) -> int:
    data_dir = Path(args.data_dir).expanduser().resolve(strict=False)
    children: list[ChildProcess] = []
    stop = threading.Event()
    lock: TextIO | None = None

    def request_stop(_signum: int, _frame: FrameType | None) -> None:
        stop.set()

    previous_int = signal.signal(signal.SIGINT, request_stop)
    previous_term = signal.signal(signal.SIGTERM, request_stop)
    try:
        if stop.is_set():
            return 0
        lock = _acquire_lock(data_dir)
        if stop.is_set():
            return 0
        _preflight(args, stop)
        if stop.is_set():
            return 0
        started_at = time.time()
        children.append(_spawn("api", _child_arguments(args, "api"), data_dir))
        if stop.is_set():
            return 0
        children.append(
            _spawn("worker", _child_arguments(args, "worker"), data_dir)
        )
        if stop.is_set():
            return 0
        if args.dev:
            children.append(
                _spawn(
                    "web",
                    [
                        "npm", "--prefix", str(WEB_ROOT), "run", "dev", "--",
                        "--host", LOOPBACK, "--port", str(args.web_port), "--strictPort",
                    ],
                    data_dir,
                    environment_overrides={
                        "SQUASHVISION_API_ORIGIN": (
                            f"http://{LOOPBACK}:{args.api_port}"
                        )
                    },
                )
            )
            if stop.is_set():
                return 0
        if not _wait_for_readiness(children, args, started_at, stop):
            return 0
        if stop.is_set():
            return 0
        product_port = args.web_port if args.dev else args.api_port
        product_url = f"http://{LOOPBACK}:{product_port}/"
        print(f"SquashVision ready at {product_url}", flush=True)
        if stop.is_set():
            return 0
        print("Model readiness is reported truthfully in /api/v1/health; missing models use the explicit install flow.", flush=True)
        if stop.is_set():
            return 0
        if not args.no_browser:
            webbrowser.open(product_url, new=2, autoraise=True)
            if stop.is_set():
                return 0
        while not stop.wait(0.2):
            failed = next(
                (
                    child
                    for child in children
                    if child.process.poll() is not None
                ),
                None,
            )
            if failed is not None:
                print(
                    f"{failed.name} exited; shutting down SquashVision",
                    flush=True,
                )
                break
        if stop.is_set():
            return 0
        return 0 if all(
            child.process.poll() is None for child in children
        ) else 1
    finally:
        try:
            _stop_children(children, args.shutdown_timeout)
        finally:
            signal.signal(signal.SIGINT, previous_int)
            signal.signal(signal.SIGTERM, previous_term)
            if lock is not None:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
                lock.close()


def main(arguments: list[str] | None = None) -> int:
    args = parse_args(arguments)
    try:
        if args.child == "api":
            return _run_api(args)
        if args.child == "worker":
            return _run_worker(args)
        return _run_launcher(args)
    except LauncherError as error:
        print(f"SquashVision launcher error: {_safe_log(error, data_dir=Path(args.data_dir))}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
