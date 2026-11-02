from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

backend_root = Path(__file__).resolve().parents[3] / "src/squashvision/backend"
sys.path.insert(0, str(backend_root))

from squashvision.app import create_app
from squashvision.schemas import ExportSelection
from squashvision.settings import Settings


@pytest.mark.parametrize(
    "name",
    [
        "", ".", "../escape", "data/../escape", "/absolute", "C:/drive.txt",
        "data//empty.csv", "data/./dot.csv", "data\\windows.csv", "nul\x00.csv",
        "control\x07.csv", "trailing. ", "CON", "data/A.csv", "data/a.csv",
    ],
)
def test_archive_member_validation_rejects_unsafe_and_case_colliding_names(name: str) -> None:
    from squashvision.exports import validate_archive_members

    candidates = ["data/a.csv", name] if name != "data/a.csv" else ["data/A.csv", name]
    with pytest.raises(ValueError):
        validate_archive_members(candidates)


def test_archive_member_validation_rejects_non_regular_staging_entries(tmp_path: Path) -> None:
    from squashvision.exports import validate_staging_tree

    stage = tmp_path / "stage"
    stage.mkdir()
    (stage / "regular.txt").write_text("ok")
    os.symlink(stage / "regular.txt", stage / "link.txt")
    with pytest.raises(ValueError, match="regular"):
        validate_staging_tree(stage, ["regular.txt", "link.txt"])

    (stage / "link.txt").unlink()
    fifo = stage / "pipe"
    os.mkfifo(fifo)
    try:
        with pytest.raises(ValueError, match="regular"):
            validate_staging_tree(stage, ["regular.txt", "pipe"])
    finally:
        if fifo.exists() and stat.S_ISFIFO(fifo.lstat().st_mode):
            fifo.unlink()


def test_export_selection_has_hard_count_duration_and_format_bounds() -> None:
    with pytest.raises(ValidationError):
        ExportSelection(formats=())
    with pytest.raises(ValidationError):
        ExportSelection(formats=("json", "json"))
    with pytest.raises(ValidationError):
        ExportSelection(formats=("pdf",))
    with pytest.raises(ValidationError):
        ExportSelection(formats=("json",), evidence_ids=tuple(f"e-{index}" for index in range(101)))
    with pytest.raises(ValidationError):
        ExportSelection(formats=("json",), evidence_ids=("e",), evidence_duration_seconds=0)
    with pytest.raises(ValidationError):
        ExportSelection(formats=("json",), evidence_ids=("e",), evidence_duration_seconds=31)


@pytest.mark.asyncio
async def test_production_static_serving_never_shadows_api_or_exposes_files(tmp_path: Path) -> None:
    static = tmp_path / "dist"
    assets = static / "assets"
    assets.mkdir(parents=True)
    (static / "index.html").write_text("<!doctype html><title>SquashVision</title>")
    (assets / "app.js").write_text("console.log('app')")
    (assets / "app.js.map").write_text("secret sources")
    outside = tmp_path / "secret.txt"
    outside.write_text("host secret")
    os.symlink(outside, assets / "link.txt")

    app = create_app(Settings(data_dir=tmp_path / "data", min_free_disk_bytes=0), static_dir=static)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        health = await client.get("/api/v1/health")
        assert health.status_code == 200 and health.headers["content-type"].startswith("application/json")
        missing_api = await client.get("/api/v1/not-a-route")
        assert missing_api.status_code == 404 and missing_api.json()["code"] == "route_not_found"
        api_root = await client.get("/api")
        assert api_root.status_code == 404
        assert api_root.headers["content-type"].startswith("application/json")
        assert api_root.json()["code"] == "route_not_found"
        navigation = await client.get("/matches/abc/analysis")
        assert navigation.status_code == 200 and "SquashVision" in navigation.text
        head = await client.head("/matches/abc/analysis")
        assert head.status_code == 200 and head.text == ""
        asset = await client.get("/assets/app.js")
        assert asset.status_code == 200 and "console.log" in asset.text
        assert (await client.get("/assets/app.js.map")).status_code == 404
        assert (await client.get("/assets/link.txt")).status_code == 404
        assert (await client.get("/%2e%2e/secret.txt")).status_code == 404
        assert (await client.get("/assets/")).status_code == 404
        assert (await client.post("/matches/abc/analysis")).status_code == 405


def test_settings_reject_every_non_loopback_host() -> None:
    for host in ("0.0.0.0", "::", "::1", "localhost", "192.168.1.4", "127.0.0.2"):
        with pytest.raises(ValidationError):
            Settings(host=host)
