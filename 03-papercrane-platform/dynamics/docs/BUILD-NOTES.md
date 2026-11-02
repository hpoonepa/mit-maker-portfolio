# Paper Crane: protein dynamics

Protein dynamics kept coming up when my co-founder and I talked with researchers. My binder work focused on an interaction with one target structure, but proteins change shape. I wanted to predict some of that movement. That became SENBA, the dynamics work within Paper Crane.

## Getting the model to improve

Training from scratch was beyond my GPU budget. I fine-tuned MarS-FM on transitions from mdCATH molecular-dynamics simulations, pairing each starting structure with a structure recorded 50 saved frames later.

The hard part was improving endpoint prediction while keeping useful variation between predictions. A model could move closer to the target frame while producing a narrower range of structures. I needed to check the spread of its predictions, not just choose the best endpoint score.

I tested blends of the fine-tuned weights and the original model. The released checkpoint keeps 7.35% of the update from ten training epochs. It passed all seven ensemble-retention checks on the eight-protein panel, covering properties such as size, fluctuations and contacts.

## Checking what the score meant

On the 28-protein validation panel used during development, SENBA reduced ensemble-mean endpoint error on 27 proteins. The mean gain was 0.0326 angstrom in C-alpha RMSD, a measure of backbone position error.

Then I checked how much the number of predictions affected the result. On eight of those proteins, the mean gain fell from 0.02401 angstrom with four predictions to 0.01383 with sixteen. SENBA also produced a narrower spread of structures than MarS-FM. I added checks of that spread alongside average endpoint error so I could see both changes.

The improvement remained, but it was small. Next I want to evaluate unused proteins and repeat the larger-sample checks with other training seeds. I built Studio to show saved SENBA predictions beside MarS-FM and recorded simulation frames. The original model and simulation data are credited to the MarS-FM and mdCATH teams.
