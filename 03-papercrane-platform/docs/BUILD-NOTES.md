# Paper Crane

During my minibinder work, getting Mosaic or BoltzGen ready could take hours. I had to install dependencies, configure runs and move between platforms or my own codebase. Researchers my co-founder and I spoke with described the same frustration, especially when their main work was in the lab. I co-founded Paper Crane to put those tools in one workspace, with my main responsibility being the backend and GPU orchestration.

## Connecting the tools

The catalog has 52 tools at different stages of integration. I built adapters that translate the app's inputs into each tool's configuration and turn its outputs into results the app can display. Jobs pass through the API into a Redis queue, where a worker calls the appropriate Modal function. I configure each tool's dependencies, model files and compute resources; BoltzGen, for example, runs in its own container and requests an A100 GPU with 40 GB of memory.

## Getting a real run through

The difficult part was getting every step to agree about inputs and outputs. ProteinMPNN's wrapper passed a directory of structures to a command that expected one PDB structure file. I changed it to run each file separately for every requested seed. ESM-2 had a different problem: the worker depended on output printed by a detached remote function. I changed the function to return its result and completion events directly, so the worker could receive them reliably.

I added regression checks for both boundaries, then tested the complete path. The September 30 local verification recorded a real ESM-2 inference and three ProteinMPNN jobs submitted through the authenticated API, Redis and worker. Each ProteinMPNN job completed remote inference and saved one design, with its sequence file stored in R2 cloud storage. That let me check the actual handoffs from submission to a result I could retrieve.

The demo shows tool search, target entry and a saved structure result. I'm still improving GPU setup and checking the remaining integrations with real runs. RFdiffusion, BindCraft, Boltz and the other scientific tools are credited to their original research teams.
