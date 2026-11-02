# Paper Crane — Meta-Scorer Build Overview

*Short version for the team. Two detailed engineering plans sit behind this (data + model); this is the why and the shape.*

## The problem we're solving
A customer gives us a target protein. Our tools generate hundreds of candidate binder designs. We can only afford to send ~20 to the wet-lab. **Which 20?** Everyone ranks by a single score (like ipSAE) — but the *right* score is different for every protein. That's the gap.

## Our answer (the differentiator)
We don't compete on the design models — we own the layer above them: a system that figures out **what matters for THIS specific protein** and ranks designs accordingly.

1. **Measure the target** (plain code) — flat or pocketed? greasy or charged? stiff or floppy?
2. **Find similar past targets** (search) — "looks like these 3 we have real lab data on; here's what worked."
3. **LLM decides what matters for this protein** (the brain) — reads the measurements + similar cases + a rulebook of metrics, and outputs a custom scoring recipe *for this target*, with a written rationale. It does **not** predict binding — it picks which yardsticks to trust.
4. **Rank & ship top 20** (math).
5. **Lab results flow back** and sharpen the system. That growing record of "what actually worked" is the moat — anyone can download the same tools and public data, but not our outcomes.

**Why the LLM and not a trained model for step 3:** we only have ~12 labeled targets — far too few to *learn* per-target weighting from data. The LLM reasons from biology instead, and gets corrected by real data as it arrives. (RAG, not fine-tuning — no training data needed, instantly updatable.)

## The one experiment that decides everything
> Does the LLM's per-target recipe rank real binders better than one fixed recipe, on held-out targets with real lab labels?

**Yes → real company. No → we fall back to one global model.** This planned comparison will determine whether target-specific recipes improve ranking; the result remains open.

## The two plans

**Plan A — Data** (33 tasks): get real binding labels into our system.
- Clean what we have (Proteinbase) → harvest public real-label datasets (Cao-2022, Adaptyv, PPB-Affinity…) via LLM → run our tools on them so they're in our format → generate NEW labels on new targets via wet-lab.

**Plan B — Model** (52 tasks): the scorer + the experiment.
- Target features → similar-target lookup → LLM recipe → ranking → a corrector that learns from real labels → the leave-one-target-out test that proves (or kills) the thesis.

## Honest constraints the team should know
- **Proteinbase is public** (an Adaptyv download) — it is *not* our moat. The moat is our accumulated lab outcomes + the benchmark.
- **The real bottleneck is targets, not designs.** We have ~12 labeled targets (two-thirds is one virus). We need **~15–30 diverse targets with real binding data** to prove the thesis. **Getting that data is the critical path** — modeling is the easy half.
- **Labels must be real wet-lab.** We never let any in-silico score (or an LLM) decide "this binds" and then train on it — that's circular and a technical investor spots it instantly.
- The system **runs and is useful on day one** (cold-start recipes); it just can't be *proven better* until we have more labeled targets.

## Status
Two fully-detailed, test-driven build plans written and reviewed (twice, adversarially). **No code written yet.** Next step is execution. Biggest open item is the data-acquisition program (the new labeled targets), which we can start in parallel with the build.
