# Paper Crane — 5-Minute Demo Script

**Audience:** Professors, investors, design-partner labs.
**Goal:** Take them from "what is this?" to "I want a beta seat" in 5 minutes.
**Setup:** Browser at `localhost:3000` (or production URL), demo account pre-seeded, dev-mode flag ON for instant mock results.

---

## Pre-flight (do this 60 seconds before the call)

- Open Chrome, full-screen, hide bookmarks bar.
- Sign out of any existing session.
- Have `1CRN.pdb` snippet copied to clipboard (crambin, 46 residues — small, loads fast).
- Confirm dev-mode env flag: `NEXT_PUBLIC_DEMO_MODE=true` so job submission returns mock designs in ~2s.
- Open these tabs in order: `/`, `/benchmark`, `/dashboard`.

---

## The Flow

### 0:00 — Hook: the benchmark
- Land on `/benchmark`.
- Point at the Pareto frontier chart: "These are public binder-design tools plotted on success rate vs cost. Paper Crane sits here." (point top-right corner — TBD numbers, do not fabricate).
- One sentence: "We are the first managed pipeline that runs all of them and picks the best per target."

### 0:30 — Sign in
- Click **Sign in**, use Google OAuth as the demo account.
- Land on `/dashboard` — show project list, recent runs, credit balance.
- "This is what a wet-lab scientist sees when they open the app."

### 1:00 — Pick a target
- Click into a project, navigate to `/target`.
- Paste **1CRN** into the PDB input.
- Structure loads in the Mol* viewer. Rotate it once for the camera.
- "Crambin — small example. In production this is GPCRs, kinases, whatever they care about."

### 1:30 — Hotspots
- Click 3 surface residues to mark as hotspots (highlighted in yellow).
- Click **Save hotspots**.
- "These tell the design model where to focus the binder interface."

### 2:00 — Submit a design job
- Click **New design run**.
- Select tool: **BoltzGen** (mention RFdiffusion, BindCraft also available).
- Set N = 50 designs.
- Click **Submit**.
- In dev-mode: 5 mock designs return in ~2s with realistic ipSAE / ipTM / pLDDT distributions.
- "In production this runs on Modal or the lab's own GPUs via BYOK — same UX either way."

### 3:00 — Browse the designs
- Navigate to `/app/designs`.
- Top 3 ranked by composite score (ipSAE > ipTM > pDockQ — show the metric tooltip).
- Click design #1: full metric panel, sequence, predicted complex structure in viewer.
- "This ranking comes from the validated thresholds in our novel-metrics research — not gut feel."

### 4:00 — Side-by-side compare
- Multi-select top 3 → **Compare**.
- Three viewers + metric table side-by-side.
- Highlight where the metrics diverge ("design 2 has higher ipSAE but worse interface SC").

### 4:30 — Export
- Click **Export FASTA** on the top design.
- Show the downloaded file: clean header, sequence, ready for cell-free or twist-order.
- "Wet lab gets exactly what they need. No file conversions, no glue scripts."

### 5:00 — Close: BYOK + keys
- Quick stop at `/settings/keys`: API keys for programmatic access.
- Mention `/onboarding/connect-modal`: "If a lab already has Modal credits or their own GPUs, they connect once and we route their jobs there. Their data stays theirs."
- One-liner: "Beta is invite-only right now. Join the waitlist."

---

## If they ask hard questions

- **"What's your moat?"** → Pipeline orchestration + benchmark dataset + per-target tool selection. Models commoditize, we don't.
- **"Why now?"** → BoltzGen, BindCraft, Chai-1 all dropped in the last 18 months. Nobody has glued them together yet.
- **"How big is this?"** → Every binder-design lab is a customer. Plus pharma. TBD on TAM, do not fabricate.
- **"Pricing?"** → Credit-based, BYOK option for labs with their own compute. Public pricing TBD until we close design partners.

## Total runtime
**5:00** — keep it tight. If they interrupt with questions, finish the current beat then answer.
