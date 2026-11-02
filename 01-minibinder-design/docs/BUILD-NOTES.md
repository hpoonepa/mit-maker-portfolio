# Minibinders against Deformed Wing Virus

U.S. beekeepers lost an estimated 55.6% of their managed colonies between April 2024 and April 2025. Deformed Wing Virus (DWV), spread by Varroa mites, is a major threat to bee health: infected bees can emerge unable to fly and die young. With my Lambert iGEM team, I wanted to design a small protein that binds DWV's VP3 capsid protein, toward eventually blocking infection.

## The first attempt

I spent three months learning tools including RFdiffusion, BindCraft and Boltz, trying different epitopes and checking solubility. I focused heavily on ipSAE and ipTM because I expected higher interface confidence to predict binding. I also compared tools and metrics against experimental binder data to see which scores were useful.

The retained Boltz-2 evaluation gave 5G51_condF_s95 0.944 ipTM and 0.900 ipSAE, yet it tested negative. Of our first 15 designs, nine were negative and six had no assay loading. We had no confirmed binders.

## Rebuilding the workflow

I focused on where the binder would attach and whether we could produce usable, soluble protein. Looking at VP3 within the capsid revealed problems with our original target region. I investigated the QP / A-ridge and checked independent predictions of each binder's fold, amino-acid composition and aggregation risk. That site-review work also led me to build PRINCE, my epitope-analysis tool.

I wanted to try Mosaic and control how candidates were generated and assessed. I wrote a runner that sets VP3 hotspots, uses soluble-ProteinMPNN sequence scoring and can exclude cysteine. It records interface metrics and saves every completed candidate, so an interrupted campaign can resume without repeating finished work. I used these tools alongside BindCraft and BoltzProt to explore different designs.

## What worked

Vedant and I contributed designs to the second round. Of 20 candidates, one confirmed binder was mine: a 79-amino-acid BindCraft design targeting the QP / A-ridge. Adaptyv measured about 604 nM overall apparent affinity against the tested VP3 construct, with two BLI replicates of 546 and 666 nM.

Next I want to test the binder in my own lab and carry out affinity maturation to improve its binding. Testing it against the assembled virus would let us investigate whether that binding helps block infection.
