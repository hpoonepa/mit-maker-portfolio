"""Boundary regressions: source grounding, review-gated ranking and local API safety."""
from types import SimpleNamespace
import pytest
from hotspot_preflight.evidence.extract import extract_documents, rank_with_evidence
from hotspot_preflight.evidence.table import row_from_mapping
from hotspot_preflight.residue import ResidueKey
from hotspot_preflight.server import analyze


def test_extractor_preserves_source_span_and_never_reviews():
    text = "  Synthetic fixture: mutation of A101 had no effect. No residue claim here."
    result = extract_documents([{"source":"PMID:123", "text":text}], [ResidueKey("A",101)])
    row = result['drafts'][0]
    assert text[row['span_start']:row['span_end']] == row['quote']
    assert row['claim'] == row['quote']
    assert row['reviewed'] is False
    assert row['direction'] == 'REFUTES'
    assert row['residues'] == ['A101']


def test_extraction_requires_chain_mapping_for_multichain_scope():
    with pytest.raises(ValueError, match='mapping'):
        extract_documents([{'source':'PMID:123','text':'A101 mutation'}],
                          [ResidueKey('A',101),ResidueKey('B',101)])


def test_only_reviewed_experiments_change_site_order():
    a,b = ResidueKey('A',101),ResidueKey('A',102)
    first = SimpleNamespace(patch=SimpleNamespace(residues=(a,)),score=.9)
    second = SimpleNamespace(patch=SimpleNamespace(residues=(b,)),score=.2)
    sites = SimpleNamespace(ranked=[first,second])
    raw = {'residues':['A102'],'claim':'synthetic experiment', 'source':'PMID:123',
           'evidence_class':'MUTAGENESIS','direction':'SUPPORTS','reviewed':False}
    with pytest.raises(ValueError,match='reviewed experimental'):
        rank_with_evidence(sites,[row_from_mapping(raw)],'evidence')
    assert sites.ranked == [first,second]
    raw.update(reviewed=True,reviewer='synthetic-test-curator')
    annotations = rank_with_evidence(sites,[row_from_mapping(raw)],'evidence')
    assert sites.ranked == [second,first]
    assert annotations[('A102',)]['structural_rank'] == 2
    assert annotations[('A102',)]['evidence']['sources'] == ['PMID:123']


@pytest.mark.parametrize('payload',[
    {'pdb_id':'../../etc/passwd'},
    {'pdb_id':'https://127.0.0.1/private'},
    {'structure_text':'x','filename':'../upload.cif'},
    {'pdb_id':'1tim','top':True},
    {'pdb_id':'1tim','top':11},
    {'pdb_id':'1tim','structure_text':'both'},
    {'file_path':'/etc/passwd'},
])
def test_api_rejects_paths_urls_and_unbounded_requests(payload):
    with pytest.raises(ValueError):
        analyze(payload)


def test_benchmark_residue_universe_excludes_symmetry_copies(cif_with_unobs_category, monkeypatch):
    import benchmark.geometric_predictor as module
    from benchmark.arms import BenchmarkInstance
    from hotspot_preflight.structure import load_target
    target = load_target(cif_with_unobs_category)
    copy = target.st[0][0].clone()
    copy.name = "A2"
    for residue in copy:
        for atom in residue:
            atom.pos.x += 40
    target.st[0].add_chain(copy)
    monkeypatch.setattr(module, "load_antigen", lambda *args, **kwargs: (target, True))
    instance = BenchmarkInstance(pdb_id="synthetic", antibody_chains=("H",),
        antigen_chains=("A",), epitope_residues=frozenset({"A101"}), cluster_id="test", split="test")
    prediction = module.GeometricArm(cif_with_unobs_category.parent)(instance)
    assert set(prediction.residue_scores) == {"A101", "A102", "A103", "A106"}
