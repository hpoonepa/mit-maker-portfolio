"""literature.py — Per-target literature retrieval for the LLM scoring prior.

Fetches binder-relevant PubMed abstracts (NCBI E-utilities) and Open Targets
annotations (knownDrugs / tractability / safetyLiabilities) for a target, and
caches the combined result on disk so repeat scoring runs do no network I/O.

Everything here is stdlib-only (urllib + xml.etree.ElementTree) and DEFENSIVE:
any network/parse failure degrades to an empty result rather than crashing the
scoring pipeline. Tests never touch the live network — the fetchers are
monkeypatched and the parsers run on fixtures.

Cache layout: data/processed/literature/{TARGET}.json  (gitignored).
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

_HERE = os.path.dirname(__file__)
CACHE_DIR = os.path.join(_HERE, "..", "data", "processed", "literature")

_EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
_OPEN_TARGETS = "https://api.platform.opentargets.org/api/v4/graphql"

# Design/interface concept group — OR'd together and AND'd against the
# target/synonyms. Targets binder / protein-design / interface literature
# (how to DESIGN and SCORE a binder) rather than generic disease biology.
_DESIGN_TERMS = [
    "binder", '"binding protein"', '"de novo"', "miniprotein", "minibinder",
    "nanobody", '"single-domain antibody"', '"peptide inhibitor"',
    '"stapled peptide"', '"protein-protein interaction"',
    '"binding interface"', "interface", "epitope", "paratope", "hotspot",
    '"structure-based"', '"computational design"', "cocrystal",
    '"crystal structure"',
]

# Structure/epitope concept group — second sub-query, merged + deduped with the
# design query so we also surface the binding site / hotspot / structure papers.
_STRUCTURE_TERMS = [
    "epitope", '"binding site"', "hotspot", "residues",
    '"crystal structure"', '"cryo-EM"',
]

# Polite NCBI rate limit: 3 req/s without a key, more with one. ~0.34s is safe.
_RATE_LIMIT_S = 0.34

_TIMEOUT = 20


# --- query building --------------------------------------------------------


def build_pubmed_query(
    target_name: str, synonyms: list[str], terms: list[str] | None = None
) -> str:
    """Build an NCBI E-utilities ``term`` query string.

    Combines the target name + synonyms (OR'd) AND'd with a concept term group
    (defaults to the design/interface group ``_DESIGN_TERMS``). Quoted terms
    (e.g. "binding site") are preserved verbatim.
    """
    names = [target_name] + [s for s in (synonyms or []) if s]
    # Dedup while preserving order.
    seen: set[str] = set()
    uniq = []
    for n in names:
        if n not in seen:
            seen.add(n)
            uniq.append(n)
    name_group = " OR ".join(uniq)
    term_group = " OR ".join(terms if terms is not None else _DESIGN_TERMS)
    return f"({name_group}) AND ({term_group})"


# --- XML parsing -----------------------------------------------------------


def parse_efetch_xml(xml: str) -> list[dict]:
    """Parse PubMed efetch XML into ``[{pmid, title, abstract}]``.

    Missing abstracts become an empty string. Structured abstracts (multiple
    <AbstractText> sections) are joined with spaces. Malformed XML -> ``[]``.
    """
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []

    out: list[dict] = []
    for article in root.iter("PubmedArticle"):
        pmid_el = article.find(".//PMID")
        pmid = pmid_el.text.strip() if pmid_el is not None and pmid_el.text else ""

        title_el = article.find(".//Article/ArticleTitle")
        title = "".join(title_el.itertext()).strip() if title_el is not None else ""

        abstract_parts = []
        for at in article.findall(".//Abstract/AbstractText"):
            text = "".join(at.itertext()).strip()
            if text:
                abstract_parts.append(text)
        abstract = " ".join(abstract_parts)

        out.append({"pmid": pmid, "title": title, "abstract": abstract})
    return out


# --- network fetchers ------------------------------------------------------


def _http_get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "papercrane-binder-scorer"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _api_key_suffix() -> str:
    key = os.environ.get("NCBI_API_KEY")
    return f"&api_key={urllib.parse.quote(key)}" if key else ""


def _esearch_pmids(query: str, retmax: int) -> list[str]:
    """Run a single esearch and return its PMID list (relevance-sorted)."""
    suffix = _api_key_suffix()
    esearch_url = (
        f"{_EUTILS}/esearch.fcgi?db=pubmed"
        f"&term={urllib.parse.quote(query)}"
        f"&retmax={int(retmax)}&retmode=json&sort=relevance{suffix}"
    )
    raw = _http_get(esearch_url)
    time.sleep(_RATE_LIMIT_S)
    return json.loads(raw).get("esearchresult", {}).get("idlist", [])


def _efetch_records(pmids: list[str]) -> list[dict]:
    """efetch + parse for a list of PMIDs. ``[]`` if no PMIDs."""
    if not pmids:
        return []
    suffix = _api_key_suffix()
    efetch_url = (
        f"{_EUTILS}/efetch.fcgi?db=pubmed"
        f"&id={','.join(pmids)}&retmode=xml{suffix}"
    )
    xml = _http_get(efetch_url)
    time.sleep(_RATE_LIMIT_S)
    return parse_efetch_xml(xml)


def fetch_pubmed_abstracts(
    target_name: str, synonyms: list[str], retmax: int = 18
) -> list[dict]:
    """Fetch DESIGN/INTERFACE-relevant abstracts for a target.

    Issues two relevance-sorted sub-queries — a design/interface query and a
    structure/epitope query — merges their PMIDs (design-first, deduped), caps
    at ``retmax``, and efetches them in one request. Returns ``[]`` on any
    network error.
    """
    try:
        sub_queries = [
            build_pubmed_query(target_name, synonyms, _DESIGN_TERMS),
            build_pubmed_query(target_name, synonyms, _STRUCTURE_TERMS),
        ]
        per_query = max(int(retmax), 1)
        pmids: list[str] = []
        seen: set[str] = set()
        for query in sub_queries:
            for pid in _esearch_pmids(query, per_query):
                if pid and pid not in seen:
                    seen.add(pid)
                    pmids.append(pid)
        pmids = pmids[: int(retmax)]
        return _efetch_records(pmids)
    except Exception:
        return []


_OT_SEARCH_QUERY = """
query Search($q: String!) {
  search(queryString: $q, entityNames: ["target"], page: {index: 0, size: 1}) {
    hits { id name entity }
  }
}
"""

_OT_TARGET_QUERY = """
query Target($id: String!) {
  target(ensemblId: $id) {
    id
    approvedSymbol
    approvedName
    tractability { label modality value }
    safetyLiabilities { event eventId datasource }
    drugAndClinicalCandidates { count }
  }
}
"""


def _ot_post(query: str, variables: dict) -> dict:
    body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    req = urllib.request.Request(
        _OPEN_TARGETS,
        data=body,
        headers={"Content-Type": "application/json",
                 "User-Agent": "papercrane-binder-scorer"},
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def fetch_open_targets(uniprot: str) -> dict:
    """Resolve a UniProt accession to an Open Targets target and fetch
    knownDrugs / tractability / safetyLiabilities. ``{}`` on any failure.
    """
    if not uniprot:
        return {}
    try:
        hits = (
            _ot_post(_OT_SEARCH_QUERY, {"q": uniprot})
            .get("data", {})
            .get("search", {})
            .get("hits", [])
        )
        if not hits:
            return {}
        ensembl_id = hits[0].get("id")
        if not ensembl_id:
            return {}
        target = (
            _ot_post(_OT_TARGET_QUERY, {"id": ensembl_id})
            .get("data", {})
            .get("target")
        )
        return target or {}
    except Exception:
        return {}


# --- top-level gather + cache ----------------------------------------------


def _cache_path(target_name: str) -> str:
    return os.path.join(CACHE_DIR, f"{target_name}.json")


def gather_literature(
    target_name: str, synonyms: list[str], uniprot: str
) -> dict:
    """Return ``{"abstracts": [...], "open_targets": {...}}`` for a target.

    Reads from the on-disk cache if present (no network); otherwise fetches
    both sources, writes the cache, and returns the result.
    """
    path = _cache_path(target_name)
    if os.path.exists(path):
        try:
            with open(path) as fh:
                return json.load(fh)
        except (OSError, ValueError):
            pass  # corrupt cache -> re-fetch

    result = {
        "abstracts": fetch_pubmed_abstracts(target_name, synonyms),
        "open_targets": fetch_open_targets(uniprot),
    }

    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(path, "w") as fh:
        json.dump(result, fh, indent=2)
    return result
