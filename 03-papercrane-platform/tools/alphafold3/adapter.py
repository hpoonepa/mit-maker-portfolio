"""Legacy AlphaFold 3 remote adapter for Paper Crane.

Paper Crane's production AlphaFold 3-compatible path uses the open-source
Protenix Modal backend in ``modal_app.py``. This optional adapter calls a
separately hosted service for deployments that provide one.

Env vars consumed at runtime:
    AF3_API_ENDPOINT  (optional; overrides manifest.endpoint)
    AF3_API_TOKEN     (required; Bearer token from Isomorphic Labs)

The adapter subclasses ``RemoteAdapter`` because it makes an HTTPS request.
"""

from __future__ import annotations

import json
import os
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

# TODO: replace inline stubs with the real SDK imports once
#       `papercrane_sdk` is published:
#           from papercrane_sdk import RemoteAdapter, Job, RawOutput, AdapterError
try:  # pragma: no cover - real SDK path
    from papercrane_sdk import RemoteAdapter, Job, RawOutput, AdapterError  # type: ignore
except ImportError:  # pragma: no cover - stubs for standalone tests
    class AdapterError(RuntimeError):
        """Raised when an adapter cannot fulfil a job."""

    @dataclass
    class Job:
        id: str
        workdir: Path
        input: Dict[str, Any]
        params: Dict[str, Any]

    @dataclass
    class RawOutput:
        workdir: Path
        artifacts: Dict[str, Path]
        metrics: Dict[str, Any]

    class RemoteAdapter:
        """Stub base. Real version lives in papercrane_sdk and handles
        manifest loading, schema validation, retry policy, and sandboxing."""

        manifest_path: Path = Path(__file__).parent / "manifest.json"

        def __init__(self) -> None:
            self.manifest = json.loads(self.manifest_path.read_text())

        def run(self, job: Job) -> RawOutput:  # pragma: no cover
            raise NotImplementedError


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

POLL_INTERVAL_SEC = 5
MAX_POLL_SECONDS = 30 * 60  # 30 minutes
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3


class AlphaFold3Adapter(RemoteAdapter):
    """Submits jobs to the AF3 HTTPS API and returns per-seed CIF + metrics."""

    def run(self, job: Job) -> RawOutput:
        transport = self.manifest["transport"]
        if transport.get("type") != "https":
            raise AdapterError(
                f"AF3 adapter requires https transport, got {transport.get('type')!r}"
            )
        endpoint = os.getenv("AF3_API_ENDPOINT") or transport["endpoint"]
        token = os.getenv("AF3_API_TOKEN")
        if not token:
            raise AdapterError(
                "AF3_API_TOKEN env var is required. Obtain a token from "
                "Isomorphic Labs; Paper Crane does not proxy credentials."
            )

        request_body = self._build_request(job)
        submit = self._request_with_retry(
            method="POST",
            url=endpoint,
            token=token,
            json_body=request_body,
        )
        job_id = submit["job_id"]

        result = self._poll_until_done(
            endpoint=endpoint, token=token, job_id=job_id
        )

        artifacts = self._download_artifacts(
            endpoint=endpoint, token=token, job_id=job_id,
            predictions=result["predictions"], workdir=job.workdir,
        )

        return RawOutput(
            workdir=job.workdir,
            artifacts=artifacts,
            metrics={"predictions": result["predictions"]},
        )

    # -- helpers -----------------------------------------------------------

    def _build_request(self, job: Job) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "chains": job.input["chains"],
            "params": job.input.get("params", self.manifest["defaultParams"]),
            "seeds": job.input["seeds"],
        }
        if job.input.get("ligands"):
            body["ligands"] = job.input["ligands"]
        return body

    def _request_with_retry(
        self,
        *,
        method: str,
        url: str,
        token: str,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        import urllib.error
        import urllib.request

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        data = json.dumps(json_body).encode("utf-8") if json_body is not None else None
        last_err: Optional[Exception] = None

        for attempt in range(1, MAX_ATTEMPTS + 1):
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code in RETRYABLE_STATUS and attempt < MAX_ATTEMPTS:
                    time.sleep(self._backoff(attempt))
                    last_err = e
                    continue
                raise AdapterError(f"AF3 API error {e.code}: {e.reason}") from e
            except urllib.error.URLError as e:
                last_err = e
                if attempt < MAX_ATTEMPTS:
                    time.sleep(self._backoff(attempt))
                    continue
                raise AdapterError(f"AF3 API unreachable: {e}") from e

        raise AdapterError(f"AF3 API retries exhausted: {last_err}")

    def _poll_until_done(
        self, *, endpoint: str, token: str, job_id: str
    ) -> Dict[str, Any]:
        status_url = f"{endpoint.rstrip('/')}/{job_id}"
        deadline = time.monotonic() + MAX_POLL_SECONDS
        while time.monotonic() < deadline:
            payload = self._request_with_retry(
                method="GET", url=status_url, token=token
            )
            state = payload.get("status")
            if state == "succeeded":
                return payload["result"]
            if state == "failed":
                raise AdapterError(
                    f"AF3 job {job_id} failed: {payload.get('error', 'unknown')}"
                )
            time.sleep(POLL_INTERVAL_SEC)
        raise AdapterError(
            f"AF3 job {job_id} exceeded {MAX_POLL_SECONDS}s poll budget"
        )

    def _download_artifacts(
        self,
        *,
        endpoint: str,
        token: str,
        job_id: str,
        predictions: List[Dict[str, Any]],
        workdir: Path,
    ) -> Dict[str, Path]:
        import urllib.request

        workdir.mkdir(parents=True, exist_ok=True)
        artifacts: Dict[str, Path] = {}
        for idx, pred in enumerate(predictions):
            rel = pred["structurePath"]
            local = workdir / rel
            local.parent.mkdir(parents=True, exist_ok=True)
            url = f"{endpoint.rstrip('/')}/{job_id}/artifacts/{rel}"
            req = urllib.request.Request(
                url, headers={"Authorization": f"Bearer {token}"}
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                local.write_bytes(resp.read())
            artifacts[f"prediction_{idx:04d}.cif"] = local
        return artifacts

    @staticmethod
    def _backoff(attempt: int) -> float:
        base = 2 ** (attempt - 1)
        jitter = random.uniform(0, 0.5)
        return base + jitter
