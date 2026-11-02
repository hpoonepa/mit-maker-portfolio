from typing import Self

from pathlib import Path

from platformdirs import user_data_path
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_MAX_UPLOAD_BYTES = 20 * 1024 * 1024 * 1024
DEFAULT_MAX_VIDEO_DURATION_SECONDS = 10_800.0
DEFAULT_MIN_FREE_DISK_BYTES = 1024 * 1024 * 1024
DEFAULT_FFPROBE_TIMEOUT_SECONDS = 30.0
DEFAULT_FFMPEG_TIMEOUT_SECONDS = 900.0


def _default_data_dir() -> Path:
    return user_data_path("Mosaic Squash")


class Settings(BaseSettings):
    """Runtime settings for the loopback-only application."""

    model_config = SettingsConfigDict(
        env_prefix="MOSAIC_SQUASH_",
        extra="forbid",
    )

    data_dir: Path = Field(default_factory=_default_data_dir)
    host: str = "127.0.0.1"
    api_port: int = 8765
    web_port: int = 5173
    database_path: Path | None = None
    storage_root: Path | None = None
    max_upload_bytes: int = Field(default=DEFAULT_MAX_UPLOAD_BYTES, gt=0)
    max_video_duration_seconds: float = Field(
        default=DEFAULT_MAX_VIDEO_DURATION_SECONDS, gt=0
    )
    min_free_disk_bytes: int = Field(default=DEFAULT_MIN_FREE_DISK_BYTES, ge=0)
    ffprobe_timeout_seconds: float = Field(
        default=DEFAULT_FFPROBE_TIMEOUT_SECONDS, gt=0
    )
    ffmpeg_timeout_seconds: float = Field(
        default=DEFAULT_FFMPEG_TIMEOUT_SECONDS, gt=0
    )

    def proxy_timeout_for_duration(self, duration_seconds: float) -> float:
        """Give long recordings bounded preparation time; explicit limits win."""
        if "ffmpeg_timeout_seconds" in self.model_fields_set:
            return self.ffmpeg_timeout_seconds
        return max(self.ffmpeg_timeout_seconds, min(3600.0, duration_seconds / 2))

    @model_validator(mode="after")
    def derive_local_paths(self) -> Self:
        if self.database_path is None:
            self.database_path = self.data_dir / "squashvision.sqlite3"
        if self.storage_root is None:
            self.storage_root = self.data_dir / "storage"
        return self

    @field_validator("host")
    @classmethod
    def require_loopback(cls, host: str) -> str:
        if host != "127.0.0.1":
            raise ValueError("host must be 127.0.0.1")
        return host
