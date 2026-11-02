# DockQ

Continuous quality assessment of a docking model against an explicit native complex.

- Upstream: <https://github.com/bjornwallner/DockQ>
- Package: <https://pypi.org/project/DockQ/2.1.3/>
- License: MIT
- Input: model and native-reference PDB/mmCIF structures, with optional chain mapping
- Output: global DockQ, per-interface mean/best/worst DockQ, iRMSD, LRMSD, fnat, F1, clashes, and the model structure as mmCIF

The native reference is mandatory (`referencePdb*`, or `partnerPdb` from Papercrane's complex form); the adapter never treats the model as its own reference. The integration uses DockQ's JSON output and remains beta until representative model/native pairs pass a live artifact smoke test.
