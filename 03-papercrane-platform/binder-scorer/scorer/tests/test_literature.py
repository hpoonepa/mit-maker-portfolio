"""Tests for scorer.literature — PubMed + Open Targets retrieval and caching.

NO live network here. Network-touching functions are exercised only via
monkeypatch; the pure parsers/query-builders are tested directly on fixtures.
"""

from __future__ import annotations

import json

import pytest

from scorer import literature


# --- build_pubmed_query ---


def test_build_pubmed_query_includes_target_and_synonym():
    q = literature.build_pubmed_query("EGFR", ["ERBB1", "HER1"])
    assert "EGFR" in q
    assert "ERBB1" in q


def test_build_pubmed_query_includes_design_interface_terms():
    # The default query targets DESIGN / INTERFACE / EPITOPE literature,
    # not generic disease biology.
    q = literature.build_pubmed_query("MDM2", ["HDM2"])
    for term in ("de novo", "miniprotein", "epitope", "interface",
                 "binder", "hotspot", "structure-based", "crystal structure"):
        assert term in q


def test_build_pubmed_query_custom_term_group():
    # The structure/epitope sub-query uses a different concept group.
    q = literature.build_pubmed_query(
        "EGFR", ["ERBB1"], literature._STRUCTURE_TERMS
    )
    assert "EGFR" in q
    for term in ("epitope", "binding site", "hotspot", "crystal structure",
                 "cryo-EM"):
        assert term in q


def test_build_pubmed_query_no_synonyms():
    # Should not crash and still include the target + design terms.
    q = literature.build_pubmed_query("PMVK", [])
    assert "PMVK" in q
    assert "binder" in q
    assert "de novo" in q


# --- parse_efetch_xml ---

_FIXTURE_XML = """<?xml version="1.0"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>11111111</PMID>
      <Article>
        <ArticleTitle>An EGFR binder with a defined epitope</ArticleTitle>
        <Abstract>
          <AbstractText>We characterize the binding site and hotspot residues.</AbstractText>
        </Abstract>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>22222222</PMID>
      <Article>
        <ArticleTitle>A title with no abstract</ArticleTitle>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>33333333</PMID>
      <Article>
        <ArticleTitle>Structured abstract example</ArticleTitle>
        <Abstract>
          <AbstractText Label="BACKGROUND">First part.</AbstractText>
          <AbstractText Label="RESULTS">Second part.</AbstractText>
        </Abstract>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>
"""


def test_parse_efetch_xml_basic():
    recs = literature.parse_efetch_xml(_FIXTURE_XML)
    assert len(recs) == 3
    first = recs[0]
    assert first["pmid"] == "11111111"
    assert first["title"] == "An EGFR binder with a defined epitope"
    assert "binding site" in first["abstract"]


def test_parse_efetch_xml_missing_abstract():
    recs = literature.parse_efetch_xml(_FIXTURE_XML)
    no_abs = recs[1]
    assert no_abs["pmid"] == "22222222"
    assert no_abs["abstract"] == ""


def test_parse_efetch_xml_structured_abstract_joined():
    recs = literature.parse_efetch_xml(_FIXTURE_XML)
    structured = recs[2]
    assert "First part." in structured["abstract"]
    assert "Second part." in structured["abstract"]


def test_parse_efetch_xml_empty():
    assert literature.parse_efetch_xml("<PubmedArticleSet></PubmedArticleSet>") == []


def test_parse_efetch_xml_malformed_returns_empty():
    # Defensive: garbage in -> empty list, not an exception.
    assert literature.parse_efetch_xml("not xml <<<") == []


# --- fetch_pubmed_abstracts merge + dedupe (two sub-queries) ---


def test_fetch_pubmed_issues_two_subqueries_and_dedupes(monkeypatch):
    # The design sub-query and the structure sub-query are merged, deduped by
    # PMID (design-first order preserved), then a single efetch is issued.
    queries_seen = []

    def fake_esearch(query, retmax):
        queries_seen.append(query)
        if "de novo" in query:  # design/interface sub-query
            return ["1", "2", "3"]
        return ["3", "4"]  # structure sub-query; "3" overlaps -> deduped

    captured = {}

    def fake_efetch(pmids):
        captured["pmids"] = pmids
        return [{"pmid": p, "title": f"t{p}", "abstract": ""} for p in pmids]

    monkeypatch.setattr(literature, "_esearch_pmids", fake_esearch)
    monkeypatch.setattr(literature, "_efetch_records", fake_efetch)

    recs = literature.fetch_pubmed_abstracts("EGFR", ["ERBB1"])

    assert len(queries_seen) == 2  # two distinct sub-queries issued
    # Deduped, design-first order, single efetch on the union.
    assert captured["pmids"] == ["1", "2", "3", "4"]
    assert [r["pmid"] for r in recs] == ["1", "2", "3", "4"]


def test_fetch_pubmed_caps_at_retmax(monkeypatch):
    def fake_esearch(query, retmax):
        if "de novo" in query:
            return [str(i) for i in range(50)]
        return ["x", "y"]

    monkeypatch.setattr(literature, "_esearch_pmids", fake_esearch)
    monkeypatch.setattr(
        literature, "_efetch_records",
        lambda pmids: [{"pmid": p, "title": "", "abstract": ""} for p in pmids],
    )
    recs = literature.fetch_pubmed_abstracts("EGFR", ["ERBB1"], retmax=18)
    assert len(recs) == 18


def test_fetch_pubmed_network_error_returns_empty(monkeypatch):
    def boom(query, retmax):
        raise RuntimeError("network down")

    monkeypatch.setattr(literature, "_esearch_pmids", boom)
    assert literature.fetch_pubmed_abstracts("EGFR", ["ERBB1"]) == []


# --- gather_literature caching ---


def test_gather_literature_writes_then_reads_cache(tmp_path, monkeypatch):
    cache_dir = tmp_path / "lit"
    monkeypatch.setattr(literature, "CACHE_DIR", str(cache_dir))

    calls = {"pubmed": 0, "ot": 0}

    def fake_pubmed(target_name, synonyms, retmax=15):
        calls["pubmed"] += 1
        return [{"pmid": "1", "title": "t", "abstract": "a"}]

    def fake_ot(uniprot):
        calls["ot"] += 1
        return {"approvedSymbol": "EGFR"}

    monkeypatch.setattr(literature, "fetch_pubmed_abstracts", fake_pubmed)
    monkeypatch.setattr(literature, "fetch_open_targets", fake_ot)

    out1 = literature.gather_literature("EGFR", ["ERBB1"], "P00533")
    assert out1["abstracts"] == [{"pmid": "1", "title": "t", "abstract": "a"}]
    assert out1["open_targets"] == {"approvedSymbol": "EGFR"}
    assert calls == {"pubmed": 1, "ot": 1}

    # Cache file written.
    cache_file = cache_dir / "EGFR.json"
    assert cache_file.exists()
    on_disk = json.loads(cache_file.read_text())
    assert on_disk["abstracts"][0]["pmid"] == "1"

    # Second call: cache hit, NO new fetch.
    out2 = literature.gather_literature("EGFR", ["ERBB1"], "P00533")
    assert out2 == out1
    assert calls == {"pubmed": 1, "ot": 1}
