# Build and publish

## Static site

Run `npm ci`, `npm run verify`, then serve the generated `dist/` directory. Astro uses static output and trailing-slash routes. The current source assumes deployment at the domain root; deploying below a path prefix requires updating the absolute navigation, resource, and asset URLs and rerunning link checks.

The informational pages can be hosted independently of Python. Live analysis needs a locally running worker configured in the workspace. Browser policies for HTTPS pages accessing local HTTP services can vary; the fully supported workflow is to serve both the frontend and worker locally.

The GitLab pipeline saves the compiled site and evaluation assets as `prince-webapp-dist.tar.gz`. The historical recording is omitted from this build artifact to keep the upload small; its original file remains versioned in `public/media/`. Download the artifact from the `verify` job, place it at the root of this repository, and run:

```sh
tar -xzf prince-webapp-dist.tar.gz
mkdir -p dist/media
cp public/media/prince-live-demo.webm dist/media/
```

The resulting `dist/` contains the full site, including its historical demonstration recording. Building locally with `npm run build` already includes every file and does not need these artifact-restoration steps.

The pipeline does not deploy a public analysis service. A shared service would require a separate application boundary, job management, resource limits, and an explicit data-retention policy; the supplied worker is designed for loopback use.

## iGEM repository submission

The current [iGEM software award criteria](https://competition.igem.org/judging/special-prizes) require source code in the team's dedicated iGEM GitLab repository. Provision the repositories through the team dashboard and use the assigned URLs. Keep the default branch `main`, include the source and license, and link the software explanation from the team wiki.

The assigned Lambert-GA repositories are [prince-webapp](https://gitlab.igem.org/2026/software/lambert-ga/prince-webapp) and [prince-model](https://gitlab.igem.org/2026/software/lambert-ga/prince-model). The web app contains the frontend source; the model repository contains the analysis service, inference code, and frozen evaluation artifacts. Clone them beside one another for local development.

Citation metadata and companion-repository links use those URLs. Archive a release with the model artifacts and exact commit identifiers if a citable DOI is wanted. Website/service deployment and archival DOI registration are separate release steps.

Wiki asset hosting rules and standalone software hosting rules are different. Review the current [iGEM deliverables guidance](https://competition.igem.org/deliverables/) before moving the app into a wiki.
