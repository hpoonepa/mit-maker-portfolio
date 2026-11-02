# Structure image and BLI figures

## Structure image

`binder-complex.png` is an unmodified copy of the project's
`homepage-overview-minibinder.png` from the original iGEM upload package. Its
SHA-256 matches the package's asset-map entry. Teal shows the minibinder and
gold the DWV target fragment. It is a campaign illustration of a predicted
complex, not an experimental atomic structure.

The package also contains the explicitly named
[`l79_s469532_mpnn9` coordinates](l79_s469532_mpnn9.pdb). Their hash matches the
original structure metadata, which identifies the source as the team's
BindCraft prediction. A later predicted complex is retained in
[design provenance](../results/5g51/design-provenance/r10_l79_s469532_mpnn9_complex.cif).
No render sidecar links the PNG to a specific coordinate export, so the image
alone is not used to authenticate the positive design or its binding pose.

## Experimental plots

The separately submitted BLI plots are the original Adaptyv PNGs from
`Lambert_iGEM_VP3_Deformed_Wing_Virus_Binder_data_package (1).zip`:

| Portfolio figure | Original archive member | Identity |
|---|---|---|
| Replicate 1 (`../results/bli/sg_rep31_f3.png`, submitted separately) | `package/data/sensorgrams/rep31/sg_rep31_f3.png` | `l79_s469532_mpnn9`, replicate 31, selected standard fit 3 |
| Replicate 2 (`../results/bli/sg_rep32_f6.png`, submitted separately) | `package/data/sensorgrams/rep32/sg_rep32_f6.png` | `l79_s469532_mpnn9`, replicate 32, selected standard fit 6 |

The archive's replicate table identifies both runs as the same design. The fit
table identifies the selected models. The summary, replicate table and fit table retained here, and the separately
submitted plots, are byte-for-byte identical to those archive members; the
images were not redrawn or altered for the portfolio.

The overall result is `6.036332007942429e-7 M`, or about 0.60 µM. The report
classifies binding as positive and fit quality as Medium. Binding does not
establish the predicted pose or antiviral activity.

[Machine-readable source paths and hashes](evidence-sources.json) ·
[Full experimental provenance](../results/PROVENANCE.md)

## Process graphic

Design process (`design-process.svg`, submitted separately) is a new schematic prepared for this portfolio
from the Lambert modeling report and the original assay records. The
PNG export (`design-process.png`, submitted separately) is submitted separately. It illustrates the
campaign workflow and both experimental rounds; it is not a historical lab
record or a claim that one particular change caused binding. The
[pipeline notes](../docs/PIPELINE-NOTES.md) explain the chronology, and the
[source record](story-sources.json) records the original local documents and hashes.
