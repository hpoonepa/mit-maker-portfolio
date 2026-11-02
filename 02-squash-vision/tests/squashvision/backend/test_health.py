import sys
from pathlib import Path

backend_root = Path(__file__).resolve().parents[3] / "src/squashvision/backend"
sys.path.insert(0, str(backend_root))

import pytest
from httpx import ASGITransport, AsyncClient

from squashvision.app import create_app
from squashvision.settings import Settings


@pytest.mark.asyncio
async def test_health_is_local_and_reports_dependencies(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path))
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["ffmpeg"]["status"] == "ready"
    assert set(response.json()) == {
        "status",
        "version",
        "ffmpeg",
        "worker",
        "models",
    }


def test_settings_rejects_non_loopback_host(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        Settings(data_dir=tmp_path, host="0.0.0.0")
