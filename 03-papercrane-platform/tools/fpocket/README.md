# fpocket

Detects and scores protein binding pockets with Voronoi tessellation and alpha spheres.

- Upstream: <https://github.com/Discngine/fpocket>
- Release: <https://github.com/Discngine/fpocket/releases/tag/4.2.3>
- License: MIT
- Input: PDB/mmCIF protein structure
- Output: pocket count and top-pocket score, druggability, volume, SASA, and alpha-sphere metrics plus fpocket's analyzed mmCIF

The adapter pins the stable 4.2.3 release and uses the upstream `fpocket -f ... -w m` interface. It remains beta until the native build and descriptor output pass a live smoke test.
