from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_REEXEC_GUARD = "MOSAIC_OPENAPI_UV_REEXEC"
ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "src/squashvision/backend"
WEB = ROOT / "src/squashvision/web"
OUTPUT = WEB / "src/api/types.generated.ts"


def _load_backend() -> tuple[object, object]:
    sys.path.insert(0, str(BACKEND))
    try:
        from squashvision.app import create_app
        from squashvision.settings import Settings
    except ModuleNotFoundError:
        if os.environ.get(_REEXEC_GUARD) == "1":
            raise
        uv = shutil.which("uv")
        if uv is None:
            raise RuntimeError(
                "backend dependencies are unavailable and uv was not found"
            ) from None
        environment = dict(os.environ)
        environment[_REEXEC_GUARD] = "1"
        os.execve(
            uv,
            [
                uv,
                "run",
                "--project",
                str(BACKEND),
                "python",
                str(Path(__file__).resolve()),
            ],
            environment,
        )
        raise RuntimeError("uv re-execution unexpectedly returned")
    return create_app, Settings


def _validate_operation_ids(schema: dict[str, object]) -> None:
    paths = schema.get("paths")
    if not isinstance(paths, dict):
        raise RuntimeError("OpenAPI schema has no paths object")
    operation_ids: list[str] = []
    for path in sorted(paths):
        operations = paths[path]
        if not isinstance(operations, dict):
            continue
        for method in ("delete", "get", "patch", "post", "put"):
            operation = operations.get(method)
            if not isinstance(operation, dict):
                continue
            operation_id = operation.get("operationId")
            if not isinstance(operation_id, str) or not operation_id:
                raise RuntimeError(f"{method.upper()} {path} has no operationId")
            operation_ids.append(operation_id)
    duplicates = sorted(
        operation_id
        for operation_id in set(operation_ids)
        if operation_ids.count(operation_id) > 1
    )
    if duplicates:
        raise RuntimeError(
            "OpenAPI operation IDs are not unique: " + ", ".join(duplicates)
        )


def _generate() -> None:
    create_app, Settings = _load_backend()
    executable = WEB / "node_modules/.bin/openapi-typescript"
    if not executable.is_file():
        raise RuntimeError(
            "local openapi-typescript is missing; run npm install in src/squashvision/web"
        )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mosaic-openapi-") as temporary_dir:
        temporary = Path(temporary_dir)
        app = create_app(Settings(data_dir=temporary / "app", min_free_disk_bytes=0))
        schema = app.openapi()
        _validate_operation_ids(schema)
        input_path = temporary / "openapi.json"
        input_path.write_text(
            json.dumps(
                schema,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        output_path = OUTPUT.with_name(f".{OUTPUT.name}.{os.getpid()}.tmp")
        try:
            subprocess.run(
                [str(executable), str(input_path), "--output", str(output_path)],
                cwd=WEB,
                check=True,
                stdin=subprocess.DEVNULL,
            )
            generated = output_path.read_bytes()
            current = OUTPUT.read_bytes() if OUTPUT.exists() else None
            if current != generated:
                os.replace(output_path, OUTPUT)
        finally:
            output_path.unlink(missing_ok=True)


if __name__ == "__main__":
    _generate()
