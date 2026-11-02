"""Export genuine saved validation coordinates, retaining their source identities."""
import ast
import hashlib
import json
import os
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent
SPRINT = Path(os.environ.get("SENBA_ROOT", str(ROOT.parent / "source-original/senba-sprint")))
source = SPRINT / "artifacts/derived/1rquA01-k16-v1/k16.jsonl"
inputs = np.load(SPRINT / "inputs/1rquA01.npz", allow_pickle=False)
sequence = str(inputs["sequence"])
metadata = json.loads(str(inputs["metadata_json"]))
constants = {}
for node in ast.parse((SPRINT / "artifacts/mars-fm/mars/vendored/openfold/residue_constants.py").read_text()).body:
    if isinstance(node, ast.Assign):
        for t in node.targets:
            if isinstance(t, ast.Name) and t.id in {"restype_name_to_atom14_names", "restype_1to3"}:
                constants[t.id] = ast.literal_eval(node.value)

records = []
with source.open() as handle:
    for i, line in enumerate(handle):
        if i == 4:
            break
        r = json.loads(line)
        assert r["replica_id"] == "0"
        assert np.allclose(r["start"], inputs["starts"][i, :, 1])
        atoms, elements, residues = [], [], []
        for j, letter in enumerate(sequence):
            for slot, name in enumerate(constants["restype_name_to_atom14_names"][constants["restype_1to3"][letter]]):
                if name:
                    atoms.append(inputs["starts"][i, j, slot].tolist())
                    elements.append(name[0])
                    residues.append(j)
        records.append({
            "id": f"example-{i}", "label": "1rquA01", "sequence": sequence,
            "kind": "saved_inference", "start": r["start"], "target": r["target"],
            "source": r["source"], "candidate": r["candidate"],
            "start_atoms": {"coordinates": atoms, "elements": elements, "residues": residues},
            "transition": metadata["transitions"][i],
            "receipt": {"record_source": str(source.relative_to(SPRINT)),
                        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                        "checkpoint_sha256": "f02dcf6a97848c834e3c0be7d848c1068d1d0eb7976d8d6bcfbc98d4114e9c7c",
                        "inference_seed": r["inference_seed"], "training_seed": r["training_seed"],
                        "samples": len(r["candidate"]), "units": r["units"], "alignment": r["alignment"],
                        "temperature_kelvin": 450, "trained_lag_saved_frames": 50,
                        "interpretation": "Saved independent endpoint samples from the reused validation panel; not a physical trajectory"},
        })
out = ROOT / "static/data/examples.json"
out.write_text(json.dumps({"records": records, "attribution": "Senba / Papercrane; MarS-FM / Valence Labs (MIT); mdCATH (CC BY 4.0)"}, separators=(",", ":"), allow_nan=False))
print(f"Exported {len(records)} real transitions, {len(records[0]['candidate'])} samples each, {out.stat().st_size:,} bytes")
