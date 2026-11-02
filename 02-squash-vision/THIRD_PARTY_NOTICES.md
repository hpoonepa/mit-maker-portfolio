# Third-party notices

These credits supplement the third parties' own license files; they do not relicense upstream code, weights, fonts or recordings. The source snapshot does not include installed dependency trees or downloaded model checkpoints. Locked versions are from `uv.lock` and `package-lock.json`; the table summarizes top-level project licenses, not every license bundled inside a wheel or transitive package.

## Adapted source, checkpoints and media

- **RacketVision inference blocks:** copyright 2025 Linfeng Dong, MIT at the exact source commit `c44af2a08524d3cb54d818f19686f4cdea4d2793`. The full notice and local changes are retained in [ATTRIBUTION.txt](src/squashvision/backend/squashvision/vision/ball/ATTRIBUTION.txt). [Pinned upstream license](https://github.com/OrcustD/RacketVision/blob/c44af2a08524d3cb54d818f19686f4cdea4d2793/LICENSE).
- **YOLO11 model and Ultralytics package:** AGPL-3.0, with separate commercial licensing offered by Ultralytics. [Pinned package license](https://github.com/ultralytics/ultralytics/blob/v8.4.129/LICENSE) and [model/license documentation](https://www.ultralytics.com/license). No enterprise license is asserted.
- **RacketVision ball weights:** checkpoint-specific terms were not established from the linked repository. They remain `not-declared` in the model registry; the implementation's MIT notice is not substituted for a model license. See [checkpoint identity and research credit](CITATIONS.md).
- **Test footage:** ÉCRANOMADE's Mulhouse teaser, CC BY 3.0; full source and transformation notice in the [fixture attribution](tests/squashvision/fixtures/ATTRIBUTION.txt). Attribution applies to the derived test video and corresponding overlay figures.
- **Professional-match demonstration:** SQUASHTV/its rights holders retain copyright in the ElShorbagy–Farag broadcast. The software demonstration, paper and source license do not grant reuse rights in that footage. [Source and excerpt record](assets/PROVENANCE.md).

## Python dependencies

| Package / upstream | Locked version | Upstream license summary | Use |
| --- | --- | --- | --- |
| [alembic](https://github.com/sqlalchemy/alembic) | 1.19.1 | MIT | Schema migrations |
| [av (PyAV)](https://github.com/PyAV-Org/PyAV) | 18.1.0 | BSD-3-Clause | Video/audio decoding |
| [fastapi](https://github.com/fastapi/fastapi) | 0.141.1 | MIT | Local API |
| [httpx](https://github.com/encode/httpx) | 0.28.1 | BSD-3-Clause | HTTP client |
| [huggingface-hub](https://github.com/huggingface/huggingface_hub) | 1.28.0 | Apache-2.0 | Model downloads |
| [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) | 0.6.0 | BSD-2-Clause (wrapper) | FFmpeg executable discovery |
| [numpy](https://github.com/numpy/numpy) | 2.5.2 | BSD-3-Clause | Numerical arrays |
| [opencv-python-headless](https://github.com/opencv/opencv-python) | 5.0.0.93 | MIT (packaging); Apache-2.0 (OpenCV) | Image processing and geometry |
| [pyarrow](https://github.com/apache/arrow) | 25.0.1 | Apache-2.0 | Columnar observations |
| [platformdirs](https://github.com/tox-dev/platformdirs) | 4.11.4 | MIT | Local application directories |
| [pydantic-settings](https://github.com/pydantic/pydantic-settings) | 2.15.0 | MIT | Configuration |
| [python-multipart](https://github.com/Kludex/python-multipart) | 0.0.32 | Apache-2.0 | Multipart uploads |
| [scipy](https://github.com/scipy/scipy) | 1.18.1 | BSD-3-Clause | Scientific computation |
| [sqlalchemy](https://github.com/sqlalchemy/sqlalchemy) | 2.0.52 | MIT | Database access |
| [torch](https://github.com/pytorch/pytorch) | 2.13.0 | BSD-3-Clause; bundled components retain notices | Inference tensors and modules |
| [torchvision](https://github.com/pytorch/vision) | 0.28.0 | BSD-3-Clause | Vision model support |
| [ultralytics](https://github.com/ultralytics/ultralytics) | 8.4.129 | AGPL-3.0 | YOLO11 pose inference |
| [uvicorn](https://github.com/Kludex/uvicorn) | 0.52.4 | BSD-3-Clause | ASGI server |
| [pytest](https://github.com/pytest-dev/pytest) | 9.1.1 | MIT | Backend tests |
| [pytest-asyncio](https://github.com/pytest-dev/pytest-asyncio) | 1.4.0 | Apache-2.0 | Async test support |

[OpenCV's license page](https://opencv.org/license/) distinguishes Apache-2.0 for OpenCV 4.5+ from older BSD releases; the [Python packaging project](https://github.com/opencv/opencv-python) has its own MIT notice. [FFmpeg](https://www.ffmpeg.org/legal.html) has LGPL/GPL terms depending on build configuration and enabled components; the imageio wrapper's BSD license does not replace the bundled binary's terms. Scientific packages may include additional numerical-library notices in their wheels.

## Frontend, fonts and development tools

| Package / upstream | Locked version | Package license | Use / credit |
| --- | --- | --- | --- |
| [@fontsource/barlow-condensed](https://fontsource.org/fonts/barlow-condensed) | 5.3.0 | OFL-1.1 | Barlow Project Authors; interface font |
| [@fontsource/ibm-plex-mono](https://fontsource.org/fonts/ibm-plex-mono) | 5.3.0 | OFL-1.1 | IBM Corp.; interface font |
| [@fontsource/inter-tight](https://fontsource.org/fonts/inter-tight) | 5.3.0 | OFL-1.1 | Inter Project Authors; interface font |
| [@tanstack/react-query](https://github.com/TanStack/query) | 5.102.4 | MIT | API data/cache |
| [react](https://github.com/react/react) | 19.2.8 | MIT | Interface components |
| [react-dom](https://github.com/react/react) | 19.2.8 | MIT | DOM rendering |
| [react-router-dom](https://github.com/remix-run/react-router) | 7.18.2 | MIT | Routing |
| [@playwright/test](https://github.com/microsoft/playwright) | 1.62.1 | Apache-2.0 | Browser tests |
| [@testing-library/jest-dom](https://github.com/testing-library/jest-dom) | 6.9.1 | MIT | DOM assertions |
| [@testing-library/react](https://github.com/testing-library/react-testing-library) | 16.3.2 | MIT | Component tests |
| [@types/react](https://github.com/DefinitelyTyped/DefinitelyTyped) | 19.2.18 | MIT | React declarations |
| [@types/react-dom](https://github.com/DefinitelyTyped/DefinitelyTyped) | 19.2.5 | MIT | DOM declarations |
| [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react) | 5.2.0 | MIT | React build integration |
| [jsdom](https://github.com/jsdom/jsdom) | 26.1.0 | MIT | Test DOM |
| [openapi-typescript](https://github.com/openapi-ts/openapi-typescript) | 7.10.1 | MIT | Generated API declarations |
| [typescript](https://github.com/microsoft/TypeScript) | 5.9.3 | Apache-2.0 | Type checking |
| [vite](https://github.com/vitejs/vite) | 7.3.6 | MIT | Build tooling |
| [vitest](https://github.com/vitest-dev/vitest) | 3.2.7 | MIT | Frontend tests |

Font packages retain their SIL Open Font License 1.1 texts and copyright notices when installed. Generated production bundles also need the applicable upstream notices when distributed. [Citations](CITATIONS.md) identify the research, model revisions and media separately from these dependency credits.
