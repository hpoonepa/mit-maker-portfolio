#!/bin/sh

if [ "${FAKE_MODAL_CONNECTION_ERROR:-0}" = "1" ]; then
  printf '%s\n' 'Could not connect to the Modal server.' >&2
  exit 1
fi

printf '%s\n' 'Modal CLI banner (not JSON)'

if [ -n "${FAKE_MODAL_INVOCATION_LOG:-}" ]; then
  printf '%s\n' "$$" >> "${FAKE_MODAL_INVOCATION_LOG}"
fi

seeds=7
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--seeds" ] && [ "$#" -gt 1 ]; then
    seeds=$(printf '%s' "$2" | tr -d '[]' | tr ',' ' ')
    break
  fi
  shift
done

if [ "${FAKE_MODAL_SKIP_SEED:-0}" != "1" ]; then
  for seed in ${seeds}; do
    emitted_seed="${FAKE_MODAL_SEED_OVERRIDE:-${seed}}"
    printf '%s\n' "{\"type\":\"seed\",\"seed\":${emitted_seed},\"sequence\":\"M\",\"artifactKey\":\"orgs/o/jobs/j/designs/${emitted_seed}.cif\",\"metrics\":{\"score\":0.9}}"
  done
fi

if [ "${FAKE_MODAL_HANG:-0}" = "1" ]; then
  if [ "${FAKE_MODAL_IGNORE_TERM:-0}" = "1" ]; then
    trap '' TERM INT
  else
    trap 'exit 0' TERM INT
  fi
  while :; do sleep 1; done
fi

# Intentionally omit the final newline to cover trailing-buffer parsing.
printf '%s' '{"type":"done","summary":{"completed":1}}'
