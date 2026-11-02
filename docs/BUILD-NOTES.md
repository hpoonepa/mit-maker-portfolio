# Project build notes

This source-only archive contains the code, research records and build notes. Submission videos, images and PDFs are provided separately.

[MiniBinder](../01-minibinder-design/docs/BUILD-NOTES.md) · [Paper Crane platform](../03-papercrane-platform/docs/BUILD-NOTES.md) · [Paper Crane dynamics](../03-papercrane-platform/dynamics/docs/BUILD-NOTES.md) · [SquashVision](../02-squash-vision/docs/BUILD-NOTES.md)

## Minibinders against Deformed Wing Virus

U.S. beekeepers lost an estimated 55.6% of their managed colonies between April 2024 and April 2025. Deformed Wing Virus (DWV), spread by Varroa mites, is a major threat to bee health: infected bees can emerge unable to fly and die young. With my Lambert iGEM team, I wanted to design a small protein that binds DWV's VP3 capsid protein, toward eventually blocking infection.

### The first attempt

I spent three months learning tools including RFdiffusion, BindCraft and Boltz, trying different epitopes and checking solubility. I focused heavily on ipSAE and ipTM because I expected higher interface confidence to predict binding. I also compared tools and metrics against experimental binder data to see which scores were useful.

The retained Boltz-2 evaluation gave 5G51_condF_s95 0.944 ipTM and 0.900 ipSAE, yet it tested negative. Of our first 15 designs, nine were negative and six had no assay loading. We had no confirmed binders.

### Rebuilding the workflow

I focused on where the binder would attach and whether we could produce usable, soluble protein. Looking at VP3 within the capsid revealed problems with our original target region. I investigated the QP / A-ridge and checked independent predictions of each binder's fold, amino-acid composition and aggregation risk. That site-review work also led me to build PRINCE, my epitope-analysis tool.

I wanted to try Mosaic and control how candidates were generated and assessed. I wrote a runner that sets VP3 hotspots, uses soluble-ProteinMPNN sequence scoring and can exclude cysteine. It records interface metrics and saves every completed candidate, so an interrupted campaign can resume without repeating finished work. I used these tools alongside BindCraft and BoltzProt to explore different designs.

### What worked

Vedant and I contributed designs to the second round. Of 20 candidates, one confirmed binder was mine: a 79-amino-acid BindCraft design targeting the QP / A-ridge. Adaptyv measured about 604 nM overall apparent affinity against the tested VP3 construct, with two BLI replicates of 546 and 666 nM.

Next I want to test the binder in my own lab and carry out affinity maturation to improve its binding. Testing it against the assembled virus would let us investigate whether that binding helps block infection.

---

## Paper Crane

During my minibinder work, getting Mosaic or BoltzGen ready could take hours. I had to install dependencies, configure runs and move between platforms or my own codebase. Researchers my co-founder and I spoke with described the same frustration, especially when their main work was in the lab. I co-founded Paper Crane to put those tools in one workspace, with my main responsibility being the backend and GPU orchestration.

### Connecting the tools

The catalog has 52 tools at different stages of integration. I built adapters that translate the app's inputs into each tool's configuration and turn its outputs into results the app can display. Jobs pass through the API into a Redis queue, where a worker calls the appropriate Modal function. I configure each tool's dependencies, model files and compute resources; BoltzGen, for example, runs in its own container and requests an A100 GPU with 40 GB of memory.

### Getting a real run through

The difficult part was getting every step to agree about inputs and outputs. ProteinMPNN's wrapper passed a directory of structures to a command that expected one PDB structure file. I changed it to run each file separately for every requested seed. ESM-2 had a different problem: the worker depended on output printed by a detached remote function. I changed the function to return its result and completion events directly, so the worker could receive them reliably.

I added regression checks for both boundaries, then tested the complete path. The September 30 local verification recorded a real ESM-2 inference and three ProteinMPNN jobs submitted through the authenticated API, Redis and worker. Each ProteinMPNN job completed remote inference and saved one design, with its sequence file stored in R2 cloud storage. That let me check the actual handoffs from submission to a result I could retrieve.

The demo shows tool search, target entry and a saved structure result. I'm still improving GPU setup and checking the remaining integrations with real runs. RFdiffusion, BindCraft, Boltz and the other scientific tools are credited to their original research teams.

---

## Paper Crane: protein dynamics

Protein dynamics kept coming up when my co-founder and I talked with researchers. My binder work focused on an interaction with one target structure, but proteins change shape. I wanted to predict some of that movement. That became SENBA, the dynamics work within Paper Crane.

### Getting the model to improve

Training from scratch was beyond my GPU budget. I fine-tuned MarS-FM on transitions from mdCATH molecular-dynamics simulations, pairing each starting structure with a structure recorded 50 saved frames later.

The hard part was improving endpoint prediction while keeping useful variation between predictions. A model could move closer to the target frame while producing a narrower range of structures. I needed to check the spread of its predictions, not just choose the best endpoint score.

I tested blends of the fine-tuned weights and the original model. The released checkpoint keeps 7.35% of the update from ten training epochs. It passed all seven ensemble-retention checks on the eight-protein panel, covering properties such as size, fluctuations and contacts.

### Checking what the score meant

On the 28-protein validation panel used during development, SENBA reduced ensemble-mean endpoint error on 27 proteins. The mean gain was 0.0326 angstrom in C-alpha RMSD, a measure of backbone position error.

Then I checked how much the number of predictions affected the result. On eight of those proteins, the mean gain fell from 0.02401 angstrom with four predictions to 0.01383 with sixteen. SENBA also produced a narrower spread of structures than MarS-FM. I added checks of that spread alongside average endpoint error so I could see both changes.

The improvement remained, but it was small. Next I want to evaluate unused proteins and repeat the larger-sample checks with other training seeds. I built Studio to show saved SENBA predictions beside MarS-FM and recorded simulation frames. The original model and simulation data are credited to the MarS-FM and mdCATH teams.

---

## SquashVision

I've played squash for over eight years, and I review matches whether I win or lose. For the past few years, I drew courts on paper and marked where I missed shots. Working through a match could take about an hour. I wanted to spend more of that time learning from the match and applying it on court. My interest in coding gave me a way to build the review tool I wanted.

### From footage to a review

I built SquashVision around a Python processing pipeline and a React interface. The pipeline uses Ultralytics YOLO for player pose and an adaptation of TrackNetV3 for the ball. Calibration maps image positions into court coordinates. Detections keep their timestamps and source frames, so the interface can show the replay alongside movement maps and shot markers. The upstream tracking models retain their authors' credits.

The demo uses an ElShorbagy-Farag match from Canary Wharf. I can follow a rally, inspect a shot and check its measurements against the footage.

### Getting the tracking to behave

The ball is small and fast, and wall contacts and floor bounces can be hard to distinguish. Early attempts could lose it, mistake someone behind the court for a player, or struggle when the camera angle changed. I spent a lot of time iterating on those cases.

I added a playing-area outline to exclude people outside the court, calibrated the geometry and made shot markers editable. In one Canary Wharf shot, the detector assigns the hitter to Player B. The saved review corrects it to Player A and leaves the hidden bounce unknown. My placement rules also allow a partial wall score when the first bounce is missing, keeping it out of bounce-based averages.

### Using it in my training

I now use SquashVision for my own match review, and its feedback helped me make a new training plan. I'm happy to have a tool I can use and keep improving. My next work is better tracking across courts and a complete web workflow for uploading a match, processing it and returning to the saved review.
