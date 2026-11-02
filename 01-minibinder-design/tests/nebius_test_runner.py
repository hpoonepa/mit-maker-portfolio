# Check result CSV merging, including empty rows and headers.
from backends.nebius.runner import merge_csv

def test_merge_csv_writes_header_and_rows(tmp_path):
    header = "seed,sequence,length,cys_count,binder_plddt,target_plddt,iptm"
    rows = ["0,SEQA,85,0,0.8,0.9,0.7", "1,SEQB,85,1,0.7,0.85,0.6"]
    out = tmp_path / "results.csv"
    merge_csv(header, rows, out)
    text = out.read_text().splitlines()
    assert text[0] == header
    assert text[1] == "0,SEQA,85,0,0.8,0.9,0.7"
    assert text[2] == "1,SEQB,85,1,0.7,0.85,0.6"
    assert len(text) == 3

def test_merge_csv_skips_empty_rows(tmp_path):
    out = tmp_path / "r.csv"
    merge_csv("h", ["a,b", "", "  ", "c,d"], out)
    assert out.read_text().splitlines() == ["h", "a,b", "c,d"]
