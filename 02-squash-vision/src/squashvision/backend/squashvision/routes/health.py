import json
import os
import platform
import stat
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

import torch

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from squashvision.media import MediaError, resolve_ffmpeg_binary
from squashvision.jobs import JobQueue
from squashvision.model_assets import ModelManifest
from squashvision.models import ModelAssetState
from squashvision.settings import Settings
from squashvision.schemas import ErrorResponse

router = APIRouter(responses={500: {"model": ErrorResponse}})


class ComponentHealth(BaseModel):
    status: Literal["ready", "unavailable"]

class WorkerHealth(ComponentHealth):
    model_config = ConfigDict(populate_by_name=True)

    architecture: str
    native_apple_silicon: bool = Field(serialization_alias="nativeAppleSilicon")
    mps_available: bool = Field(serialization_alias="mpsAvailable")




class ModelAssetHealth(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str
    required: bool
    state: ModelAssetState
    error_code: str | None = Field(serialization_alias="errorCode")


class ModelComponentHealth(BaseModel):
    status: Literal[
        "ready",
        "missing",
        "downloading",
        "corrupt",
        "incompatible",
        "unavailable",
    ]
    assets: list[ModelAssetHealth]

class HealthResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    status: Literal["ready", "degraded"]
    version: str
    ffmpeg: ComponentHealth
    worker: WorkerHealth
    models: ModelComponentHealth


def _model_health(manifest: ModelManifest | None) -> ModelComponentHealth:
    if manifest is None:
        return ModelComponentHealth(status="unavailable", assets=[])
    assets = manifest.states()
    required_states = {
        asset.state for asset in assets if asset.required
    }
    if not required_states or required_states == {ModelAssetState.READY}:
        status = "ready"
    else:
        priority = (
            ModelAssetState.INCOMPATIBLE,
            ModelAssetState.CORRUPT,
            ModelAssetState.DOWNLOADING,
            ModelAssetState.MISSING,
        )
        status = next(
            state.value for state in priority if state in required_states
        )
    return ModelComponentHealth(
        status=status,
        assets=[
            ModelAssetHealth(
                name=asset.name,
                required=asset.required,
                state=asset.state,
                error_code=asset.error_code,
            )
            for asset in assets
        ],
    )


def _ffmpeg_health() -> ComponentHealth:
    try:
        resolve_ffmpeg_binary()
    except MediaError:
        return ComponentHealth(status="unavailable")
    return ComponentHealth(status="ready")


def _launcher_worker_is_healthy(settings: Settings) -> bool:
    path = Path(settings.data_dir) / ".worker-heartbeat.json"
    try:
        info = path.lstat()
        if (
            stat.S_ISLNK(info.st_mode)
            or not stat.S_ISREG(info.st_mode)
            or info.st_size > 4_096
        ):
            return False
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return False
        worker_pid = payload.get("pid")
        heartbeat_at = payload.get("heartbeatAt")
        if (
            payload.get("schemaVersion") != 1
            or payload.get("state") != "ready"
            or type(worker_pid) is not int
            or worker_pid <= 1
            or not isinstance(heartbeat_at, str)
        ):
            return False
        parsed = datetime.fromisoformat(heartbeat_at)
        if parsed.tzinfo is None:
            return False
        age = datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)
        if age < -timedelta(seconds=5) or age > timedelta(seconds=10):
            return False
        os.kill(worker_pid, 0)
        return True
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False


def _health_response(
    settings: Settings,
    queue: JobQueue | None = None,
    manifest: ModelManifest | None = None,
) -> HealthResponse:
    components = {
        "ffmpeg": _ffmpeg_health(),
        "worker": WorkerHealth(
            status=(
                "ready"
                if (
                    queue is not None
                    and (
                        queue.worker_is_healthy()
                        or _launcher_worker_is_healthy(settings)
                    )
                )
                else "unavailable"
            ),
            architecture=platform.machine() or "unknown",
            native_apple_silicon=(
                sys.platform == "darwin"
                and platform.machine().lower() in {"arm64", "aarch64"}
            ),
            mps_available=bool(
                hasattr(torch.backends, "mps") and torch.backends.mps.is_available()
            ),
        ),
        "models": _model_health(manifest),
    }
    overall_status = (
        "ready"
        if all(component.status == "ready" for component in components.values())
        else "degraded"
    )
    return HealthResponse(
        status=overall_status,
        version="1.0.0",
        **components,
    )


@router.get("/health", response_model=HealthResponse, operation_id="getHealth")
def health(request: Request) -> HealthResponse:
    return _health_response(
        request.app.state.settings,
        getattr(request.app.state, "job_queue", None),
        getattr(request.app.state, "model_manifest", None),
    )
