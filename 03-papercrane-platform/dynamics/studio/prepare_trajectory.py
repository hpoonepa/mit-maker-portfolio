"""Export authentic time-ordered MD frames from one hash-verified public simulation."""
import hashlib
import json
from pathlib import Path
import h5py
import numpy as np

ROOT = Path(__file__).resolve().parent
path = ROOT / 'runtime/mdcath_dataset_1rquA01.h5'
digest = hashlib.sha256(path.read_bytes()).hexdigest()
assert digest == '8be1bd65e5d63aaf838dc7be3174a06a85bcef379c50f9d1f93e743ab85673e8'
examples_path = ROOT / 'static/data/examples.json'
data = json.loads(examples_path.read_text())

def align(reference, mobile):
    rc, mc = reference.mean(0), mobile.mean(0)
    u, _, vt = np.linalg.svd((mobile - mc).T @ (reference - rc))
    correction = np.eye(3)
    correction[-1, -1] = 1 if np.linalg.det(u @ vt) >= 0 else -1
    return (mobile - mc) @ (u @ correction @ vt) + rc

with h5py.File(path) as handle:
    group = handle['1rquA01']
    pdb = group['pdbProteinAtoms'][()]
    if isinstance(pdb, bytes):
        pdb = pdb.decode()
    atoms = [line for line in pdb.splitlines() if line.startswith(('ATOM  ', 'HETATM'))]
    indices = [i for i, line in enumerate(atoms) if line[12:16].strip() == 'CA']
    coords = group['450']['0']['coords']
    assert coords.attrs['unit'] in ('Angstrom', b'Angstrom')
    for record in data['records']:
        start = record['transition']['start_frame']
        reference = np.asarray(record['start'])
        trajectory = [align(reference, np.asarray(coords[i])[indices]) for i in range(start, start + 51)]
        assert np.allclose(trajectory[0], reference, atol=0.001)
        assert np.allclose(trajectory[-1], record['target'], atol=0.001)
        record['trajectory'] = [np.round(frame, 5).tolist() for frame in trajectory]
        record['trajectory_receipt'] = {
            'dataset': 'compsciencelab/mdCATH', 'revision': '5e3ed8aec62b689e01751db16275fdcdbc39e47f',
            'h5_sha256': digest, 'protein': '1rquA01', 'temperature_kelvin': 450, 'replica': 0,
            'first_saved_frame': start, 'last_saved_frame': start + 50,
            'alignment': 'each frame aligned to starting CA coordinates; proper Kabsch rotation',
            'units': 'angstrom', 'physical_time_unit': None,
            'interpretation': 'Chronologically ordered recorded MD frames; no synthetic intermediate frames',
        }
examples_path.write_text(json.dumps(data, separators=(',', ':'), allow_nan=False))
print(f"Exported four authentic 51-frame MD windows. Verified start and endpoint correspondence. {examples_path.stat().st_size:,} bytes")
