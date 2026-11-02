"""Prepare only the frozen public validation panel from pinned mdCATH HDF5s."""
import argparse
import ast
import hashlib
import json
from pathlib import Path

import h5py
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
REVISION = "5e3ed8aec62b689e01751db16275fdcdbc39e47f"
HASHES = {
    "1e7uA04": "56b58f0feac0e3265540ebf2539effd9b2ecb81859cc92589485b058a9aa80ef",
    "1rquA01": "8be1bd65e5d63aaf838dc7be3174a06a85bcef379c50f9d1f93e743ab85673e8",
    "1q16B03": "5d79972286b6c33b51b7c193f52bb60bdebd3e5f47a155108b026ab96dfe5aec",
    "1d1rA00": "9d341b34c5c3dd7e730a867e56c577a04552cd39edf0133753a7672c2937c175",
    "2k4qA00": "71850ae95839e5167c8803e1f21556463229d0d6f2a51cc6b151e698004790ab",
    "2f2cA02": "b217d9d17ecb264b845acb038be6f03760bde867d24985793a0fae5ba990cdf6",
    "5k2mA01": "3cf66928a4cd7f20636f72f6950eb810a690619eaedf58e5074c5f24603f5903",
    "2dp9A01": "60107ceb0ee1a9416e4f8f5c8854036793a5b0a2e0e9de14649a8eb9927777bd",
}


def file_sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def constant_tables():
    path = ROOT / "artifacts/mars-fm/mars/vendored/openfold/residue_constants.py"
    # Read literal mapping tables without importing the optional ML stack.
    found = {}
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in {"restype_name_to_atom14_names", "restype_1to3"}:
                    found[target.id] = ast.literal_eval(node.value)
    return found["restype_name_to_atom14_names"], {v: k for k, v in found["restype_1to3"].items()}


def fixed_starts(n_frames):
    values = [i * (n_frames - 51) // 3 for i in range(4)]
    if len(set(values)) != 4 or min(values) < 0 or max(values) + 50 >= n_frames:
        raise ValueError("replica cannot supply four distinct lag-50 pairs")
    return values


def atom_mapping(pdb_text, atom14_names, letter_by_resname):
    rows = [line for line in pdb_text.splitlines() if line.startswith(("ATOM  ", "HETATM"))]
    residues = {}
    for index, row in enumerate(rows):
        key = (row[21], row[22:26], row[26])
        name = row[17:20].strip()
        name = {"HSD": "HIS", "HSE": "HIS", "HSP": "HIS"}.get(name, name)
        if name not in letter_by_resname:
            raise ValueError(f"unsupported residue {name}")
        entry = residues.setdefault(key, {"name": name, "atoms": {}})
        if entry["name"] != name:
            raise ValueError("inconsistent residue names")
        atom = row[12:16].strip()
        if name == "ILE" and atom == "CD":
            atom = "CD1"
        if atom in atom14_names[name]:
            if atom in entry["atoms"]:
                raise ValueError("duplicate required heavy atom")
            entry["atoms"][atom] = index
    mapping = np.full((len(residues), 14), -1, dtype=np.int64)
    sequence = ""
    for i, entry in enumerate(residues.values()):
        sequence += letter_by_resname[entry["name"]]
        for slot, atom in enumerate(atom14_names[entry["name"]]):
            if not atom:
                continue
            if atom not in entry["atoms"]:
                raise ValueError(f"missing atom {atom} at residue {i+1}")
            mapping[i, slot] = entry["atoms"][atom]
    return sequence, mapping, rows


def prepare(path, protein_id, output):
    if protein_id not in HASHES:
        raise ValueError("protein is not in the frozen eight-protein validation panel")
    digest = file_sha(path)
    if digest != HASHES[protein_id]:
        raise ValueError("mdCATH file hash does not match the pinned provider identity")
    names, letters = constant_tables()
    starts, targets, transitions = [], [], []
    with h5py.File(path, "r") as handle:
        group = handle[protein_id]
        pdb_text = group["pdbProteinAtoms"][()]
        if isinstance(pdb_text, bytes):
            pdb_text = pdb_text.decode()
        sequence, mapping, rows = atom_mapping(pdb_text, names, letters)
        if len(sequence) != int(group.attrs["numResidues"]) or len(sequence) > 256:
            raise ValueError("topology residue count mismatch or outside model scope")
        if len(rows) != int(group.attrs["numProteinAtoms"]):
            raise ValueError("topology atom count mismatch")
        real = mapping >= 0
        if not np.all(real[:, 1]):
            raise ValueError("incomplete C-alpha mapping")
        for replica in range(5):
            replica_group = group["450"][str(replica)]
            coords = replica_group["coords"]
            unit = coords.attrs.get("unit", "")
            if isinstance(unit, bytes):
                unit = unit.decode()
            if unit != "Angstrom" or coords.shape[1:] != (len(rows), 3):
                raise ValueError("coordinate units or atom axes are inconsistent")
            if coords.shape[0] != int(replica_group.attrs["numFrames"]):
                raise ValueError("replica frame-count mismatch")
            for start_frame in fixed_starts(coords.shape[0]):
                xyz = np.asarray(coords[start_frame], dtype=np.float32)
                future = np.asarray(coords[start_frame + 50], dtype=np.float32)
                if not np.isfinite(xyz).all() or not np.isfinite(future).all():
                    raise ValueError("selected coordinates are not finite")
                center = xyz[mapping[real]].mean(axis=0)
                atom14 = np.zeros((*mapping.shape, 3), dtype=np.float32)
                atom14[real] = xyz[mapping[real]] - center
                target_ca = future[mapping[:, 1]] - center
                ca_bonds = np.linalg.norm(np.diff(atom14[:, 1], axis=0), axis=1)
                if np.any(ca_bonds > 6.0):
                    raise ValueError("input chain appears discontinuous; inspect periodic wrapping")
                starts.append(atom14)
                targets.append(target_ca)
                transitions.append({"replica_id": replica, "start_frame": start_frame,
                                    "target_frame": start_frame + 50, "n_frames": coords.shape[0],
                                    "start_center_shift_angstrom": center.tolist()})
    metadata = {
        "protein_id": protein_id, "hf_revision": REVISION, "h5_sha256": digest,
        "temperature_kelvin": 450, "lag_saved_frames": 50, "units": "angstrom",
        "unit_evidence": "HDF5 coords.attrs['unit'] == Angstrom",
        "physical_interval_in_raw_metadata": None,
        "converter_frame_interval_ps": 1000,
        "converter_reference": "https://github.com/compsciencelab/mdCATH/blob/71cbe9383b1911b8bc8bcce04d7c077499845f8c/user-utils/convert_mdCATH.py",
        "preprocessing": "float32; atom14 heavy-atom mapping; translate by start heavy-atom centroid",
        "atom14_source_indices": mapping.tolist(), "transitions": transitions,
        "claim_boundary": "new_evaluator_previously_used_validation_panel",
    }
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        np.savez_compressed(stream, starts=np.asarray(starts), targets_ca=np.asarray(targets),
                            sequence=np.array(sequence), metadata_json=np.array(json.dumps(metadata)))
    return {"output": str(output), "npz_sha256": file_sha(output),
            "protein_id": protein_id, "residues": len(sequence), "transitions": len(transitions)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--protein", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.input, args.protein, args.output), indent=2))


if __name__ == "__main__":
    main()
