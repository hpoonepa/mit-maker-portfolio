# ThermoMPNN

Papercrane beta adapter for Kuhlman Lab ThermoMPNN, pinned to upstream commit `2b04fd370e399911b1fa5848112cc9013f084110`. It runs the official site-saturation inference script, ranks predicted point mutations by ΔΔG, and returns one stabilizing proposal per requested seed.

The returned mmCIF is the input fixed backbone; coordinates are not relaxed after mutation. The emitted sequence contains the proposed substitution, and metrics include predicted `ddg`, residue position, and rank. Callers can request an explicit mutation or adjust the ΔΔG threshold.

ThermoMPNN is MIT-licensed. This integration remains beta until its pinned CUDA image is live-smoke-tested.
