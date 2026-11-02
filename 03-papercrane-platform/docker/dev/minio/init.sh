#!/bin/sh
# Paper Crane — MinIO bootstrap
#
# One-shot script that runs in the `minio/mc` sidecar container. Idempotent:
# safe to re-run on every `docker compose up`.
#
# Steps:
#   1. Wait for MinIO to become reachable
#   2. Register a `local` mc alias pointing at the MinIO server
#   3. Create the `papercrane-dev` bucket (no-op if it exists)
#   4. Attach a bucket policy granting anonymous read under the `public/*` prefix
#   5. Print a success banner
#
# Note: if this file is not executable on the host (git may keep it 644),
# that's fine — the Compose entrypoint invokes `/bin/sh /init/init.sh`
# explicitly, bypassing the exec bit. Still, `chmod +x` it if you plan to
# run it directly on the host for debugging.

set -eu

ENDPOINT="${MINIO_ENDPOINT:-http://minio:9000}"
ACCESS_KEY="${MINIO_ROOT_USER:-minioadmin}"
SECRET_KEY="${MINIO_ROOT_PASSWORD:-minioadmin}"
BUCKET="${MINIO_BUCKET:-papercrane-dev}"
ALIAS="local"

echo "[minio-init] waiting for MinIO at ${ENDPOINT} ..."
attempt=0
max_attempts=60
until mc alias set "${ALIAS}" "${ENDPOINT}" "${ACCESS_KEY}" "${SECRET_KEY}" >/dev/null 2>&1; do
  attempt=$((attempt + 1))
  if [ "${attempt}" -ge "${max_attempts}" ]; then
    echo "[minio-init] ERROR: MinIO never became reachable after ${max_attempts} attempts" >&2
    exit 1
  fi
  sleep 1
done
echo "[minio-init] connected to MinIO (alias=${ALIAS})"

# 3. Create bucket (ignore 'already own it' style errors).
if mc ls "${ALIAS}/${BUCKET}" >/dev/null 2>&1; then
  echo "[minio-init] bucket '${BUCKET}' already exists, skipping create"
else
  echo "[minio-init] creating bucket '${BUCKET}' ..."
  mc mb "${ALIAS}/${BUCKET}"
fi

# 4. Policy: anonymous read for anything under public/*
POLICY_FILE="$(mktemp)"
cat >"${POLICY_FILE}" <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "PublicReadPublicPrefix",
      "Effect": "Allow",
      "Principal": {"AWS": ["*"]},
      "Action": ["s3:GetObject"],
      "Resource": ["arn:aws:s3:::${BUCKET}/public/*"]
    },
    {
      "Sid": "PublicListPublicPrefix",
      "Effect": "Allow",
      "Principal": {"AWS": ["*"]},
      "Action": ["s3:ListBucket"],
      "Resource": ["arn:aws:s3:::${BUCKET}"],
      "Condition": {
        "StringLike": {"s3:prefix": ["public/*"]}
      }
    }
  ]
}
EOF

echo "[minio-init] applying public-read policy on '${BUCKET}/public/*' ..."
mc anonymous set-json "${POLICY_FILE}" "${ALIAS}/${BUCKET}" \
  || mc policy set-json "${POLICY_FILE}" "${ALIAS}/${BUCKET}"
rm -f "${POLICY_FILE}"

echo "[minio-init] OK — bucket=${BUCKET}  endpoint=${ENDPOINT}  public prefix=public/*"
