"""Local-only Senba portfolio demo. Real checkpoint inference; no cloud services."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
import threading
import time
import uuid
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent
SPRINT = Path(os.environ.get("SENBA_ROOT", str(ROOT.parent / "source-original/senba-sprint")))
CHECKPOINT = SPRINT / "artifacts/hf-release/senba.ckpt"
DIGEST = "f02dcf6a97848c834e3c0be7d848c1068d1d0eb7976d8d6bcfbc98d4114e9c7c"
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "runtime/matplotlib"))
sys.path[:0] = [str(SPRINT), str(SPRINT / "artifacts/mars-fm")]
STATE = {"status": "loading", "message": "Verifying checkpoint and loading Senba on CPU"}
JOBS = {}
STRUCTURES = {}
LOCK = threading.Lock()
MODEL = None


def digest_file(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_model():
    global MODEL, torch, np, example, align
    try:
        import numpy as np
        import torch
        from senba_sprint.inference import kabsch_align
        align = kabsch_align
        if digest_file(CHECKPOINT) != DIGEST:
            raise ValueError("Checkpoint SHA-256 does not match the released Senba weights")
        spec = importlib.util.spec_from_file_location("senba_example", SPRINT / "artifacts/hf-release/inference_example.py")
        example = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(example)
        from mars.model.module import MarSModule
        torch.set_num_threads(min(4, os.cpu_count() or 1))
        torch.serialization.add_safe_globals([argparse.Namespace])
        checkpoint = torch.load(CHECKPOINT, map_location="cpu", weights_only=True)
        model = MarSModule(args=checkpoint["hyper_parameters"]["args"])
        model.on_load_checkpoint(checkpoint)
        model.load_state_dict(checkpoint["state_dict"], strict=True)
        MODEL = model.eval().cpu()
        data = np.load(SPRINT / "inputs/1rquA01.npz", allow_pickle=False)
        metadata = json.loads(str(data["metadata_json"]))
        for index in range(4):
            STRUCTURES[f"example-{index}"] = {
                "atom14": data["starts"][index], "sequence": str(data["sequence"]),
                "label": "1rquA01", "transition": metadata["transitions"][index],
            }
        STATE.update(status="ready", message="Senba ready · local CPU", device="cpu", checkpoint_sha256=DIGEST,
                     parameters=sum(p.numel() for p in MODEL.parameters()))
    except Exception as exc:
        STATE.update(status="error", message=str(exc))


def flatten_atoms(atom14, sequence):
    atoms, elements, residues = [], [], []
    rc = example.rc
    for i, letter in enumerate(sequence):
        for slot, name in enumerate(rc.restype_name_to_atom14_names[rc.restype_1to3[letter]]):
            if name:
                atoms.append(atom14[i, slot].tolist())
                elements.append(name[0])
                residues.append(i)
    return {"coordinates": atoms, "elements": elements, "residues": residues}


def align_all(reference, atom14):
    mobile = atom14[:, 1]
    a, b = mobile.mean(0), reference.mean(0)
    u, _, vt = np.linalg.svd((mobile - a).T @ (reference - b))
    correction = np.eye(3)
    correction[-1, -1] = 1 if np.linalg.det(u @ vt) >= 0 else -1
    return (atom14 - a) @ (u @ correction @ vt) + b


def run_job(job_id, structure, samples, seed):
    job = JOBS[job_id]
    began = time.perf_counter()
    original_forward = None
    try:
        job.update(status="running", stage="Preparing input coordinates", evaluations=0)
        atom14, sequence = structure["atom14"], structure["sequence"]
        batch = example.build_batch(atom14, sequence, samples, torch.device("cpu"))
        original_forward = MODEL.model.forward
        def count(*args, **kwargs):
            job["evaluations"] += 1
            return original_forward(*args, **kwargs)
        # Upstream inference calls .forward directly, bypassing PyTorch hooks.
        MODEL.model.forward = count
        job["stage"] = "Sampling the learned flow field"
        torch.manual_seed(seed)
        infer_start = time.perf_counter()
        with torch.inference_mode():
            generated, _ = MODEL.inference(batch, num_steps=10)
        infer_seconds = time.perf_counter() - infer_start
        generated = generated[:, 0].float().cpu().numpy()
        if generated.shape != (samples, len(sequence), 14, 3) or not np.isfinite(generated).all():
            raise ValueError("Model returned invalid coordinates")
        job["stage"] = "Aligning structures and measuring displacement"
        generated = [align_all(atom14[:, 1], g) for g in generated]
        result = {
            "kind": "fresh_inference", "label": structure["label"], "sequence": sequence,
            "start": atom14[:, 1].tolist(), "candidate": [g[:, 1].tolist() for g in generated],
            "start_atoms": flatten_atoms(atom14, sequence),
            "candidate_atoms": [flatten_atoms(g, sequence) for g in generated],
            "receipt": {"checkpoint_sha256": DIGEST, "seed": seed, "samples": samples,
                        "ode_output_points": 10, "network_evaluations": job["evaluations"],
                        "inference_seconds": round(infer_seconds, 3), "device": "cpu",
                        "torch_version": torch.__version__, "temperature_kelvin": 450,
                        "trained_lag_saved_frames": 50, "units": "angstrom",
                        "alignment": "each sample aligned to input CA; proper Kabsch rotation",
                        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "input_sha256": hashlib.sha256(atom14.tobytes() + sequence.encode()).hexdigest(),
                        "interpretation": "Independent endpoint samples; morphs interpolate displayed coordinates"},
        }
        (ROOT / "runtime/results").mkdir(parents=True, exist_ok=True)
        (ROOT / f"runtime/results/{job_id}.json").write_text(json.dumps(result, allow_nan=False))
        job.update(status="complete", stage="Fresh prediction ready", result=result,
                   elapsed_seconds=round(time.perf_counter() - began, 3))
    except Exception as exc:
        job.update(status="error", stage=str(exc))
    finally:
        if original_forward is not None:
            MODEL.model.forward = original_forward
        LOCK.release()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT / "static"), **kwargs)

    def json_response(self, value, code=200):
        payload = json.dumps(value, allow_nan=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            return self.json_response(STATE)
        if path.startswith("/api/jobs/"):
            job = JOBS.get(path.rsplit("/", 1)[-1])
            return self.json_response(job or {"error": "Unknown job"}, 200 if job else 404)
        return super().do_GET()

    def do_POST(self):
        try:
            origin = self.headers.get("Origin")
            expected = f"http://{self.headers.get('Host')}"
            if origin and origin != expected:
                return self.json_response({"error": "Cross-origin requests are disabled"}, 403)
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 2_000_000:
                return self.json_response({"error": "Request must be under 2 MB"}, 413)
            payload = json.loads(self.rfile.read(size))
            if not isinstance(payload, dict):
                raise ValueError("Expected a JSON object")
            if STATE["status"] != "ready":
                return self.json_response({"error": STATE["message"]}, 503)
            if self.path == "/api/structure":
                chain = payload.get("chain", "A")
                if not isinstance(chain, str) or len(chain) != 1 or not chain.isalnum():
                    raise ValueError("Choose a single-letter or single-digit chain")
                pdb_id = payload.get("pdb_id", "").upper().strip()
                if pdb_id:
                    if not re.fullmatch(r"[0-9][A-Z0-9]{3}", pdb_id):
                        raise ValueError("Enter a four-character PDB ID, such as 1UBQ")
                    with urlopen(f"https://files.rcsb.org/download/{pdb_id}.pdb", timeout=20) as response:
                        pdb = response.read(2_000_001).decode()
                    if len(pdb) > 2_000_000:
                        raise ValueError("PDB file exceeds the 2 MB limit")
                else:
                    pdb = payload.get("pdb_text", "")
                    if not isinstance(pdb, str):
                        raise ValueError("PDB input must be text")
                # Use only the first MODEL in NMR ensembles.
                pdb = pdb.split("ENDMDL")[0]
                atom14, sequence = example.pdb_to_atom14(pdb, chain)
                if not 3 <= len(sequence) <= 256:
                    raise ValueError("Choose a single protein domain with 3–256 residues")
                # Center only real atoms; retain zero-valued padding slots.
                mask = np.any(atom14 != 0, axis=-1)
                atom14[mask] -= atom14[:, 1].mean(0)
                key = uuid.uuid4().hex
                if len(STRUCTURES) >= 32:
                    raise ValueError("Structure limit reached; restart the local server")
                label = f"{pdb_id or 'Uploaded PDB'} · chain {chain}"
                STRUCTURES[key] = {"atom14": atom14, "sequence": sequence, "label": label}
                return self.json_response({"id": key, "label": label, "sequence": sequence,
                                           "start": atom14[:, 1].tolist(), "start_atoms": flatten_atoms(atom14, sequence)})
            if self.path == "/api/run":
                structure = STRUCTURES.get(payload.get("structure_id", "example-0"))
                samples, seed = payload.get("samples", 2), payload.get("seed", 20261024)
                if structure is None:
                    raise ValueError("Load a structure first")
                if type(samples) is not int or samples not in (1, 2, 4):
                    raise ValueError("Choose 1, 2, or 4 endpoint samples")
                if type(seed) is not int or not 0 <= seed <= 2**31 - 1:
                    raise ValueError("Seed must be an integer from 0 to 2147483647")
                if len(JOBS) >= 100:
                    raise ValueError("Session job limit reached; restart the local server")
                if not LOCK.acquire(blocking=False):
                    return self.json_response({"error": "A prediction is already running"}, 409)
                key = uuid.uuid4().hex
                JOBS[key] = {"id": key, "status": "queued", "stage": "Starting Senba"}
                threading.Thread(target=run_job, args=(key, structure, samples, seed), daemon=True).start()
                return self.json_response({"id": key}, 202)
            self.json_response({"error": "Unknown endpoint"}, 404)
        except (ValueError, KeyError, TypeError) as exc:
            self.json_response({"error": str(exc)}, 400)
        except Exception as exc:
            self.json_response({"error": str(exc)}, 500)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8941)
    args = parser.parse_args()
    threading.Thread(target=load_model, daemon=True).start()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Senba Studio: http://127.0.0.1:{args.port}", flush=True)
    server.serve_forever()
