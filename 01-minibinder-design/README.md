# Minibinders against Deformed Wing Virus

Deformed Wing Virus can leave honeybees unable to fly. With my Lambert iGEM team, I worked on a small protein that binds its VP3 target, as a first step toward something we could eventually test for interference with infection.

Submission figures are provided separately; this source-only archive retains the coordinates, assay tables and analysis code.

I spent about three months learning protein design and trying tools including RFdiffusion and BindCraft. Our first 15 designs produced zero confirmed binders: nine negative and six unresolved results with no assay loading. I then reviewed the target in the surrounding viral structure, combined different generators and independent folding checks, and compared sequence properties and candidate diversity. I wrote campaign runners and analysis around the existing research tools, including saving completed designs so interrupted GPU jobs could be resumed.

The second round produced one positive from 20 designs: **`l79_s469532_mpnn9`**, a 79-residue BindCraft design. Adaptyv measured an overall apparent affinity of approximately **604 nM**. The final order assigns seven designs to me and thirteen to Vedant; the positive is one of my seven. Adaptyv performed the measurements. Binding to the tested construct is the result so far; antiviral activity and heat stability still need testing.

The two BLI replicates measured 546 nM and 666 nM. Original plots are submitted separately; the assay records are linked below.

[Build notes](docs/BUILD-NOTES.md) · [First-batch scores](results/bli/first-batch-scores.csv) · [Assay records](results/bli/round2-adaptyv-summary.csv) · [Pipeline decisions](docs/PIPELINE-NOTES.md)

[Source and setup](docs/SOURCE-GUIDE.md) maps the campaign scripts, compute backends and retained earlier experiments. [PRINCE](prince/) is the later target-site review and ranking tool; its records do not establish that it selected the positive binder. The [citations and credits](CITATIONS.md) distinguish our campaign/software contributions from the scientific tools, models and datasets we used.
