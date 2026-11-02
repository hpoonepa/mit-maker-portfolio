# SPDX-License-Identifier: MIT
"""CLI boundaries for the local service and combined evidence analysis."""
from __future__ import annotations
import json
from pathlib import Path
import typer
from .server import analyze, serve


def serve_command(
    port: int = typer.Option(8765, min=1024, max=65535),
    allow_origin: list[str] = typer.Option(
        ["http://localhost:4321", "http://127.0.0.1:4321"], "--allow-origin",
        help="Exact allowed browser origin; repeatable. Service binds loopback only.",
    ),
) -> None:
    """Serve the real analysis API on 127.0.0.1 (local use only)."""
    try:
        serve(port=port, allow_origins=allow_origin)
    except (ValueError, OSError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(3) from None


def analyze_command(
    structure: str = typer.Argument(..., help="Local PDB/mmCIF file or public PDB ID"),
    chain: str | None = typer.Option(None),
    profile: str = typer.Option("antibody_epitope"),
    top: int = typer.Option(3, min=1, max=10),
    hotspots: str | None = typer.Option(None),
    evidence: Path | None = typer.Option(None, help="Reviewed evidence YAML; never auto-approved"),
    sources: Path | None = typer.Option(None, help="JSON list of source, text and optional chain objects"),
    ranking: str = typer.Option("structural", help="structural or evidence"),
    json_out: Path | None = typer.Option(None, "--json"),
) -> None:
    """Analyze real structures, extract source-grounded drafts and rank reviewed evidence."""
    try:
        payload = {"chain": chain, "profile": profile, "top": top,
                   "hotspots": hotspots, "ranking": ranking}
        path = Path(structure)
        if path.is_file():
            payload.update(structure_text=path.read_text(), filename=path.name)
        else:
            payload["pdb_id"] = structure
        if evidence:
            payload["evidence_yaml"] = evidence.read_text()
        if sources:
            payload["source_documents"] = json.loads(sources.read_text())
        result = json.dumps(analyze(payload), indent=2, allow_nan=False) + "\n"
        if json_out:
            json_out.write_text(result)
            typer.echo(f"Wrote analysis to {json_out}")
        else:
            typer.echo(result, nl=False)
    except (ValueError, OSError, RuntimeError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(3) from None
