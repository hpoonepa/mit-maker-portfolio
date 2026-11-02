import type { Metadata } from "next";
import Link from "next/link";
import { LegalLayout } from "@/components/legal/LegalLayout";
import { pageMetadata } from "@/lib/metadata";

const TITLE = "Terms of Service";
const DESCRIPTION =
  "Paper Crane Terms of Service. Account terms, acceptable use, IP ownership, billing, disclaimers, and dispute resolution.";

export const metadata: Metadata = pageMetadata({
  title: TITLE,
  description: DESCRIPTION,
  path: "/terms",
  ogTitle: "Terms",
  ogDesc: "Acceptable use, IP, and the legal stuff.",
});

export default function TermsPage() {
  return (
    <LegalLayout
      eyebrow="§ Legal · Terms"
      title="Terms of Service."
      effective="2026-04-27"
      intro={
        <>
          These Terms are a contract between you and{" "}
          <strong className="text-ink">Paper Crane, Inc.</strong>, a Delaware
          corporation. They cover your use of papercrane.bio,
          app.papercrane.bio, our APIs, our CLI, and any related products. By
          signing up, clicking &quot;I agree&quot;, or running a job, you
          accept them.
        </>
      }
    >
      <h2>0. The plain-English summary</h2>
      <p>
        We&apos;re a protein-design tooling company. Here&apos;s the deal in
        one screen, before the legalese:
      </p>
      <ul>
        <li>
          <strong>You own your designs.</strong> What you upload, generate,
          and download is yours. We don&apos;t claim authorship.
        </li>
        <li>
          <strong>We need a narrow license</strong> to anonymized, aggregated{" "}
          <em>usage data</em> (timings, success rates, error patterns) so we
          can keep the benchmark honest and improve our pipelines. We do{" "}
          <strong>not</strong> train foundation models on your private inputs
          without explicit opt-in.
        </li>
        <li>
          <strong>Pay for what you run.</strong> Seeds and compute consumed
          are non-refundable. Subscription portions are pro-rated under §5.
        </li>
        <li>
          <strong>Don&apos;t break the law or build weapons.</strong> Our
          biosecurity policy is enforceable. We will suspend accounts that
          violate it.
        </li>
        <li>
          <strong>No warranties of biological function.</strong> Models are
          predictions, not promises. You are responsible for wet-lab
          validation.
        </li>
        <li>
          <strong>Liability is capped</strong> at the fees you paid us in the
          prior 12 months, except for the usual carve-outs.
        </li>
        <li>
          <strong>Delaware law, JAMS arbitration in San Francisco</strong>,
          with a small-claims and IP-injunction carve-out.
        </li>
      </ul>
      <p>
        The full terms control if there&apos;s any conflict, but if you only
        read this section, you have the gist.
      </p>

      <h2>1. Definitions</h2>
      <ul>
        <li>
          <strong>&quot;Account&quot;</strong> — your registered user or
          organization account on the Service.
        </li>
        <li>
          <strong>&quot;Customer Content&quot;</strong> — any data, sequences,
          structures, target definitions, designs, or outputs you submit to or
          generate on the Service.
        </li>
        <li>
          <strong>&quot;Designs&quot;</strong> — protein sequences, backbones,
          and structures generated for you by tools run on the Service.
        </li>
        <li>
          <strong>&quot;Order Form&quot;</strong> — a written or electronic
          ordering document signed or accepted by you and us referencing these
          Terms.
        </li>
        <li>
          <strong>&quot;Seeds&quot;</strong> — the unit of consumption for
          generative jobs, as published on our pricing page or your Order
          Form.
        </li>
        <li>
          <strong>&quot;Subprocessor&quot;</strong> — a third party we use to
          provide the Service (listed in the Privacy Policy).
        </li>
        <li>
          <strong>&quot;Tools&quot;</strong> — third-party or first-party
          software pipelines (e.g., RFdiffusion, BindCraft, Boltz-2, Chai-1,
          AlphaFold) that we orchestrate on your behalf.
        </li>
      </ul>

      <h2>2. Eligibility &amp; Account</h2>
      <p>
        You must be at least 18 years old and able to form a binding contract.
        If you sign up on behalf of an organization, you represent that you
        have the authority to bind that organization, and &quot;you&quot; then
        refers to the organization.
      </p>
      <p>
        You agree to (a) provide accurate registration information, (b) keep
        your credentials secret, (c) not share an Account between multiple
        humans, and (d) notify us promptly at security@papercrane.bio if you
        suspect unauthorized access. You are responsible for everything that
        happens under your Account, including the actions of your team
        members and any API keys you issue.
      </p>

      <h2>3. The Service</h2>
      <p>
        We orchestrate protein-design tools on managed compute, store your
        inputs and outputs, run a public reproducibility benchmark, and
        provide dashboards, APIs, and a CLI to interact with all of the
        above. The exact set of features depends on your tier.
      </p>
      <p>
        We may add, change, deprecate, or remove features. For paid customers
        on an annual Order Form, we will not materially degrade core paid
        features during your committed term without your consent or a
        pro-rata refund of unused fees.
      </p>
      <p>
        The Service depends on third-party model weights, datasets, and cloud
        infrastructure. Their availability and licensing terms can change. We
        will use commercially reasonable efforts to keep the Service usable,
        but we cannot guarantee that any specific Tool, model version, or
        dataset will remain available indefinitely.
      </p>

      <h2>4. Acceptable use</h2>
      <p>
        You agree <strong>not</strong> to use the Service to:
      </p>
      <ol>
        <li>
          Design, generate, or characterize toxins, select agents, controlled
          pathogens, gain-of-function mutants of pandemic-potential pathogens,
          or any agent intended or reasonably foreseeable to cause mass harm
          to humans, animals, plants, or the environment.
        </li>
        <li>
          Circumvent biosecurity screening (yours or ours), nucleic-acid
          synthesis screening, IBC review, or applicable export controls
          (EAR, ITAR, BIS Entity List).
        </li>
        <li>
          Build chemical, biological, radiological, or nuclear (CBRN)
          weapons, dual-use research of concern (DURC) outputs, or anything
          covered by the United States Government Policy for Oversight of
          DURC and Pathogens with Enhanced Pandemic Potential.
        </li>
        <li>
          Infringe anyone&apos;s intellectual property, trade secrets,
          privacy, or publicity rights.
        </li>
        <li>
          Reverse-engineer, decompile, scrape, or extract our model weights,
          prompts, internal data, or non-public APIs, except where this
          restriction is unenforceable under applicable law.
        </li>
        <li>
          Resell, white-label, or operate the Service as a &quot;model
          marketplace&quot; for third parties without a written reseller
          agreement.
        </li>
        <li>
          Send malicious code, attempt to break authentication, evade rate
          limits, or stress-test our infrastructure without written
          permission.
        </li>
        <li>
          Train a competing protein-design foundation model on outputs
          generated by the Service in a way that materially copies our
          orchestration, ranking, or benchmark methodology (general
          scientific reuse of your own designs is fine).
        </li>
        <li>
          Misrepresent generated designs as having properties we have not
          validated (e.g., implying FDA approval, &quot;clinical-grade&quot;,
          or wet-lab confirmation when none exists).
        </li>
        <li>
          Use the Service in life-or-death decisions without independent
          expert review.
        </li>
      </ol>
      <p>
        We may suspend or terminate an Account immediately, without refund,
        for violations of this section.
      </p>

      <h2>5. Plans, fees, and billing</h2>
      <h3>5.1 Subscriptions</h3>
      <p>
        Subscription fees are billed in advance, monthly or annually, and are{" "}
        <strong>non-refundable</strong> except where required by law. If you
        cancel, your subscription remains active through the end of the
        current paid period.
      </p>
      <h3>5.2 Seeds and consumption</h3>
      <p>
        Generative jobs consume Seeds.{" "}
        <strong>Seeds, once consumed, are non-refundable.</strong> This
        includes:
      </p>
      <ul>
        <li>Jobs that complete successfully.</li>
        <li>Jobs that you cancel after compute has started.</li>
        <li>
          Jobs that fail due to your inputs (malformed PDB, invalid hotspots,
          out-of-spec sequence length, etc.).
        </li>
      </ul>
      <p>
        If a job fails because of an outage or bug{" "}
        <strong>on our side</strong>, we will refund or re-credit the Seeds.
        Determination is at our reasonable discretion based on logs.
      </p>
      <h3>5.3 Overages</h3>
      <p>
        If you exceed your plan&apos;s included Seeds, we will either (a)
        bill the overage at the published per-Seed rate, or (b) pause new
        generative jobs until you top up. Free-tier accounts always pause;
        paid accounts default to billing unless you opt into the pause
        behavior.
      </p>
      <h3>5.4 Taxes</h3>
      <p>
        Fees do not include taxes. You are responsible for all sales, use,
        VAT, GST, and similar taxes, except taxes on our net income.
      </p>
      <h3>5.5 Late payment</h3>
      <p>
        Invoices are due net 30 unless otherwise stated. Past-due amounts
        accrue interest at the lesser of 1.0% per month or the maximum rate
        permitted by law. We may suspend the Service for accounts more than
        15 days past due after written notice.
      </p>
      <h3>5.6 Price changes</h3>
      <p>
        We may change prices on 30 days&apos; notice for month-to-month
        plans, or at renewal for annual plans. Existing committed-term prices
        are locked for the committed term.
      </p>

      <h2>6. Intellectual property</h2>
      <h3>6.1 Customer Content</h3>
      <p>
        <strong>You own your Customer Content</strong>, including all Designs
        you generate. As between you and us, we claim no ownership rights in
        your sequences, structures, target definitions, or outputs. You are
        responsible for ensuring you have all rights necessary to upload your
        Customer Content.
      </p>
      <p>
        You grant us a non-exclusive, worldwide, royalty-free license to
        host, store, transmit, display, and process Customer Content{" "}
        <strong>solely to provide and improve the Service for you</strong>.
      </p>
      <h3>6.2 Anonymized usage data</h3>
      <p>
        You also grant us a perpetual, non-exclusive, royalty-free license
        to:
      </p>
      <ul>
        <li>
          Collect anonymized, aggregated <strong>usage telemetry</strong> —
          job durations, GPU types, success/failure codes, queue times, tool
          versions, and similar operational metrics — for benchmarking,
          capacity planning, and Service improvement.
        </li>
        <li>
          Publish aggregated benchmark results that do <strong>not</strong>{" "}
          identify you, your organization, your targets, or your sequences.
        </li>
      </ul>
      <p>
        This license does <strong>not</strong> include the right to train
        foundation models on your sequences, structures, or designs unless
        you separately and explicitly opt in (e.g., via a contributor program
        with a published data agreement).
      </p>
      <h3>6.3 Our IP</h3>
      <p>
        The Service, our software, our benchmark methodology, our
        orchestration code, our brand, and our documentation are owned by
        Paper Crane, Inc. and protected by intellectual property law. We
        grant you a limited, non-exclusive, non-transferable, revocable
        license to use them to access and use the Service in accordance with
        these Terms.
      </p>
      <h3>6.4 Third-party tools and weights</h3>
      <p>
        The Tools we orchestrate are owned by their respective authors and
        licensed under their own terms (often Apache 2.0, MIT, BSD, or
        research-only licenses). We will surface the relevant license for
        each Tool inside the Service. By running a Tool, you agree to its
        license <strong>in addition to</strong> these Terms. If a
        Tool&apos;s license restricts commercial use, you are responsible
        for not using it commercially.
      </p>
      <h3>6.5 Feedback</h3>
      <p>
        If you send us feedback, suggestions, or feature requests, we may
        use them without restriction or compensation.
      </p>

      <h2>7. Privacy and data</h2>
      <p>
        Your privacy is governed by our{" "}
        <Link href="/privacy" className="underline">
          Privacy Policy
        </Link>
        , which is incorporated by reference. The Privacy Policy describes
        what we collect, how we use it, our subprocessors, retention periods
        per tier, and your access/correction/deletion rights under the GDPR,
        the CCPA/CPRA, and similar laws.
      </p>
      <p>
        For Customers subject to HIPAA, we do <strong>not</strong> currently
        sign Business Associate Agreements and the Service is not certified
        for protected health information (PHI). Do not upload PHI.
      </p>
      <p>
        For Customers requiring SOC 2 attestation: we are pre-SOC 2 as of
        the Effective Date. Reach out to security@papercrane.bio for our
        current security questionnaire and roadmap.
      </p>

      <h2>8. DMCA and IP takedowns</h2>
      <p>
        If you believe Customer Content on the Service infringes your
        copyright, send a notice to <strong>dmca@papercrane.bio</strong>{" "}
        that includes:
      </p>
      <ol>
        <li>
          A physical or electronic signature of the rights holder or
          authorized agent.
        </li>
        <li>Identification of the copyrighted work.</li>
        <li>
          Identification of the allegedly infringing material and its
          location on the Service.
        </li>
        <li>Your contact information.</li>
        <li>A good-faith statement that the use is not authorized.</li>
        <li>
          A statement under penalty of perjury that the information is
          accurate and you are authorized to act.
        </li>
      </ol>
      <p>
        We will respond in accordance with 17 U.S.C. § 512. We may remove or
        disable the allegedly infringing material and notify the user who
        uploaded it. Repeat infringers will have their Accounts terminated.
      </p>

      <h2>9. Disclaimers — read this one carefully</h2>
      <p>
        <strong>
          THE SERVICE IS PROVIDED &quot;AS IS&quot; AND &quot;AS
          AVAILABLE&quot;, WITHOUT WARRANTIES OF ANY KIND
        </strong>
        , express or implied, including the implied warranties of
        merchantability, fitness for a particular purpose, non-infringement,
        accuracy, or availability.
      </p>
      <p>In particular:</p>
      <ul>
        <li>
          <strong>No biological warranty.</strong> Designs generated by the
          Service are <em>predictions</em>. They may not bind, fold, express,
          be soluble, be non-toxic, be non-immunogenic, or behave as
          predicted.{" "}
          <strong>
            You are responsible for wet-lab validation, biosafety review, and
            regulatory compliance
          </strong>{" "}
          before any in-vivo, clinical, agricultural, or environmental use.
        </li>
        <li>
          <strong>No medical advice.</strong> Nothing in the Service is
          medical advice. Outputs are not diagnostics, are not approved by
          any regulator, and must not be used to make patient-care
          decisions.
        </li>
        <li>
          <strong>Models can hallucinate.</strong> Confidence scores (pLDDT,
          ipTM, ipSAE, etc.) correlate with quality but do not guarantee it.
          High scores can be wrong.
        </li>
        <li>
          <strong>Benchmarks describe past results.</strong> Benchmark
          metrics are point-in-time estimates on specific targets and are
          not promises of future performance on your target.
        </li>
        <li>
          <strong>Third-party tools change.</strong> Underlying models may
          be updated, deprecated, or licensed differently. We will give
          reasonable notice when we can.
        </li>
      </ul>
      <p>
        Nothing in this section limits any warranty that cannot be
        disclaimed under applicable law.
      </p>

      <h2>10. Limitation of liability</h2>
      <p>
        <strong>TO THE MAXIMUM EXTENT PERMITTED BY LAW</strong>:
      </p>
      <ul>
        <li>
          Neither party will be liable for any{" "}
          <strong>
            indirect, incidental, special, consequential, exemplary, or
            punitive damages
          </strong>
          , or for{" "}
          <strong>
            lost profits, lost revenue, lost data, or business interruption
          </strong>
          , even if advised of the possibility.
        </li>
        <li>
          Each party&apos;s <strong>aggregate liability</strong> arising out
          of or related to these Terms or the Service is capped at the{" "}
          <strong>
            greater of (a) USD $100 or (b) the fees you paid us in the 12
            months preceding the event giving rise to the claim
          </strong>
          .
        </li>
      </ul>
      <p>
        These caps do <strong>not</strong> apply to: (i) your breach of §4
        (Acceptable Use) or §6 (IP); (ii) your payment obligations; (iii)
        either party&apos;s indemnification obligations; or (iv) liability
        that cannot be limited under applicable law (gross negligence,
        willful misconduct, fraud, death, or personal injury where
        applicable).
      </p>

      <h2>11. Indemnification</h2>
      <h3>11.1 By you</h3>
      <p>
        You will defend, indemnify, and hold harmless Paper Crane and its
        officers, directors, employees, and agents from any third-party
        claim arising out of (a) your Customer Content, (b) your use of the
        Service in violation of these Terms or applicable law, (c) your
        violation of §4, or (d) your wet-lab, clinical, or commercial use of
        generated Designs.
      </p>
      <h3>11.2 By us</h3>
      <p>
        We will defend you from any third-party claim alleging that the{" "}
        <strong>
          Service itself, as provided by us and used in accordance with these
          Terms
        </strong>
        , infringes a U.S. patent, copyright, or trademark, and we will pay
        damages and costs finally awarded against you for that claim. This
        obligation does not apply to claims arising from (i) your Customer
        Content, (ii) your combination of the Service with other products or
        processes, (iii) modifications you make, or (iv) your use of a
        deprecated version after we provided a non-infringing replacement.
      </p>
      <p>
        This §11.2 states our entire liability for IP infringement claims.
      </p>

      <h2>12. Term, suspension, and termination</h2>
      <p>
        These Terms apply from the moment you first use the Service and
        continue until your Account is terminated.
      </p>
      <p>
        You can terminate at any time by canceling your subscription and
        deleting your Account. We can terminate (a) for convenience on 30
        days&apos; written notice for free-tier Accounts, (b) for material
        breach not cured within 15 days of notice, or (c) immediately for §4
        violations, non-payment beyond 30 days, or insolvency events.
      </p>
      <p>
        We may <strong>suspend</strong> the Service immediately without
        notice if we reasonably believe continued operation would cause us
        legal exposure, security risk, or harm to others.
      </p>
      <p>
        On termination: (i) your access ends, (ii) outstanding fees become
        immediately due, (iii) we will make Customer Content available for
        export for 30 days under the retention rules of your tier, after
        which we may delete it, and (iv) §§4–6, 8–11, 13, and 15 survive.
      </p>

      <h2>13. Governing law and disputes</h2>
      <p>
        These Terms are governed by the laws of the{" "}
        <strong>State of Delaware</strong>, USA, without regard to
        conflict-of-laws rules. The U.N. Convention on Contracts for the
        International Sale of Goods does not apply.
      </p>
      <p>
        <strong>Informal resolution.</strong> Before filing anything, send a
        written description of the dispute to legal@papercrane.bio. Both
        parties agree to negotiate in good faith for 30 days.
      </p>
      <p>
        <strong>Arbitration.</strong> Any unresolved dispute, except as
        carved out below, will be resolved by binding individual
        arbitration administered by <strong>JAMS</strong> under its
        Streamlined Rules, in <strong>San Francisco, California</strong>,
        in English, before a single arbitrator. Judgment on the award may
        be entered in any court of competent jurisdiction.
      </p>
      <p>
        <strong>Carve-outs.</strong> Either party may (a) bring a claim in
        small-claims court for claims that qualify, or (b) seek injunctive
        or equitable relief in any court of competent jurisdiction to
        protect intellectual property, confidentiality, or §4.
      </p>
      <p>
        <strong>No class actions.</strong> You and we agree to bring claims
        only in an individual capacity, not as a class member, class
        representative, or in a private-attorney-general action. If this
        clause is unenforceable for a particular claim, that claim must be
        brought in the state or federal courts in{" "}
        <strong>Wilmington, Delaware</strong>, and both parties consent to
        personal jurisdiction there.
      </p>

      <h2>14. Export, sanctions, and government users</h2>
      <p>
        You represent that you are not located in, and will not use the
        Service from, a country subject to a comprehensive U.S. embargo,
        and that you are not on any U.S. government denied-party list (OFAC
        SDN, BIS Entity List, etc.). You will not export, re-export, or
        transfer the Service or generated Designs in violation of U.S. or
        other applicable export-control laws.
      </p>

      <h2>15. Miscellaneous</h2>
      <ul>
        <li>
          <strong>Entire agreement.</strong> These Terms, the Privacy
          Policy, the Acceptable Use Policy, and any Order Form are the
          entire agreement between us regarding the Service.
        </li>
        <li>
          <strong>Changes.</strong> We may update these Terms by posting a
          new version with a new Effective Date and, for material changes,
          giving you 30 days&apos; notice (in-app, email, or both).
          Continued use after the effective date is acceptance.
        </li>
        <li>
          <strong>Assignment.</strong> You may not assign these Terms
          without our written consent, except to a successor in a merger or
          acquisition that is not a competitor of ours.
        </li>
        <li>
          <strong>Force majeure.</strong> Neither party is liable for delays
          caused by events beyond reasonable control. Payment obligations
          are not excused.
        </li>
        <li>
          <strong>Notices.</strong> Legal notices to us must go to
          legal@papercrane.bio with a copy to Paper Crane, Inc., Atlanta,
          GA, USA. Notices to you go to your Account email.
        </li>
        <li>
          <strong>Severability.</strong> If any clause is unenforceable, the
          rest stays in effect, and the unenforceable clause is reformed to
          the minimum extent needed.
        </li>
        <li>
          <strong>No waiver.</strong> Failure to enforce a right is not a
          waiver of it.
        </li>
        <li>
          <strong>Independent contractors.</strong> No agency, partnership,
          joint venture, or employment is created.
        </li>
      </ul>

      <h2>16. Contact</h2>
      <ul>
        <li>
          General:{" "}
          <a href="mailto:hello@papercrane.bio" className="underline">
            hello@papercrane.bio
          </a>
        </li>
        <li>
          Legal:{" "}
          <a href="mailto:legal@papercrane.bio" className="underline">
            legal@papercrane.bio
          </a>
        </li>
        <li>
          Security:{" "}
          <a href="mailto:security@papercrane.bio" className="underline">
            security@papercrane.bio
          </a>
        </li>
        <li>
          Privacy:{" "}
          <a href="mailto:privacy@papercrane.bio" className="underline">
            privacy@papercrane.bio
          </a>
        </li>
        <li>
          Biosecurity:{" "}
          <a href="mailto:biosecurity@papercrane.bio" className="underline">
            biosecurity@papercrane.bio
          </a>
        </li>
        <li>
          DMCA:{" "}
          <a href="mailto:dmca@papercrane.bio" className="underline">
            dmca@papercrane.bio
          </a>
        </li>
      </ul>
      <p className="text-graphite text-[14px]">
        Paper Crane, Inc. · Delaware C-Corp · Operating from Atlanta, GA →
        San Francisco, CA.
      </p>
    </LegalLayout>
  );
}
