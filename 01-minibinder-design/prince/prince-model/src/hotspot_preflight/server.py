# SPDX-License-Identifier: MIT
"""Loopback-only PRINCE JSON service over the existing structural analysis core.

Run ``preflight serve --allow-origin http://localhost:4325``. Uploaded structures
are temporary and never sent to an LLM. PDB retrieval uses only the fixed PDBe
endpoint. This local research service is not a public multi-user deployment.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .predict.geometric import GeometricPredictor
from .predict.profiles import get_profile
from .propose import propose_sites, to_propose_record
from .record import to_run_record
from .report import run_preflight, select_assembly
from .residue import parse_hotspot_spec
from .structure import load_target

MAX_BYTES = 8 * 1024 * 1024
ROOT = Path(__file__).resolve().parents[2]


def validation_status() -> dict[str, Any]:
    artifact = Path(__file__).parent / "model/prince_connected.json"
    if artifact.is_file():
        data = json.loads(artifact.read_text())
        data.pop("split_ids", None)
        return data
    return {"status": "evaluation_artifact_unavailable", "model_type": "logistic regression; not an LLM",
            "limitations": ["No evaluation artifact installed. No 83% recovery claim is supported."]}


def analyze(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {"pdb_id", "structure_text", "filename", "chain", "assembly", "profile", "top", "hotspots", "evidence_yaml", "source_documents", "ranking"}
    if not isinstance(payload, dict) or set(payload) - allowed:
        raise ValueError("Expected a JSON object containing only documented analysis fields")
    pdb_id, text = payload.get("pdb_id"), payload.get("structure_text")
    if bool(pdb_id) == bool(text):
        raise ValueError("Supply exactly one of pdb_id or structure_text")
    top = payload.get("top", 3)
    if isinstance(top, bool) or not isinstance(top, int) or not 1 <= top <= 10:
        raise ValueError("top must be an integer from 1 to 10")
    for key in ("chain", "assembly", "profile", "hotspots", "filename", "evidence_yaml", "ranking"):
        if payload.get(key) is not None and not isinstance(payload[key], str):
            raise ValueError(f"{key} must be a string")
    if pdb_id is not None and (not isinstance(pdb_id, str) or not re.fullmatch(r"[0-9][A-Za-z0-9]{3}", pdb_id)):
        raise ValueError("pdb_id must be a four-character PDB identifier, not a path or URL")
    profile = get_profile(payload.get("profile") or "antibody_epitope")
    with tempfile.TemporaryDirectory(prefix="prince-") as directory:
        if pdb_id:
            from .cli import PDBE_UPDATED_CIF_URL
            filename = f"{pdb_id.lower()}_updated.cif"
            cache = Path(os.environ.get("HOTSPOT_PREFLIGHT_CACHE", ".cache")) / filename
            if cache.is_file():
                if cache.stat().st_size > MAX_BYTES:
                    raise ValueError("Structure exceeds the 8 MiB local service limit")
                text = cache.read_text()
            else:
                request = urllib.request.Request(PDBE_UPDATED_CIF_URL.format(entry=pdb_id.lower()))
                with urllib.request.urlopen(request, timeout=20) as response:
                    body = response.read(MAX_BYTES + 1)
                if len(body) > MAX_BYTES:
                    raise ValueError("Structure exceeds the 8 MiB local service limit; use the CLI")
                text = body.decode("utf-8")
        else:
            filename = payload.get("filename") or "upload.cif"
            if Path(filename).name != filename or "\\" in filename or filename in (".", ".."):
                raise ValueError("filename must be a basename, not a path")
            if Path(filename).suffix.lower() not in (".cif", ".mmcif", ".pdb"):
                raise ValueError("filename must end in .cif, .mmcif or .pdb")
        if not isinstance(text, str) or not text.strip() or len(text.encode()) > MAX_BYTES:
            raise ValueError("structure_text must be nonempty text up to 8 MiB")
        path = Path(directory) / filename
        path.write_text(text)
        target = load_target(path)
        if len(target.st) != 1:
            raise ValueError("Local service accepts single-model structures; select a model with the CLI first")
        if sum(len(res) for c in target.st[0] for res in c) > 100000:
            raise ValueError("Structure exceeds the local service atom limit; use the CLI")
        select_assembly(target, payload.get("assembly"))
        sites = propose_sites(target, GeometricPredictor(profile=profile), chain=payload.get("chain"))
        evidence = None
        if payload.get("evidence_yaml"):
            from .evidence.table import load_table
            evidence_file = Path(directory) / "evidence.yaml"
            evidence_file.write_text(payload["evidence_yaml"])
            evidence = load_table(evidence_file)
        from .evidence.extract import extract_documents, rank_with_evidence
        ranking = payload.get("ranking", "structural")
        annotations = rank_with_evidence(sites, evidence or [], ranking)
        extraction = extract_documents(payload.get("source_documents", []),
            sorted({key for site in sites.ranked for key in site.patch.residues}))
        proposal = to_propose_record(sites, top)
        proposal["ranking"] = ranking
        for patch, site in zip(proposal["patches"], sites.top(top)):
            patch.update(annotations[tuple(sorted(map(str, site.patch.residues)))])
        checks = []
        for rank, site in enumerate(sites.top(top), 1):
            keys = sorted(site.patch.residues)
            spec = ",".join(map(str, keys))
            run = run_preflight(target, keys, hotspot_spec=spec, evidence_rows=evidence)
            checks.append({"rank": rank, "residues": list(map(str, keys)), "record": to_run_record(run)})
        selected = None
        if payload.get("hotspots"):
            selected = to_run_record(run_preflight(target, parse_hotspot_spec(payload["hotspots"]),
                hotspot_spec=payload["hotspots"], evidence_rows=evidence))
        return {"schema_version": 1,
                "target": {"id": target.entry_id, "chains": target.chain_ids,
                           "chain": sites.chain, "assembly_id": sites.assembly_id},
                "proposal": proposal, "checks": checks,
                "selected_check": selected, "validation": validation_status(),
                "evidence": {"status": "reviewed_table_supplied" if evidence is not None else "not_supplied",
                             "affects": "reviewed experimental rows rerank sites when ranking=evidence; otherwise checks only",
                             "ranking": ranking, "extraction": extraction, "llm_trained": False,
                             "limitation": "Evidence ranking is uncalibrated; predictive improvement has not been measured."}}


def make_server(port: int, allow_origins: list[str]) -> HTTPServer:
    origins = set(allow_origins)
    for origin in origins:
        parsed = urlsplit(origin)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.path or parsed.query or parsed.fragment:
            raise ValueError("Allowed origins must be exact http(s) origins without paths")

    class Handler(BaseHTTPRequestHandler):
        server_version = "PRINCE/1"
        def log_message(self, *_args):
            pass  # Do not log uploaded content, query strings, or target identifiers.

        def _allowed(self) -> bool:
            host = self.headers.get("Host", "")
            if host not in {f"127.0.0.1:{port}", f"localhost:{port}"}:
                self._json(403, {"error": {"code": "host_denied", "message": "Loopback Host required"}})
                return False
            origin = self.headers.get("Origin")
            if origin and origin not in origins:
                self._json(403, {"error": {"code": "origin_denied", "message": "Browser origin not allowed"}})
                return False
            return True

        def _json(self, status: int, data: dict) -> None:
            body = json.dumps(data, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            origin = self.headers.get("Origin")
            if origin in origins:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Access-Control-Allow-Private-Network", "true")
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):
            if self._allowed():
                self._json(200, {"ok": True})

        def do_GET(self):
            if not self._allowed():
                return
            if self.path == "/api/health":
                self._json(200, {"status": "ok", "schema_version": 1, "service": "PRINCE"})
            elif self.path == "/api/validation":
                self._json(200, validation_status())
            else:
                self._json(404, {"error": {"code": "not_found", "message": "Unknown endpoint"}})

        def do_POST(self):
            if not self._allowed():
                return
            if self.path != "/api/analyze":
                self._json(404, {"error": {"code": "not_found", "message": "Unknown endpoint"}})
                return
            if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                self._json(415, {"error": {"code": "content_type", "message": "Use application/json"}})
                return
            try:
                if self.headers.get("Transfer-Encoding"):
                    raise ValueError("Transfer-Encoding is unsupported")
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= MAX_BYTES:
                    raise ValueError("JSON request must be nonempty and at most 8 MiB")
                self.connection.settimeout(30)
                payload = json.loads(self.rfile.read(size))
                self._json(200, analyze(payload))
            except (ValueError, UnicodeError, RuntimeError) as exc:
                self._json(400, {"error": {"code": "invalid_input", "message": str(exc)}})
            except OSError:
                self._json(502, {"error": {"code": "structure_unavailable", "message": "Structure fetch or temporary storage failed; try a local upload"}})

    server = HTTPServer(("127.0.0.1", port), Handler)
    server.timeout = 30
    return server


def serve(port: int = 8765, allow_origins: list[str] | None = None) -> None:
    server = make_server(port, allow_origins or ["http://localhost:4321", "http://127.0.0.1:4321"])
    print(f"PRINCE ready on http://127.0.0.1:{port}", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
