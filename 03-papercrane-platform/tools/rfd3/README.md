# RFdiffusion3

Papercrane beta adapter for RosettaCommons Foundry RFdiffusion3 0.1.9. It designs an all-atom binder around a target structure and optional hotspot residues, uploads the resulting mmCIF through the signed Papercrane artifact URL, and emits one design event per seed.

The default contig generates a 60–120 residue binder followed by the selected target chain. Advanced callers can pass Foundry's `contig` expression directly. Model code and weights are BSD-3-Clause; the Modal image downloads the official checkpoint into a persistent volume.

This remains beta until the remote H100 image and checkpoint have completed a live artifact smoke test.
