# SPDX-License-Identifier: MIT
"""Conservative source-span extraction and explicitly uncalibrated evidence ranking.

No LLM, network or automatic verification is involved. Supplied paper text is
not authenticated. A curator must verify target/numbering, assay, direction and
citation before any draft can influence ranking.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Sequence

from ..residue import ResidueKey
from .grader import row_to_mapping
from .table import Direction, EvidenceClass, EvidenceRow, row_from_mapping

_RESIDUE = re.compile(r"\b(?:[A-Z][a-z]{2}|[A-Z])[- ]?(\d{1,5})(?!\d)")
_SENTENCE = re.compile(r"[^.!?\n]+(?:[.!?]|$)")


def extract_documents(documents: list[dict[str, Any]], residues: Sequence[ResidueKey]) -> dict:
    """Return only verbatim source spans containing explicit residue mentions.

A document declares the author-chain mapping (``chain``); otherwise extraction
is allowed only when the candidate residues occupy a single chain. Sequence
number offsets are never guessed. Each match is an unreviewed draft requiring source verification.
"""
    if not isinstance(documents, list) or len(documents) > 20:
        raise ValueError("source_documents must be a list of at most 20 documents")
    drafts, sources = [], []
    chains = {r.auth_asym_id for r in residues}
    for document in documents:
        if not isinstance(document, dict) or set(document) - {"source", "text", "chain"}:
            raise ValueError("Each document needs source, text and optional chain")
        text, source = document.get("text"), document.get("source")
        if not isinstance(text, str) or not text.strip() or len(text) > 200000:
            raise ValueError("Each source text must contain 1–200000 characters")
        chain = document.get("chain")
        if chain is None and len(chains) == 1:
            chain = next(iter(chains))
        if chain not in chains:
            raise ValueError("Specify the source's author-chain mapping for a candidate chain")
        # Validate identifiers even when there are no matching residue sentences.
        probe = row_from_mapping({"residues": [str(next(r for r in residues if r.auth_asym_id == chain))],
            "claim": "Identifier validation", "source": source,
            "evidence_class": "ASSERTION", "direction": "SUPPORTS", "reviewed": False})
        digest = hashlib.sha256(text.encode()).hexdigest()
        sources.append({"source": probe.source, "sha256": digest, "characters": len(text),
                        "verification": "user_supplied_text_not_authenticated"})
        for span in _SENTENCE.finditer(text):
            quote = span.group().strip()
            start = span.start() + len(span.group()) - len(span.group().lstrip())
            end = start + len(quote)
            numbers = {int(match.group(1)) for match in _RESIDUE.finditer(quote)}
            keys = [r for r in residues if r.auth_asym_id == chain and r.auth_seq_id in numbers and not r.icode.strip()]
            if not keys:
                continue
            if re.search(r"mutan|mutagen|substitut|alanine.scan", quote, re.I):
                kind = "MUTAGENESIS"
            elif re.search(r"assay|binding affinity|dissociation constant|\bKD\b|\bIC50\b", quote, re.I):
                kind = "FUNCTIONAL_ASSAY"
            else:
                kind = "ASSERTION"
            direction = "REFUTES" if re.search(r"no (?:significant )?effect|did not affect|unchanged", quote, re.I) else "SUPPORTS"
            row = row_from_mapping({"residues": list(map(str, keys)), "claim": quote,
                "source": probe.source, "evidence_class": kind, "direction": direction,
                "reviewed": False, "notes": f"Rule-based draft; verify target, numbering, experimental class and direction. Source SHA256 {digest}; character span {start}:{end}."})
            drafts.append({**row_to_mapping(row), "quote": quote, "source_sha256": digest,
                           "span_start": start, "span_end": end})
    return {"method": "rule_based_verbatim_extraction_not_an_LLM", "sources": sources,
            "drafts": drafts, "review_required": True}


def evidence_score(keys: Sequence[ResidueKey], rows: Sequence[EvidenceRow]) -> dict:
    """Signed fraction of patch residues with reviewed experimental support.

One citation cannot earn extra weight by being repeated. Conflicting evidence
is kept visible. Structural rank breaks ties; this score is not calibrated to
binding probability and has no demonstrated predictive improvement.
"""
    covered = set(keys)
    eligible = [r for r in rows if r.reviewed and r.reviewer and r.evidence_class in (
        EvidenceClass.FUNCTIONAL_ASSAY, EvidenceClass.MUTAGENESIS) and covered.intersection(r.residues)]
    positive = {k for r in eligible if r.direction == Direction.SUPPORTS for k in r.residues if k in covered}
    negative = {k for r in eligible if r.direction == Direction.REFUTES for k in r.residues if k in covered}
    return {"score": (len(positive) - len(negative)) / len(covered) if covered else 0.0,
            "supported_residues": sorted(map(str, positive)), "refuted_residues": sorted(map(str, negative)),
            "conflicting_residues": sorted(map(str, positive & negative)),
            "sources": sorted({r.source for r in eligible}),
            "reviewers": sorted({r.reviewer for r in eligible}),
            "status": "reviewed_experimental_evidence" if eligible else "no_reviewed_experimental_evidence"}


def rank_with_evidence(sites: Any, rows: Sequence[EvidenceRow], mode: str = "structural") -> dict:
    """Rerank proposals using reviewed experimental evidence, then structural order."""
    if mode not in ("structural", "evidence"):
        raise ValueError("ranking must be structural or evidence")
    annotations = {}
    for rank, site in enumerate(sites.ranked, 1):
        key = tuple(sorted(map(str, site.patch.residues)))
        annotations[key] = {"structural_rank": rank, "structural_score": site.score,
                            "evidence": evidence_score(site.patch.residues, rows)}
    if mode == "evidence":
        if not any(a["evidence"]["sources"] for a in annotations.values()):
            raise ValueError("Evidence ranking requires reviewed experimental evidence covering a candidate site")
        sites.ranked.sort(key=lambda site: (
            -annotations[tuple(sorted(map(str, site.patch.residues)))]["evidence"]["score"],
            annotations[tuple(sorted(map(str, site.patch.residues)))]["structural_rank"],
        ))
    return annotations
