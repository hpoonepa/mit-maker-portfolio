# Collaborators, sources and citations

## Collaborators

For Paper Crane, my co-founder Vedant Kalipatnapu developed the website's front end, while I built and integrated the platform's computational tools. We developed the protein-dynamics model together. Michael Hecht (Princeton), Aashish Manglik (UCSF), and Tudor Ștefan Coțet (Adaptyv Bio) provided research feedback that helped refine our approach but did not contribute code or implementation.

For MiniBinder, I worked with my Lambert iGEM team. Vedant and I contributed designs to the second testing round, and Adaptyv Bio performed the binding measurements. The [MiniBinder project notes](../01-minibinder-design/README.md) describe our contributions and results.

I developed SquashVision independently, using [RacketVision](https://github.com/OrcustD/RacketVision) as a starting point for the ball-tracking architecture, then building the remaining features and functionality myself. None of my collaborators will be submitting a Maker Portfolio.

## Sources and citations

My protein-design workflows use existing tools including [BoltzGen](https://github.com/HannesStark/boltzgen), [RFdiffusion](https://github.com/RosettaCommons/RFdiffusion), [Mosaic](https://github.com/escalante-bio/mosaic), and [BindCraft](https://github.com/martinpacesa/BindCraft) for generating and evaluating candidates. Paper Crane builds on open-source protein-modeling tools, while SquashVision was inspired by an existing GitHub repository that provided a starting point for its development. I cite the relevant tools, models, and repositories in my project documentation.

## Coding and research assistants

I also use [Claude](https://claude.com/product/overview) and [OpenAI Codex](https://openai.com/codex/) as coding and research assistants, particularly recently for brainstorming approaches, synthesizing literature, troubleshooting, and writing code. I review and test AI-generated code, make changes based on my own understanding and technical judgment, and verify scientific claims against original research. I treat these tools as collaborators in exploration, not substitutes for understanding my work.

## Detailed project credits

| Project | Detailed credits |
| --- | --- |
| MiniBinder and PRINCE | [Tools, papers, structural data and dependencies](../01-minibinder-design/CITATIONS.md) |
| Paper Crane platform | [All 52 tool integrations and direct dependencies](../03-papercrane-platform/THIRD_PARTY/CITATIONS.md) |
| Paper Crane research data | [File-by-file data sources](../03-papercrane-platform/THIRD_PARTY/DATA-PROVENANCE.md) |
| SENBA, Studio and later dynamics work | [MarS-FM, mdCATH, viewer and research sources](../03-papercrane-platform/dynamics/CITATIONS.md) |
| SquashVision | [Tracking models, libraries and match footage](../02-squash-vision/CITATIONS.md) |

The root MIT license applies to my original contributions. Collaborators' work, scientific tools, model weights, datasets, fonts and footage keep their own licenses and notices, recorded in the project credits above.

The dependencies declared by package manifests are listed in [DEPENDENCIES.json](DEPENDENCIES.json); lockfiles retain exact resolutions where supplied. Large weights and bulk datasets are obtained separately.
