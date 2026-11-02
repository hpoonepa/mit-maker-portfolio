#!/usr/bin/env bash
# Example: bash run.sh /workspace/egfr-job run --hours 1 --evaluation-hours 2
set -euo pipefail
root=${1:?Usage: bash run.sh NEW_WORK_ROOT [plan|run] [pilot options]}
action=${2:-plan}
if [[ "$action" != plan && "$action" != run ]]; then echo 'Action must be plan or run' >&2; exit 1; fi
if [[ $# -ge 2 ]]; then shift 2; else shift 1; fi
script_dir=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$root"
root=$(cd "$root" && pwd)
if [[ ! -d "$root/engines" ]]; then bash "$script_dir/setup.sh" "$root/engines"; fi
python_bin="$root/engines/control/bin/python"
if [[ ! -x "$python_bin" ]]; then echo 'Incomplete setup. Inspect installation logs; use a new work root.' >&2; exit 1; fi
if [[ ! -f "$root/pilot/targets.json" ]]; then
  "$python_bin" "$script_dir/prepare.py" --work "$root/pilot"
fi
"$python_bin" "$script_dir/pilot.py" "$action" --work "$root/pilot" --deps "$root/engines" "$@"
