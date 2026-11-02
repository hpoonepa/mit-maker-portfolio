# Attribution

PRINCE code is MIT-licensed; see [LICENSE](LICENSE). The analysis implementation is maintained in the companion model repository.

| Component | Role | License |
|---|---|---|
| Astro | Static site build | MIT |
| React and React DOM | Interactive workspace | MIT |
| Three.js | Structure illustration | MIT |
| TypeScript | Type checking | Apache-2.0 |
| Instrument Sans and Instrument Serif | Interface typography | SIL Open Font License 1.1 |
| Inter | Bundled typography asset | SIL Open Font License 1.1 |

Dependency versions are locked in `package-lock.json`. The original interface adopted editorial design ideas from the authors' Papercrane project. The 6F5J illustration is derived from public structural coordinates; its source and coordinate hash are recorded in `src/lib/protein.json`.

The demonstration recording documents an earlier PRINCE interface. The bundled evaluation artifacts describe the residue baseline and retain the data provenance discussed in [DATA_LICENSES.md](DATA_LICENSES.md).

## Bundled Inter font

`public/fonts/inter.woff2` is retained unchanged. The full SIL Open Font License
1.1 is included at `public/licenses/inter.txt`, copied from the official Inter
repository's [v4.1 license](https://github.com/rsms/inter/blob/v4.1/LICENSE.txt).
This pins the license text source; it does not assert a recovered version for
the existing font binary. Copyright belongs to the Inter Project Authors.
