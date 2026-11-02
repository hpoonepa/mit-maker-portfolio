# Prepared-patch example

`patches.json` contains the first eight candidate patches from PDB **1JHL**, context `0cb68aa8668149e2`, with the original geometry, atom, and ESM feature blocks. Features were copied from the original experiment cache; no labels are needed for inference. This is a small excerpt, not the full candidate pool or a performance benchmark.

`expected.json` records per-patch scores computed directly with the original XGBoost classifier interface, along with the source context and coordinate hashes. The inference tests compare against those scores. The source coordinates come from the PDB; chain roles used by the original study come from SAbDab. See [data attribution](../DATA_LICENSES.md).

Run `prince-rank examples/patches.json --top 3 --output ranked.json`. Output patch indices refer to rows in this example, and overlap suppression may return fewer than the requested number.
