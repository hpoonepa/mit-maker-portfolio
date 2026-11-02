# PRINCE Web App

**Inspect a protein surface before choosing where to design a binder.**

PRINCE turns a structure into a short list of surface patches and checks whether the residues you intend to target are present, accessible, and numbered correctly. This repository contains the browser workspace, method pages, and interactive evaluation views built by Lambert iGEM 2026.

The interface is built with **Astro, React, TypeScript, and Three.js**. Analysis runs in the companion **[prince-model](https://gitlab.igem.org/2026/software/lambert-ga/prince-model)** Python repository. A local installation needs no account, API key, GPU, or database.

[Quick start](#quick-start) · [First analysis](#try-a-first-analysis) · [Architecture](docs/architecture.md) · [API contract](docs/api.md) · [Deployment](docs/deployment.md)

## What you can do

- Retrieve a public PDB entry or upload a PDB/mmCIF structure.
- Choose a chain and biological assembly, then rank candidate surface patches.
- Check a specific hotspot list independently of the proposed sites.
- Inspect the residues and structural findings behind each result.
- Attach source text, review extracted evidence, and supply an attributed evidence table.
- Download results for review and compare the frozen evaluation with its controls.

A high structural score is a reason to inspect a site, not a measured probability of binding. The workspace does not generate binder sequences or predict affinity.

## Quick start

Use Node.js **22.12 or later** and Python **3.10 or later**. Node 22 LTS and Python 3.11 are the CI targets. FreeSASA includes native code; Linux may need a C compiler and Python development headers, and macOS may need the Xcode Command Line Tools.

Clone both repositories into the same parent directory:

```sh
git clone https://gitlab.igem.org/2026/software/lambert-ga/prince-webapp.git
git clone https://gitlab.igem.org/2026/software/lambert-ga/prince-model.git
cd prince-webapp
```

The resulting layout is:

```text
project/
├── prince-webapp/
└── prince-model/
```

From `prince-webapp`:

```sh
npm ci
python3 -m venv .venv
source .venv/bin/activate
python -m pip install '../prince-model[sbol]'
```

Start the analysis service in the first terminal:

```sh
source .venv/bin/activate
preflight serve --port 18766 \
  --allow-origin http://127.0.0.1:4330 \
  --allow-origin http://localhost:4330
```

Start the website in a second terminal:

```sh
npm run dev
```

Open **http://127.0.0.1:4330/workspace/**. The homepage is at **http://127.0.0.1:4330/**.

The model repository can be elsewhere: replace `../prince-model` in the installation command with its path. On Windows, use `.venv\Scripts\Activate.ps1`; WSL is useful if native Python dependencies do not build.

### Read the site without running analysis

`npm ci && npm run dev` is enough to browse the method, validation, resources, and guide pages. The workspace shows a disconnected state until the local worker is running. It does not substitute demonstration results for a failed request.

## Try a first analysis

1. Open the workspace. The example is PDB **6F5J**, chain **C**, assembly **1**.
2. Keep the antibody-epitope profile and request three sites.
3. Leave **C405,C408** in the selected-hotspot field and run preflight.
4. Inspect the selected-hotspot result: these residues are declared in the sequence but absent from the deposited coordinates, so this check returns **STOP**.
5. Inspect the proposed patches separately. A proposed site does not cancel the finding for your original hotspot list.
6. Export the result and retain the input structure and settings with it.

The first PDB lookup needs internet access to PDBe. Uploaded coordinates are processed by your local worker. Prefer mmCIF when you need assembly, numbering, or unresolved-residue metadata; a plain PDB file may not contain enough information for every check.

## Read the results correctly

| Result | Meaning |
|---|---|
| Structural score | A relative ranking within the analyzed target; not a calibrated success probability |
| `GO` | The implemented checks found no blocking issue |
| `GO_WITH_WARNINGS` | Review the reported qualifications before using the site |
| `STOP` | At least one check found a blocking structural issue |
| Evidence draft | An extracted passage awaiting source review and attribution |

The current worker uses the **four-feature residue model** and connected surface patches. The larger XGBoost site ranker is distributed separately in `prince-model`; its benchmark results must not be presented as the accuracy of this live workspace. See [model scope](docs/model-scope.md).

## Pages

| Route | Contents |
|---|---|
| `/` | Project introduction and an interactive structure scene |
| `/workspace/` | Structure input, analysis, evidence review, and exports |
| `/method/` | Features, ranking, checks, and limitations |
| `/validation/` | Frozen retrospective evaluation and paired comparisons |
| `/resources/` | Searchable evaluation artifacts, manifest, license, and demonstration recording |
| `/guide/` | Installation, first-run walkthrough, and troubleshooting |

The homepage scene is a recorded 6F5J structure illustration. The downloadable recording shows an earlier interface and is labeled accordingly.

## Development

```sh
npm run check       # Astro and TypeScript diagnostics
npm run build       # Static production output in dist/
npm run preview     # Serve that production build on port 4330
npm run verify      # Check, build, then verify internal links and downloads
npm run integration # With both services running: real API and structure checks
```

The GitLab pipeline runs `npm run verify` on Node 22 and saves `prince-webapp-dist.tar.gz`. The artifact contains the compiled site and evaluation assets. To keep the upload small, the historical recording is restored from the versioned source when using that artifact; see [deployment](docs/deployment.md). A local `npm run build` includes every file automatically. Python behavior is tested in the companion repository.

```text
src/
  pages/             Astro routes
  components/        React workspace, benchmark explorer, resource library
  home/              Three.js homepage scene
  layouts/           Shared navigation and page metadata
  styles/            Shared and workspace styles
  lib/protein.json   Recorded structure illustration
public/
  prince/            Frozen evaluation downloads
  media/             Historical demonstration recording
scripts/
  check-links.mjs    Production link and asset verification
```

## Data and privacy

The browser calls the configured worker at `http://127.0.0.1:18766` by default. Connection settings let you change that address. The worker accepts exact allowed browser origins, limits requests to 8 MiB, and binds to loopback. PDB IDs are fetched from a fixed public PDBe endpoint; uploaded structures are written to temporary local files for analysis. The service does not accept arbitrary download URLs.

The browser offers explicit exports. Save those files wherever your project stores its analysis records. The local HTTP service is intended for a single researcher; deployment details are in [docs/deployment.md](docs/deployment.md).

## Troubleshooting

| Symptom | What to check |
|---|---|
| Workspace says offline | Confirm `preflight serve` is running; open `http://127.0.0.1:18766/api/health` |
| Browser rejects the request | The page origin must exactly match `--allow-origin`, including hostname and port |
| PDB retrieval fails | Check the identifier and connectivity, or upload the coordinate file |
| Structure rejected | Use a single model, a valid `.cif`, `.mmcif`, or `.pdb` file, and stay within the service limits |
| Missing chain or ambiguous assembly | Use author chain identifiers and inspect the assembly choices in the structure |
| FreeSASA installation fails | Install native build tools, use a supported Python version, and check the package's build output |
| Native Node package is missing | Use one Node architecture consistently, then rerun `npm ci` |
| Informational pages work but analysis does not | Static hosting serves the site; it does not start the Python worker |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Changes to labels, scoring, and scientific claims need the same care as changes to code. Include the input and expected behavior in bug reports; do not post confidential structures in public issues.

## License and citation

PRINCE code is licensed under [MIT](LICENSE). [NOTICE.md](NOTICE.md) records frontend dependencies and asset attribution. Evaluation and structural data retain the terms described in [DATA_LICENSES.md](DATA_LICENSES.md).

Please cite **Lambert iGEM 2026, PRINCE Web App**, version 1.0.0, together with the release or commit you used. Machine-readable metadata is in [CITATION.cff](CITATION.cff). This source release includes local setup instructions and citation metadata; a hosted service and archival DOI remain pending.
