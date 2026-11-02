# Paper Crane — Terms of Service

**Effective: 2026-04-27** · **Last updated: 2026-04-27**

These Terms of Service ("Terms") are a contract between you ("you", "Customer") and **Paper Crane, Inc.**, a Delaware corporation ("Paper Crane", "we", "us", "our"). They govern your access to and use of the Paper Crane platform, websites, APIs, dashboards, and any related products or documentation (collectively, the "Service").

By creating an account, clicking "I agree", running a job, calling our API, or otherwise using the Service, you agree to these Terms. If you do not agree, do not use the Service.

---

## 0. The plain-English summary

We're a protein-design tooling company. Here's the deal in one screen, before the legalese:

- **You own your designs.** What you upload, generate, and download is yours. We don't claim authorship.
- **We need a narrow license** to anonymized, aggregated *usage data* (timings, success rates, error patterns) so we can keep the benchmark honest and improve our pipelines. We do **not** train foundation models on your private inputs without explicit opt-in.
- **Pay for what you run.** Seeds and compute consumed are non-refundable. Subscription portions are pro-rated under §5.
- **Don't break the law or build weapons.** Our biosecurity policy is enforceable. We will suspend accounts that violate it.
- **No warranties of biological function.** Models are predictions, not promises. You are responsible for wet-lab validation.
- **Liability is capped** at the fees you paid us in the prior 12 months, except for the usual carve-outs.
- **Delaware law, JAMS arbitration in San Francisco**, with a small-claims and IP-injunction carve-out.

The full terms control if there's any conflict, but if you only read this section, you have the gist.

---

## 1. Definitions

- **"Account"** — your registered user or organization account on the Service.
- **"Customer Content"** — any data, sequences, structures, target definitions, designs, or outputs you submit to or generate on the Service.
- **"Designs"** — protein sequences, backbones, and structures generated for you by tools run on the Service.
- **"Documentation"** — the published guides, API docs, and methodology papers at papercrane.bio/docs.
- **"Order Form"** — a written or electronic ordering document signed or accepted by you and us referencing these Terms.
- **"Seeds"** — the unit of consumption for generative jobs, as published on our pricing page or your Order Form.
- **"Subprocessor"** — a third party we use to provide the Service (listed in the Privacy Policy).
- **"Tools"** — third-party or first-party software pipelines (e.g., RFdiffusion, BindCraft, Boltz-2, Chai-1, AlphaFold) that we orchestrate on your behalf.

---

## 2. Eligibility & Account

You must be at least 18 years old and able to form a binding contract. If you sign up on behalf of an organization, you represent that you have the authority to bind that organization, and "you" then refers to the organization.

You agree to (a) provide accurate registration information, (b) keep your credentials secret, (c) not share an Account between multiple humans, and (d) notify us promptly at security@papercrane.bio if you suspect unauthorized access.

You are responsible for everything that happens under your Account, including the actions of your team members and any API keys you issue.

---

## 3. The Service

We orchestrate protein-design tools on managed compute, store your inputs and outputs, run a public reproducibility benchmark, and provide dashboards, APIs, and a CLI to interact with all of the above. The exact set of features depends on your tier.

We may add, change, deprecate, or remove features from time to time. For paid customers on an annual Order Form, we will not materially degrade the core paid features during your committed term without your consent or a pro-rata refund of unused fees.

The Service depends on third-party model weights, datasets, and cloud infrastructure. Their availability and licensing terms can change. We will use commercially reasonable efforts to keep the Service usable, but we cannot guarantee that any specific Tool, model version, or dataset will remain available indefinitely.

---

## 4. Acceptable use

You agree **not** to use the Service to:

1. Design, generate, or characterize toxins, select agents, controlled pathogens, gain-of-function mutants of pandemic-potential pathogens, or any agent intended or reasonably foreseeable to cause mass harm to humans, animals, plants, or the environment.
2. Circumvent biosecurity screening (yours or ours), nucleic-acid synthesis screening, IBC review, or applicable export controls (EAR, ITAR, BIS Entity List).
3. Build chemical, biological, radiological, or nuclear (CBRN) weapons, dual-use research of concern (DURC) outputs, or anything covered by the United States Government Policy for Oversight of DURC and Pathogens with Enhanced Pandemic Potential.
4. Infringe anyone's intellectual property, trade secrets, privacy, or publicity rights.
5. Reverse-engineer, decompile, scrape, or extract our model weights, prompts, internal data, or non-public APIs, except where this restriction is unenforceable under applicable law.
6. Resell, white-label, or operate the Service as a "model marketplace" for third parties without a written reseller agreement.
7. Send malicious code, attempt to break authentication, evade rate limits, or stress-test our infrastructure without written permission.
8. Train a competing protein-design foundation model on outputs generated by the Service in a way that materially copies our orchestration, ranking, or benchmark methodology (general scientific reuse of your own designs is fine).
9. Misrepresent generated designs as having properties we have not validated (e.g., implying FDA approval, "clinical-grade", or wet-lab confirmation when none exists).
10. Use the Service in life-or-death decisions without independent expert review.

We may suspend or terminate an Account immediately, without refund, for violations of this section. We will use reasonable judgment and try to give you notice for non-egregious violations, but we are not obligated to.

---

## 5. Plans, fees, and billing

### 5.1 Subscriptions
Subscription fees are billed in advance, monthly or annually, and are **non-refundable** except where required by law or expressly granted by us in writing. If you cancel, your subscription remains active through the end of the current paid period; we will not pro-rate a partial month.

### 5.2 Seeds and consumption
Generative jobs consume Seeds. **Seeds, once consumed, are non-refundable.** This includes:
- Jobs that complete successfully.
- Jobs that you cancel after compute has started.
- Jobs that fail due to your inputs (malformed PDB, invalid hotspots, out-of-spec sequence length, etc.).

If a job fails because of an outage or bug **on our side**, we will refund or re-credit the Seeds. Determination is at our reasonable discretion based on logs.

### 5.3 Overages
If you exceed your plan's included Seeds, we will either (a) bill the overage at the published per-Seed rate, or (b) pause new generative jobs until you top up. Free-tier accounts always pause; paid accounts default to billing unless you opt into the pause behavior.

### 5.4 Taxes
Fees do not include taxes. You are responsible for all sales, use, VAT, GST, and similar taxes, except taxes on our net income.

### 5.5 Late payment
Invoices are due net 30 unless otherwise stated. Past-due amounts accrue interest at the lesser of 1.0% per month or the maximum rate permitted by law. We may suspend the Service for accounts more than 15 days past due after written notice.

### 5.6 Price changes
We may change prices on 30 days' notice for month-to-month plans, or at renewal for annual plans. Existing committed-term prices are locked for the committed term.

---

## 6. Intellectual property

### 6.1 Customer Content
**You own your Customer Content**, including all Designs you generate. As between you and us, we claim no ownership rights in your sequences, structures, target definitions, or outputs. You are responsible for ensuring you have all rights necessary to upload your Customer Content.

You grant us a non-exclusive, worldwide, royalty-free license to host, store, transmit, display, and process Customer Content **solely to provide and improve the Service for you**.

### 6.2 Anonymized usage data
You also grant us a perpetual, non-exclusive, royalty-free license to:
- Collect anonymized, aggregated **usage telemetry** — job durations, GPU types, success/failure codes, queue times, tool versions, and similar operational metrics — for benchmarking, capacity planning, and Service improvement.
- Publish aggregated benchmark results that do **not** identify you, your organization, your targets, or your sequences.

This license does **not** include the right to train foundation models on your sequences, structures, or designs unless you separately and explicitly opt in (e.g., via a contributor program with a published data agreement).

### 6.3 Our IP
The Service, our software, our benchmark methodology, our orchestration code, our brand, and our documentation are owned by Paper Crane, Inc. and protected by intellectual property law. We grant you a limited, non-exclusive, non-transferable, revocable license to use them to access and use the Service in accordance with these Terms.

### 6.4 Third-party tools and weights
The Tools we orchestrate are owned by their respective authors and licensed under their own terms (often Apache 2.0, MIT, BSD, or research-only licenses). We will surface the relevant license for each Tool inside the Service. By running a Tool, you agree to its license **in addition to** these Terms. If a Tool's license restricts commercial use, you are responsible for not using it commercially.

### 6.5 Feedback
If you send us feedback, suggestions, or feature requests, we may use them without restriction or compensation.

---

## 7. Privacy and data

Your privacy is governed by our [Privacy Policy](/privacy), which is incorporated by reference. The Privacy Policy describes what we collect, how we use it, our subprocessors, retention periods per tier, and your access/correction/deletion rights under the GDPR, the CCPA/CPRA, and similar laws.

For Customers subject to HIPAA, we do **not** currently sign Business Associate Agreements and the Service is not certified for protected health information (PHI). Do not upload PHI.

For Customers requiring SOC 2 attestation: we are pre-SOC 2 as of the Effective Date. Reach out to security@papercrane.bio for our current security questionnaire and roadmap.

---

## 8. DMCA and IP takedowns

If you believe Customer Content on the Service infringes your copyright, send a notice to **dmca@papercrane.bio** that includes:

1. A physical or electronic signature of the rights holder or authorized agent.
2. Identification of the copyrighted work.
3. Identification of the allegedly infringing material and its location on the Service.
4. Your contact information.
5. A good-faith statement that the use is not authorized.
6. A statement under penalty of perjury that the information is accurate and you are authorized to act.

We will respond in accordance with 17 U.S.C. § 512. We may remove or disable the allegedly infringing material and notify the user who uploaded it. Repeat infringers will have their Accounts terminated.

For non-copyright IP claims (trademarks, patents, trade secrets), email legal@papercrane.bio with equivalent detail.

---

## 9. Disclaimers — read this one carefully

**THE SERVICE IS PROVIDED "AS IS" AND "AS AVAILABLE", WITHOUT WARRANTIES OF ANY KIND**, express or implied, including the implied warranties of merchantability, fitness for a particular purpose, non-infringement, accuracy, or availability.

In particular:

- **No biological warranty.** Designs generated by the Service are *predictions*. They may not bind, fold, express, be soluble, be non-toxic, be non-immunogenic, or behave as predicted. **You are responsible for wet-lab validation, biosafety review, and regulatory compliance** before any in-vivo, clinical, agricultural, or environmental use.
- **No medical advice.** Nothing in the Service is medical advice. Outputs are not diagnostics, are not approved by any regulator, and must not be used to make patient-care decisions.
- **Models can hallucinate.** Confidence scores (pLDDT, ipTM, ipSAE, etc.) correlate with quality but do not guarantee it. High scores can be wrong.
- **Benchmarks describe past results.** Benchmark metrics are point-in-time estimates on specific targets and are not promises of future performance on your target.
- **Third-party tools change.** Underlying models may be updated, deprecated, or licensed differently. We will give reasonable notice when we can.

Nothing in this section limits any warranty that cannot be disclaimed under applicable law.

---

## 10. Limitation of liability

**TO THE MAXIMUM EXTENT PERMITTED BY LAW**:

- Neither party will be liable for any **indirect, incidental, special, consequential, exemplary, or punitive damages**, or for **lost profits, lost revenue, lost data, or business interruption**, even if advised of the possibility.
- Each party's **aggregate liability** arising out of or related to these Terms or the Service is capped at the **greater of (a) USD $100 or (b) the fees you paid us in the 12 months preceding the event giving rise to the claim**.

These caps do **not** apply to: (i) your breach of §4 (Acceptable Use) or §6 (IP); (ii) your payment obligations; (iii) either party's indemnification obligations; or (iv) liability that cannot be limited under applicable law (gross negligence, willful misconduct, fraud, death, or personal injury where applicable).

You acknowledge that these limitations are an essential basis of the bargain and that the Service would not be provided to you on these economic terms without them.

---

## 11. Indemnification

### 11.1 By you
You will defend, indemnify, and hold harmless Paper Crane and its officers, directors, employees, and agents from any third-party claim arising out of (a) your Customer Content, (b) your use of the Service in violation of these Terms or applicable law, (c) your violation of §4, or (d) your wet-lab, clinical, or commercial use of generated Designs.

### 11.2 By us
We will defend you from any third-party claim alleging that the **Service itself, as provided by us and used in accordance with these Terms**, infringes a U.S. patent, copyright, or trademark, and we will pay damages and costs finally awarded against you for that claim. This obligation does not apply to claims arising from (i) your Customer Content, (ii) your combination of the Service with other products or processes, (iii) modifications you make, or (iv) your use of a deprecated version after we provided a non-infringing replacement.

If we reasonably believe the Service may be subject to such a claim, we may (a) procure a license, (b) modify the Service to be non-infringing, or (c) terminate the affected portion and refund pre-paid unused fees.

This §11.2 states our entire liability for IP infringement claims.

### 11.3 Procedure
The indemnified party must (a) promptly notify the indemnifying party of the claim, (b) give the indemnifying party sole control of the defense, and (c) reasonably cooperate. The indemnifying party may not settle a claim that imposes liability or admits wrongdoing on the indemnified party without consent.

---

## 12. Term, suspension, and termination

These Terms apply from the moment you first use the Service and continue until your Account is terminated.

You can terminate at any time by canceling your subscription and deleting your Account. We can terminate (a) for convenience on 30 days' written notice for free-tier Accounts, (b) for material breach not cured within 15 days of notice, or (c) immediately for §4 violations, non-payment beyond 30 days, or insolvency events.

We may **suspend** the Service immediately without notice if we reasonably believe continued operation would cause us legal exposure, security risk, or harm to others.

On termination: (i) your access ends, (ii) outstanding fees become immediately due, (iii) we will make Customer Content available for export for 30 days under the retention rules of your tier, after which we may delete it, and (iv) §§4–6, 8–11, 13, and 15 survive.

---

## 13. Governing law and disputes

These Terms are governed by the laws of the **State of Delaware**, USA, without regard to conflict-of-laws rules. The U.N. Convention on Contracts for the International Sale of Goods does not apply.

**Informal resolution.** Before filing anything, send a written description of the dispute to legal@papercrane.bio. Both parties agree to negotiate in good faith for 30 days.

**Arbitration.** Any unresolved dispute, except as carved out below, will be resolved by binding individual arbitration administered by **JAMS** under its Streamlined Rules, in **San Francisco, California**, in English, before a single arbitrator. Judgment on the award may be entered in any court of competent jurisdiction.

**Carve-outs.** Either party may (a) bring a claim in small-claims court for claims that qualify, or (b) seek injunctive or equitable relief in any court of competent jurisdiction to protect intellectual property, confidentiality, or §4.

**No class actions.** You and we agree to bring claims only in an individual capacity, not as a class member, class representative, or in a private-attorney-general action. If this clause is unenforceable for a particular claim, that claim must be brought in the state or federal courts in **Wilmington, Delaware**, and both parties consent to personal jurisdiction there.

---

## 14. Export, sanctions, and government users

You represent that you are not located in, and will not use the Service from, a country subject to a comprehensive U.S. embargo, and that you are not on any U.S. government denied-party list (OFAC SDN, BIS Entity List, etc.). You will not export, re-export, or transfer the Service or generated Designs in violation of U.S. or other applicable export-control laws.

The Service is "commercial computer software" and "commercial computer software documentation" under FAR 12.212 and DFARS 227.7202; U.S. government users get only the rights granted to all other Customers.

---

## 15. Miscellaneous

- **Entire agreement.** These Terms, the Privacy Policy, the Acceptable Use Policy, and any Order Form are the entire agreement between us regarding the Service. Order Form terms control over conflicting Terms only where the Order Form expressly amends a numbered section here.
- **Changes.** We may update these Terms by posting a new version with a new Effective Date and, for material changes, giving you 30 days' notice (in-app, email, or both). Continued use after the effective date is acceptance.
- **Assignment.** You may not assign these Terms without our written consent, except to a successor in a merger or acquisition that is not a competitor of ours. We may assign freely to an affiliate or successor.
- **Force majeure.** Neither party is liable for delays caused by events beyond reasonable control (acts of God, war, terrorism, pandemics, internet or cloud-provider outages, government action). Payment obligations are not excused.
- **Notices.** Legal notices to us must go to legal@papercrane.bio with a copy to Paper Crane, Inc., Atlanta, GA, USA. Notices to you go to your Account email.
- **No waiver.** Failure to enforce a right is not a waiver of it.
- **Severability.** If any clause is unenforceable, the rest stays in effect, and the unenforceable clause is reformed to the minimum extent needed.
- **Independent contractors.** No agency, partnership, joint venture, or employment is created.
- **Headings.** Headings are for convenience and do not affect interpretation.

---

## 16. Contact

- **General:** hello@papercrane.bio
- **Legal:** legal@papercrane.bio
- **Security:** security@papercrane.bio
- **Privacy:** privacy@papercrane.bio
- **Biosecurity:** biosecurity@papercrane.bio
- **DMCA:** dmca@papercrane.bio

Paper Crane, Inc. · Delaware C-Corp · Operating from Atlanta, GA → San Francisco, CA.
