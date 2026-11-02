#!/usr/bin/env bash
set -euo pipefail

# Chai-1 requires a user-acknowledged non-commercial EULA (plan 02 §§8, 9).
# The platform UI must render the license modal before queueing any chai1 job;
# this guard is a belt-and-suspenders sanity check at the container edge.
if [[ "${PAPERCRANE_LICENSE_ACK:-}" != "chai1" ]]; then
  echo "ERROR: Chai-1 license not acknowledged. Set PAPERCRANE_LICENSE_ACK=chai1." >&2
  echo "See /opt/papercrane/LICENSE-GATE.md for terms." >&2
  exit 3
fi

python /opt/papercrane/adapter.py \
  --request /inputs/request.json \
  --output /outputs
