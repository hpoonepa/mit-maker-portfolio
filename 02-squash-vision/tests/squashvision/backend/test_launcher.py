from __future__ import annotations

import errno
import importlib.util
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

root = Path(__file__).resolve().parents[3]
launcher_path = root / "src/squashvision/launcher.py"


def _load_launcher() -> object:
    spec = importlib.util.spec_from_file_location("squashvision_launcher", launcher_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError as error:
        return error.errno == errno.EPERM
    return True


def _wait_ready(data_dir: Path, port: int, process: subprocess.Popen[str], timeout: float = 30.0) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout = process.stdout.read() if process.stdout is not None else ""
            raise AssertionError(f"launcher exited {process.returncode}: {stdout}")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v1/health", timeout=0.5) as response:
                health = json.load(response)
            heartbeat = data_dir / ".worker-heartbeat.json"
            if heartbeat.is_file() and health["status"] in {"ready", "degraded"}:
                return json.loads(heartbeat.read_text())
        except Exception as error:
            last_error = error
        time.sleep(0.1)
    raise AssertionError(f"launcher did not become ready: {last_error}")


def _children(parent_pid: int) -> list[int]:
    completed = subprocess.run(
        ["pgrep", "-P", str(parent_pid)],
        check=False,
        capture_output=True,
        text=True,
    )
    return [int(value) for value in completed.stdout.split()]


def test_launcher_parser_has_no_unsafe_host_override_and_defaults_to_loopback(tmp_path: Path) -> None:
    launcher = _load_launcher()
    parsed = launcher.parse_args(["--data-dir", str(tmp_path), "--no-browser"])
    assert parsed.host == "127.0.0.1"
    with pytest.raises(SystemExit):
        launcher.parse_args(["--host", "0.0.0.0"])


def test_worker_failure_log_includes_safe_traceback_and_iteration_context(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    launcher = _load_launcher()
    data_dir = tmp_path / "private-data"
    try:
        raise RuntimeError(f"decoder failed under {data_dir}")
    except RuntimeError as error:
        launcher._log_worker_iteration_failure(
            error,
            data_dir=data_dir,
            worker_id="local-test-worker",
            iteration=7,
        )

    diagnostic = capsys.readouterr().err
    assert "worker iteration 7 failed (worker local-test-worker)" in diagnostic
    assert "RuntimeError: decoder failed under <data-dir>" in diagnostic
    assert "Traceback (most recent call last):" in diagnostic
    assert "test_worker_failure_log_includes_safe_traceback" in diagnostic
    assert str(data_dir) not in diagnostic


def test_launcher_runs_api_and_real_worker_without_node_rejects_second_instance_and_cleans_groups(tmp_path: Path) -> None:
    static = tmp_path / "dist"
    assets = static / "assets"
    assets.mkdir(parents=True)
    (static / "index.html").write_text(
        '<!doctype html><script type="module" src="/assets/app.js"></script>'
        '<link rel="stylesheet" href="/assets/app.css"><title>Launcher product</title>'
    )
    (assets / "app.js").write_text("document.body.dataset.ready = 'yes'")
    (assets / "app.css").write_text("body { color: white; }")
    data_dir = tmp_path / "data"
    port = _free_port()
    environment = {**os.environ, "PATH": "/usr/bin:/bin"}
    arguments = [
        sys.executable,
        str(launcher_path),
        "--data-dir", str(data_dir),
        "--api-port", str(port),
        "--static-dir", str(static),
        "--startup-timeout", "30",
        "--shutdown-timeout", "5",
        "--no-browser",
    ]
    process = subprocess.Popen(
        arguments,
        cwd=root,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    child_pids: list[int] = []
    try:
        heartbeat = _wait_ready(data_dir, port, process)
        assert heartbeat["state"] == "ready"
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/v1/health", timeout=2
        ) as response:
            health = json.load(response)
        assert health["worker"]["status"] == "ready"
        child_pids = _children(process.pid)
        assert len(child_pids) == 2
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2) as response:
            assert "Launcher product" in response.read().decode()

        second = subprocess.run(arguments, cwd=root, env=environment, capture_output=True, text=True, timeout=15)
        assert second.returncode != 0
        assert "already running" in (second.stdout + second.stderr).lower()
        assert process.poll() is None
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
        process.wait(timeout=15)
        if process.stdout is not None:
            process.stdout.close()
    assert process.returncode == 0
    assert child_pids and not any(_alive(pid) for pid in child_pids)


def test_launcher_fails_before_spawning_when_static_assets_are_missing(tmp_path: Path) -> None:
    port = _free_port()
    completed = subprocess.run(
        [
            sys.executable,
            str(launcher_path),
            "--data-dir", str(tmp_path / "data"),
            "--api-port", str(port),
            "--static-dir", str(tmp_path / "missing"),
            "--startup-timeout", "2",
            "--no-browser",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert completed.returncode != 0
    assert "built web assets" in (completed.stdout + completed.stderr).lower()


def test_static_preflight_validates_every_referenced_asset_and_symlink(
    tmp_path: Path,
) -> None:
    launcher = _load_launcher()
    static = tmp_path / "dist"
    assets = static / "assets"
    assets.mkdir(parents=True)
    (static / "index.html").write_text(
        '<script type="module" src="/assets/app.js"></script>'
        '<link rel="stylesheet" href="/assets/app.css">'
    )
    (assets / "app.js").write_text("export {}")

    with pytest.raises(launcher.LauncherError, match="referenced web asset"):
        launcher.validate_static_assets(static)

    (assets / "app.css").write_text("body {}")
    launcher.validate_static_assets(static)
    (assets / "app.js").unlink()
    outside = tmp_path / "outside.js"
    outside.write_text("secret")
    (assets / "app.js").symlink_to(outside)
    with pytest.raises(launcher.LauncherError, match="referenced web asset"):
        launcher.validate_static_assets(static)


@pytest.mark.parametrize(
    "index",
    [
        "<!doctype html><title>Truncated build</title>",
        '<script type="module" src="/assets/app.js"></script>',
        '<script src="/assets/app.js"></script>'
        '<link rel="stylesheet" href="/assets/app.css">',
    ],
)
def test_static_preflight_rejects_index_only_and_truncated_builds(
    tmp_path: Path,
    index: str,
) -> None:
    launcher = _load_launcher()
    static = tmp_path / "dist"
    assets = static / "assets"
    assets.mkdir(parents=True)
    (static / "index.html").write_text(index)
    (assets / "app.js").write_text("export {}")
    (assets / "app.css").write_text("body {}")

    with pytest.raises(launcher.LauncherError, match="incomplete"):
        launcher.validate_static_assets(static)


def test_storage_and_database_write_probes_are_real_and_rollback(
    tmp_path: Path,
) -> None:
    launcher = _load_launcher()
    read_only = tmp_path / "read-only"
    read_only.mkdir()
    read_only.chmod(0o500)
    try:
        with pytest.raises(launcher.LauncherError, match="not writable"):
            launcher.probe_writable_directory(read_only, "storage")
    finally:
        read_only.chmod(0o700)

    settings = launcher.Settings(
        data_dir=tmp_path / "data",
        min_free_disk_bytes=0,
    )
    database = launcher.Database.open(settings)
    launcher.probe_database_write(database)
    with database.engine.connect() as connection:
        names = {
            row[0]
            for row in connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert "launcher_write_probe" not in names


def test_launcher_stops_after_preflight_signal_before_spawning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    launcher = _load_launcher()
    args = launcher.parse_args(
        [
            "--data-dir",
            str(tmp_path / "data"),
            "--static-dir",
            str(tmp_path / "static"),
            "--no-browser",
        ]
    )

    def interrupt(_args: object, _stop: Event) -> object:
        os.kill(os.getpid(), signal.SIGTERM)
        return SimpleNamespace()

    monkeypatch.setattr(launcher, "_preflight", interrupt)
    monkeypatch.setattr(
        launcher,
        "_spawn",
        lambda *_args, **_kwargs: pytest.fail(
            "launcher spawned a child after shutdown was requested"
        ),
    )

    assert launcher._run_launcher(args) == 0


def test_launcher_stops_during_preflight_before_later_phases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    launcher = _load_launcher()
    args = launcher.parse_args(
        [
            "--data-dir",
            str(tmp_path / "data"),
            "--static-dir",
            str(tmp_path / "static"),
            "--no-browser",
        ]
    )

    def interrupt(_directory: Path, _label: str) -> None:
        os.kill(os.getpid(), signal.SIGTERM)

    monkeypatch.setattr(launcher, "probe_writable_directory", interrupt)
    monkeypatch.setattr(
        launcher,
        "_check_port_available",
        lambda _port: pytest.fail(
            "preflight continued after shutdown was requested"
        ),
    )
    monkeypatch.setattr(
        launcher,
        "_spawn",
        lambda *_args, **_kwargs: pytest.fail(
            "launcher spawned a child after shutdown was requested"
        ),
    )

    assert launcher._run_launcher(args) == 0


def test_readiness_stops_between_probes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    launcher = _load_launcher()
    stop = Event()
    worker_probed = False
    process = SimpleNamespace(pid=123, poll=lambda: None)
    children = [
        SimpleNamespace(name="api", process=process),
        SimpleNamespace(name="worker", process=process),
    ]
    args = SimpleNamespace(
        startup_timeout=1.0,
        data_dir=tmp_path,
        dev=False,
        api_port=8000,
        web_port=5173,
    )

    def api_ready(_port: int) -> bool:
        stop.set()
        return False

    def worker_ready(_path: Path, _pid: int, _started_at: float) -> bool:
        nonlocal worker_probed
        worker_probed = True
        return False

    monkeypatch.setattr(launcher, "_api_ready", api_ready)
    monkeypatch.setattr(launcher, "_worker_ready", worker_ready)

    assert (
        launcher._wait_for_readiness(
            children, args, time.time(), stop
        )
        is False
    )
    assert worker_probed is False


def test_stop_children_terminates_group_after_leader_exits(tmp_path: Path) -> None:
    launcher = _load_launcher()
    child_pid_path = tmp_path / "descendant.pid"
    script = (
        "import pathlib, subprocess, sys; "
        f"p=subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
        f"pathlib.Path({str(child_pid_path)!r}).write_text(str(p.pid))"
    )
    child = launcher._spawn(
        "orphan-test",
        [sys.executable, "-c", script],
        tmp_path,
    )
    child.process.wait(timeout=5)
    deadline = time.monotonic() + 5
    while not child_pid_path.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    descendant_pid = int(child_pid_path.read_text())

    try:
        launcher._stop_children([child], 1.0)
        deadline = time.monotonic() + 5
        while _alive(descendant_pid) and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not _alive(descendant_pid)
    finally:
        if _alive(descendant_pid):
            os.kill(descendant_pid, signal.SIGKILL)


def test_launcher_lock_rejects_symlink_without_touching_target(
    tmp_path: Path,
) -> None:
    launcher = _load_launcher()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    target = tmp_path / "target"
    target.write_text("do not truncate", encoding="utf-8")
    (data_dir / ".launcher.lock").symlink_to(target)

    with pytest.raises(launcher.LauncherError, match="lock"):
        launcher._acquire_lock(data_dir)

    assert target.read_text(encoding="utf-8") == "do not truncate"


def test_dev_web_child_receives_custom_api_origin_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    launcher = _load_launcher()
    args = launcher.parse_args(
        [
            "--data-dir",
            str(tmp_path / "data"),
            "--static-dir",
            str(tmp_path / "static"),
            "--api-port",
            "9123",
            "--dev",
            "--no-browser",
        ]
    )
    environments: dict[str, dict[str, str] | None] = {}

    def spawn(
        name: str,
        _arguments: list[str],
        _data_dir: Path,
        *,
        environment_overrides: dict[str, str] | None = None,
    ) -> object:
        environments[name] = environment_overrides
        process = SimpleNamespace(pid=123, poll=lambda: None)
        return SimpleNamespace(
            name=name,
            process=process,
            relay=SimpleNamespace(join=lambda **_kwargs: None),
            pgid=123,
        )

    monkeypatch.setattr(launcher, "_preflight", lambda _args, _stop: None)
    monkeypatch.setattr(launcher, "_spawn", spawn)
    monkeypatch.setattr(
        launcher,
        "_wait_for_readiness",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        launcher, "_stop_children", lambda *_args, **_kwargs: None
    )

    assert launcher._run_launcher(args) == 0
    assert environments == {
        "api": None,
        "worker": None,
        "web": {"SQUASHVISION_API_ORIGIN": "http://127.0.0.1:9123"},
    }


def test_group_signal_uses_spawn_verified_pgid_without_relooking_up_pid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launcher = _load_launcher()
    process = SimpleNamespace(pid=4321, poll=lambda: 0)
    child = launcher.ChildProcess(
        "verified",
        process,
        SimpleNamespace(join=lambda **_kwargs: None),
        4321,
    )
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(
        launcher.os,
        "getpgid",
        lambda _pid: pytest.fail(
            "cleanup re-looked up a reusable leader PID"
        ),
    )
    monkeypatch.setattr(
        launcher.os,
        "killpg",
        lambda pgid, signum: signals.append((pgid, signum)),
    )

    launcher._verified_group_signal(child, signal.SIGTERM)

    assert signals == [(4321, signal.SIGTERM)]
