"""RemoteAdapter — base class for closed-weight HTTPS-backed tools.

Mirrors `RemoteAdapter` in `packages/tools-sdk/src/adapter.ts`. Uses stdlib
`urllib.request` to avoid pulling heavy deps (`httpx`, `requests`) into the
minimal SDK surface; subclasses that want a fancier client can inject one via
the `http_post` hook.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable, Optional
from urllib.parse import urljoin

from .adapter import Adapter


PostHook = Callable[[str, Any, dict[str, str], Optional[int]], Any]
"""Signature: (url, payload, headers, timeout_ms) -> response dict."""


def _default_post(url: str, payload: Any, headers: dict[str, str], timeout_ms: Optional[int]) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url=url, data=body, headers=headers, method="POST")
    timeout_s = (timeout_ms / 1000) if timeout_ms else None
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310 (https only)
            raw = resp.read()
            content_type = resp.headers.get("content-type", "")
            data: Any
            if "application/json" in content_type:
                data = json.loads(raw.decode("utf-8")) if raw else None
            else:
                data = raw.decode("utf-8")
            return {"status": resp.status, "headers": dict(resp.headers), "data": data}
    except urllib.error.HTTPError as e:
        raw = e.read()
        return {"status": e.code, "headers": dict(e.headers), "data": raw.decode("utf-8", errors="replace")}


class RemoteAdapter(Adapter):
    """Base class for closed-weight HTTPS-backed tools (e.g. AlphaFold 3).

    The contract is identical to ``Adapter`` — only ``run()`` differs: it calls
    an HTTPS endpoint instead of spawning a container. Subclasses access
    ``self.post_json(path, payload)`` to make requests; auth headers are set up
    in the constructor from ``api_key`` + ``extra_headers``.
    """

    def __init__(
        self,
        endpoint: str,
        api_key: Optional[str] = None,
        extra_headers: Optional[dict[str, str]] = None,
        http_post: Optional[PostHook] = None,
    ) -> None:
        if not endpoint:
            raise ValueError("RemoteAdapter requires a non-empty endpoint")
        self.endpoint: str = endpoint
        headers: dict[str, str] = {"content-type": "application/json"}
        if api_key:
            headers["authorization"] = f"Bearer {api_key}"
        if extra_headers:
            headers.update(extra_headers)
        self._headers: dict[str, str] = headers
        self._http_post: PostHook = http_post or _default_post

    def post_json(self, path: str, payload: Any, timeout_ms: Optional[int] = None) -> Any:
        """POST ``payload`` as JSON to ``endpoint + path`` and return the parsed response."""
        url = path if path.startswith(("http://", "https://")) else urljoin(self._ensure_slash(self.endpoint), path.lstrip("/"))
        return self._http_post(url, payload, dict(self._headers), timeout_ms)

    @staticmethod
    def _ensure_slash(url: str) -> str:
        return url if url.endswith("/") else url + "/"


__all__ = ["RemoteAdapter", "PostHook"]
