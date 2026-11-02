#!/usr/bin/env bash
# BindCraft on 5G51 via the Colab CLI (G4 / RTX PRO 6000 Blackwell, 96GB). Run ON the remote VM.
#
#   LOCAL:   pip install google-colab-cli
#            colab new -s bc5g51 --gpu G4        # or --gpu A100 if G4 is unavailable
#            colab upload -s bc5g51 bindcraft_5g51_colabcli.sh
#            colab ssh -s bc5g51
#   REMOTE:  bash bindcraft_5g51_colabcli.sh
#
# Detach-safe: runs under nohup+setsid, so closing the SSH session does not kill it.
# Resume-safe: BindCraft counts finished PDBs on disk, so re-running continues the campaign.
set -uo pipefail

# ----------------------------- CONFIG -----------------------------
RUN_NAME="5G51_freebind"
WORK=/content/bindcraft
OUT=/content/drive/MyDrive/BindCraft/${RUN_NAME}          # persistent target
LENGTHS_MIN=60
LENGTHS_MAX=150          # G4 has 96GB VRAM. BindCraft: 32GB~550 res, 80GB~950 res, so 96GB is
                         # ~1100+ - VRAM is a NON-ISSUE here. 150 is a design choice (typical
                         # minibinder range), not a memory limit. Raise it if you want longer binders.
N_FINAL=200              # G4 is fast and unconstrained on memory; aim high
HOTSPOTS=""              # "" = FREE BINDING, AF2 picks the site
ADVANCED=default_4stage_multimer.json
FILTERS=default_filters.json
# ------------------------------------------------------------------

echo "=== GPU ==="; nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
VRAM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -1)
echo "VRAM ${VRAM} MiB | target 157 aa + binder ${LENGTHS_MIN}-${LENGTHS_MAX} aa"
if [ "${VRAM}" -lt 20000 ]; then
  echo "!! Small GPU detected. BindCraft's guidance is ~350 total residues on 16GB."
  echo "!! Lower LENGTHS_MAX to ~130 before running."
fi

# --- persistence: prefer Drive, fall back to local + warn -----------
if [ ! -d /content/drive/MyDrive ]; then
  echo "Drive not mounted; attempting mount..."
  python3 -c "from google.colab import drive; drive.mount('/content/drive')" 2>/dev/null || true
fi
if [ ! -d /content/drive/MyDrive ]; then
  OUT=/content/bindcraft_out/${RUN_NAME}
  echo "!! WARNING: Drive unavailable. Writing to ${OUT} on EPHEMERAL VM DISK."
  echo "!! Results are lost if the VM is torn down. Pull them periodically with:"
  echo "!!   colab download -s <session> ${OUT}"
fi
mkdir -p "${OUT}" "${OUT}_settings" "${OUT}_logs"

# --- install (idempotent) -------------------------------------------
if [ ! -f "${WORK}/params/done.txt" ]; then
  echo "=== installing BindCraft ==="
  git clone -q https://github.com/martinpacesa/BindCraft "${WORK}"
  chmod +x "${WORK}/functions/dssp" "${WORK}/functions/DAlphaBall.gcc"
  mkdir -p "${WORK}/params"
  apt-get install -y aria2 -qq
  aria2c -q -x 16 -d /content \
    https://storage.googleapis.com/alphafold/alphafold_params_2022-12-06.tar
  tar -xf /content/alphafold_params_2022-12-06.tar -C "${WORK}/params"
  rm -f /content/alphafold_params_2022-12-06.tar
  touch "${WORK}/params/done.txt"
  pip install -q git+https://github.com/sokrypton/ColabDesign.git
  pip install -q pyrosetta --find-links \
    https://west.rosettacommons.org/pyrosetta/quarterly/release.cxx11thread.serialization
fi

# --- preflight: fail now, not 3 hours in ----------------------------
python3 - <<'PY' || exit 1
import jax, sys
d = jax.devices(); print("jax devices:", d)
if not any(x.platform == "gpu" for x in d):
    sys.exit("FATAL: no GPU visible to JAX")
import pyrosetta, colabdesign
print("pyrosetta OK / colabdesign OK")
PY

# --- target: 5G51 chain A 260-416 -----------------------------------
TARGET="${OUT}_settings/5G51_chainA_260_416.pdb"
if [ ! -f "${TARGET}" ]; then
python3 - "$TARGET" <<'PY'
import sys, urllib.request
dst = sys.argv[1]
urllib.request.urlretrieve("https://files.rcsb.org/download/5G51.pdb", "/tmp/5g51.pdb")
out, seen = [], set()
for l in open("/tmp/5g51.pdb"):
    if not l.startswith("ATOM") or l[21] != "A":      continue
    try: rn = int(l[22:26])
    except ValueError:                                continue
    if not (260 <= rn <= 416):                        continue
    # 5G51 is 1.45 A: 21 residues have NO blank-altloc copy. Keeping blank-only would
    # silently delete 263 270 271 278 291-294 303 313 318 328 350 352 353 363 375 392
    # 400 405 411 - straight through the epitope of interest. Keep (" ","A").
    if l[16] not in (" ", "A"):                       continue
    k = (rn, l[12:16].strip())
    if k in seen:                                     continue
    seen.add(k); out.append(l[:16] + " " + l[17:])
out.append("TER\nEND\n")
open(dst, "w").writelines(out)
ca = sum(1 for l in out if l.startswith("ATOM") and l[12:16] == " CA ")
assert ca == 157, f"expected 157 CA, got {ca} - altloc filter is wrong"
print(f"target written: {ca} residues")
PY
fi

# --- settings -------------------------------------------------------
SETTINGS="${OUT}_settings/target.json"
cat > "${SETTINGS}" <<JSON
{
    "design_path": "${OUT}/",
    "binder_name": "${RUN_NAME}",
    "starting_pdb": "${TARGET}",
    "chains": "A",
    "target_hotspot_residues": "${HOTSPOTS}",
    "lengths": [${LENGTHS_MIN}, ${LENGTHS_MAX}],
    "number_of_final_designs": ${N_FINAL}
}
JSON
cat "${SETTINGS}"

# --- supervised, detached run ---------------------------------------
LOG="${OUT}_logs/run_$(date +%Y%m%d_%H%M%S).log"
cat > /content/_bc_loop.sh <<LOOP
#!/usr/bin/env bash
cd ${WORK}
for i in \$(seq 1 200); do
  n=\$(ls ${OUT}/Accepted/*.pdb 2>/dev/null | wc -l)
  echo "===== attempt \$i | \$n accepted ====="
  if [ "\$n" -ge ${N_FINAL} ]; then echo "TARGET REACHED"; break; fi
  python3 -u ./bindcraft.py --settings "${SETTINGS}" \
      --filters "./settings_filters/${FILTERS}" \
      --advanced "./settings_advanced/${ADVANCED}"
  echo "exit \$? - restarting in 20s"; sleep 20
done
echo "LOOP FINISHED"
LOOP
chmod +x /content/_bc_loop.sh

setsid nohup /content/_bc_loop.sh > "${LOG}" 2>&1 < /dev/null &
PID=$!
echo
echo "STARTED pid ${PID}"
echo "log: ${LOG}"
echo "out: ${OUT}"
echo
echo "Safe to close this SSH session - the job is detached."
echo "  progress : ls ${OUT}/Accepted/*.pdb | wc -l"
echo "  tail log : tail -f ${LOG}"
echo "  stop     : pkill -f bindcraft.py"
