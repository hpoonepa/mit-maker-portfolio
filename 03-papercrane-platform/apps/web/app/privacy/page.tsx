import type { Metadata } from "next";
import Link from "next/link";
import { LegalLayout } from "@/components/legal/LegalLayout";
import { pageMetadata } from "@/lib/metadata";

const TITLE = "Privacy Policy";
const DESCRIPTION =
  "Paper Crane Privacy Policy. What we collect, why, our subprocessors, retention by tier, and how to access, correct, or delete your data.";

export const metadata: Metadata = pageMetadata({
  title: TITLE,
  description: DESCRIPTION,
  path: "/privacy",
  ogTitle: "Privacy",
  ogDesc: "What we collect. What we never do.",
});

export default function PrivacyPage() {
  return (
    <LegalLayout
      eyebrow="§ Legal · Privacy"
      title="Privacy Policy."
      effective="2026-04-27"
      intro={
        <>
          How <strong className="text-ink">Paper Crane, Inc.</strong>{" "}
          collects, uses, shares, and retains personal information when you
          use papercrane.bio, app.papercrane.bio, our APIs, our CLI, or any
          related service. The Quick Read below covers the gist; the rest is
          the long version, and the long version controls.
        </>
      }
    >
      <h2>Quick Read</h2>
      <ul>
        <li>
          We collect what we need to run the Service:{" "}
          <strong>account info</strong> (email, name, org), your{" "}
          <strong>job inputs and outputs</strong>, and{" "}
          <strong>operational telemetry</strong> (timings, error codes, IP,
          browser).
        </li>
        <li>
          We do <strong>not</strong> read your sequences or designs to train
          foundation models without your explicit, separately-given opt-in.
        </li>
        <li>
          We use a small, named list of <strong>subprocessors</strong>{" "}
          (Supabase, Stripe, Modal, Resend, Vercel, Cloudflare, Sentry) for
          hosting, payments, compute, email, and observability.
        </li>
        <li>
          You have <strong>rights</strong> to access, correct, delete, port,
          and (for EU/UK/Brazil/etc.) object to processing. Email{" "}
          <strong>privacy@papercrane.bio</strong> to exercise them.
        </li>
        <li>
          We retain your job data for <strong>7 days (Free)</strong>,{" "}
          <strong>90 days (Pro)</strong>, or{" "}
          <strong>365 days (Frontier)</strong> unless you delete it sooner or
          your Order Form sets a different period.
        </li>
        <li>
          We use essential cookies and{" "}
          <strong>privacy-friendly analytics (Plausible)</strong> that does
          not set cross-site tracking cookies and does not collect PII. See
          our{" "}
          <Link href="/cookie-policy" className="underline">
            Cookie Policy
          </Link>
          .
        </li>
        <li>
          We don&apos;t sell your personal information. We don&apos;t share
          it with advertisers.
        </li>
      </ul>

      <h2>1. Who we are and how to reach us</h2>
      <p>
        <strong>Controller:</strong> Paper Crane, Inc., a Delaware
        corporation, operating from Atlanta, GA, USA.
      </p>
      <ul>
        <li>
          Privacy contact:{" "}
          <a href="mailto:privacy@papercrane.bio" className="underline">
            privacy@papercrane.bio
          </a>
        </li>
        <li>
          Security contact:{" "}
          <a href="mailto:security@papercrane.bio" className="underline">
            security@papercrane.bio
          </a>
        </li>
        <li>
          General contact:{" "}
          <a href="mailto:hello@papercrane.bio" className="underline">
            hello@papercrane.bio
          </a>
        </li>
      </ul>
      <p>
        If you are in the EU/EEA or the UK, you can also contact our
        representative at the same address until we appoint a local Article
        27 / UK GDPR representative; we will publish that representative&apos;s
        contact details here when appointed.
      </p>

      <h2>2. What we collect</h2>
      <h3>2.1 Information you provide</h3>
      <ul>
        <li>
          <strong>Account info.</strong> Email, name, organization, password
          hash (we use bcrypt/argon2 via Supabase Auth and never see your
          plaintext password), profile picture if you set one.
        </li>
        <li>
          <strong>Billing info.</strong> Plan, billing email, billing
          address, last 4 digits of card and card brand.{" "}
          <strong>
            Full card numbers are handled by Stripe and never touch our
            servers.
          </strong>
        </li>
        <li>
          <strong>Customer Content.</strong> Sequences, target structures
          (PDB IDs and uploaded files), hotspot definitions, parameter sets,
          design outputs, notes, and any files you attach to a job or
          design.
        </li>
        <li>
          <strong>Communications.</strong> Support emails, in-app messages,
          survey responses, scheduling, and anything you send to our team.
        </li>
      </ul>
      <h3>2.2 Information generated by your use</h3>
      <ul>
        <li>
          <strong>Job logs.</strong> Tool name and version, queue time, GPU
          type, duration, success/failure code, error messages, and resource
          usage. These power the dashboard and the public benchmark.
        </li>
        <li>
          <strong>Designs as inputs/outputs.</strong> Hashes, paths, metric
          scores (pLDDT, ipTM, ipSAE, etc.), and links between them. We
          treat the contents of designs as Customer Content (see §2.1).
        </li>
        <li>
          <strong>Auth and session events.</strong> Sign-ins, sign-outs,
          password resets, MFA events, API key issuance and revocation.
        </li>
        <li>
          <strong>Device and connection.</strong> IP address, user-agent,
          approximate region (city-level, derived from IP), referrer URL,
          time zone.
        </li>
        <li>
          <strong>Product analytics.</strong> Page views, navigation events,
          feature usage. We use <strong>Plausible Analytics</strong>, which
          is privacy-friendly, EU-hosted, cookieless, and does not collect
          personal information or set cross-site identifiers.
        </li>
      </ul>
      <h3>2.3 Information from third parties</h3>
      <ul>
        <li>
          <strong>OAuth providers</strong> (Google, GitHub, ORCID if you
          choose them) give us your email, name, avatar, and a stable user
          ID. We do not get your password.
        </li>
        <li>
          <strong>Stripe</strong> sends us payment status, subscription
          state, invoice IDs, and the metadata above.
        </li>
        <li>
          <strong>Email-deliverability vendors</strong> (e.g., Resend) tell
          us whether our messages were delivered, bounced, or marked as
          spam.
        </li>
      </ul>
      <p>
        We do <strong>not</strong> buy data from data brokers and we do{" "}
        <strong>not</strong> enrich your profile with marketing data.
      </p>

      <h2>3. Why we use it (legal bases)</h2>
      <div className="overflow-x-auto">
        <table className="w-full text-[14px] border-collapse">
          <thead>
            <tr className="border-b border-ink/15 text-left">
              <th className="py-2 pr-4 font-medium text-ink">Purpose</th>
              <th className="py-2 pr-4 font-medium text-ink">Categories</th>
              <th className="py-2 font-medium text-ink">Lawful basis (GDPR)</th>
            </tr>
          </thead>
          <tbody className="text-graphite">
            <tr className="border-b border-ink/5 align-top">
              <td className="py-2 pr-4">Provide the Service</td>
              <td className="py-2 pr-4">Account, Customer Content, Job logs</td>
              <td className="py-2"><strong>Contract</strong> (Art. 6(1)(b))</td>
            </tr>
            <tr className="border-b border-ink/5 align-top">
              <td className="py-2 pr-4">Bill you and prevent fraud</td>
              <td className="py-2 pr-4">Billing, IP, device</td>
              <td className="py-2">Contract + legitimate interest (b, f)</td>
            </tr>
            <tr className="border-b border-ink/5 align-top">
              <td className="py-2 pr-4">Secure the Service</td>
              <td className="py-2 pr-4">IP, device, auth events, job logs</td>
              <td className="py-2">Legitimate interest + legal obligation (c, f)</td>
            </tr>
            <tr className="border-b border-ink/5 align-top">
              <td className="py-2 pr-4">Improve via aggregated telemetry</td>
              <td className="py-2 pr-4">Aggregated job logs, error patterns</td>
              <td className="py-2">Legitimate interest (f)</td>
            </tr>
            <tr className="border-b border-ink/5 align-top">
              <td className="py-2 pr-4">Transactional email</td>
              <td className="py-2 pr-4">Email, name, job state</td>
              <td className="py-2">Contract (b)</td>
            </tr>
            <tr className="border-b border-ink/5 align-top">
              <td className="py-2 pr-4">Marketing email</td>
              <td className="py-2 pr-4">Email, name</td>
              <td className="py-2">Consent (a) — unsubscribe any time</td>
            </tr>
            <tr className="border-b border-ink/5 align-top">
              <td className="py-2 pr-4">Comply with biosecurity / export law</td>
              <td className="py-2 pr-4">Account, Customer Content metadata</td>
              <td className="py-2">Legal obligation (c)</td>
            </tr>
            <tr className="align-top">
              <td className="py-2 pr-4">Defend legal claims</td>
              <td className="py-2 pr-4">As reasonably necessary</td>
              <td className="py-2">Legitimate interest (f)</td>
            </tr>
          </tbody>
        </table>
      </div>

      <h2>4. What we DO NOT do</h2>
      <ul>
        <li>
          We do <strong>not</strong> sell your personal information. We do
          not &quot;share&quot; it for cross-context behavioral advertising
          under the CCPA/CPRA.
        </li>
        <li>
          We do <strong>not</strong> read your sequences, structures, or
          designs to train foundation models, fine-tune model weights, or
          build new tools, <strong>unless you explicitly opt in</strong>{" "}
          through a labeled contributor program with a published data-use
          agreement.
        </li>
        <li>
          We do <strong>not</strong> make automated decisions that produce
          legal or similarly significant effects on you.
        </li>
        <li>
          We do <strong>not</strong> use your Customer Content to advertise
          to you.
        </li>
        <li>
          We do <strong>not</strong> share Customer Content with other
          Paper Crane customers, ever, except where you&apos;ve explicitly
          chosen to publish or share it.
        </li>
      </ul>

      <h2>5. Subprocessors</h2>
      <p>
        We rely on a small set of subprocessors. Each is bound by a written
        data-processing agreement with appropriate safeguards (SCCs for EU
        transfers, where relevant).
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-[14px] border-collapse">
          <thead>
            <tr className="border-b border-ink/15 text-left">
              <th className="py-2 pr-4 font-medium text-ink">Subprocessor</th>
              <th className="py-2 pr-4 font-medium text-ink">Purpose</th>
              <th className="py-2 pr-4 font-medium text-ink">What it gets</th>
              <th className="py-2 font-medium text-ink">Region</th>
            </tr>
          </thead>
          <tbody className="text-graphite">
            <tr className="border-b border-ink/5 align-top">
              <td className="py-2 pr-4 font-medium text-ink">Supabase</td>
              <td className="py-2 pr-4">Postgres, auth, object storage</td>
              <td className="py-2 pr-4">Account info, Customer Content, sessions</td>
              <td className="py-2">US (multi-region)</td>
            </tr>
            <tr className="border-b border-ink/5 align-top">
              <td className="py-2 pr-4 font-medium text-ink">Stripe</td>
              <td className="py-2 pr-4">Payments, subscriptions, invoices</td>
              <td className="py-2 pr-4">Billing email, name, payment method, plan</td>
              <td className="py-2">US/EU</td>
            </tr>
            <tr className="border-b border-ink/5 align-top">
              <td className="py-2 pr-4 font-medium text-ink">Modal</td>
              <td className="py-2 pr-4">Serverless GPU compute</td>
              <td className="py-2 pr-4">Customer Content during job execution, job logs</td>
              <td className="py-2">US</td>
            </tr>
            <tr className="border-b border-ink/5 align-top">
              <td className="py-2 pr-4 font-medium text-ink">Vast.ai (where used)</td>
              <td className="py-2 pr-4">Spot GPU compute</td>
              <td className="py-2 pr-4">Customer Content during job execution, job logs</td>
              <td className="py-2">US/EU</td>
            </tr>
            <tr className="border-b border-ink/5 align-top">
              <td className="py-2 pr-4 font-medium text-ink">Resend</td>
              <td className="py-2 pr-4">Transactional + newsletter email</td>
              <td className="py-2 pr-4">Email address, name, message content</td>
              <td className="py-2">US/EU</td>
            </tr>
            <tr className="border-b border-ink/5 align-top">
              <td className="py-2 pr-4 font-medium text-ink">Vercel</td>
              <td className="py-2 pr-4">Web/API hosting, edge runtime</td>
              <td className="py-2 pr-4">IP, user-agent, request metadata</td>
              <td className="py-2">Global edge</td>
            </tr>
            <tr className="border-b border-ink/5 align-top">
              <td className="py-2 pr-4 font-medium text-ink">Cloudflare</td>
              <td className="py-2 pr-4">DNS, CDN, DDoS, WAF</td>
              <td className="py-2 pr-4">IP, user-agent, request metadata</td>
              <td className="py-2">Global edge</td>
            </tr>
            <tr className="border-b border-ink/5 align-top">
              <td className="py-2 pr-4 font-medium text-ink">Sentry</td>
              <td className="py-2 pr-4">Error + performance monitoring</td>
              <td className="py-2 pr-4">Error stacks, request URL, pseudonymous user ID</td>
              <td className="py-2">US/EU</td>
            </tr>
            <tr className="align-top">
              <td className="py-2 pr-4 font-medium text-ink">Plausible</td>
              <td className="py-2 pr-4">Privacy-friendly site analytics</td>
              <td className="py-2 pr-4">Aggregated, cookieless event counts; no PII</td>
              <td className="py-2">EU</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p>
        If we add or change a subprocessor, we will update this table and,
        for paid customers, give 30 days&apos; notice via email or in-app
        banner before the change takes effect, so you can object.
      </p>

      <h2>6. Cookies, analytics, and tracking</h2>
      <p>
        We use a minimal set of cookies and similar technologies. The full
        list and purpose is in our{" "}
        <Link href="/cookie-policy" className="underline">
          Cookie Policy
        </Link>
        . In summary:
      </p>
      <ul>
        <li>
          <strong>Strictly necessary cookies</strong> — auth/session, CSRF,
          load balancing. Required to use the Service.
        </li>
        <li>
          <strong>Privacy-friendly analytics</strong> — Plausible.
          Cookieless, no cross-site tracking, no PII. Aggregated only.
        </li>
        <li>
          <strong>Preferences</strong> — your dashboard layout, theme,
          accepted cookie banner state. Stored in <code>localStorage</code>,
          not transmitted.
        </li>
      </ul>
      <p>
        We do <strong>not</strong> use Google Analytics, Meta Pixel, TikTok
        Pixel, or any third-party advertising cookies.
      </p>
      <p>
        You can manage your preferences any time at{" "}
        <Link href="/privacy-choices" className="underline">
          /privacy-choices
        </Link>{" "}
        or via the cookie banner that appears on your first visit.
      </p>

      <h2>7. International transfers</h2>
      <p>
        Our primary infrastructure is in the United States. If you access
        the Service from outside the U.S., your information will be
        transferred to and processed in the U.S. and other countries where
        our subprocessors operate. We rely on:
      </p>
      <ul>
        <li>
          <strong>EU Standard Contractual Clauses (2021/914)</strong> with
          each subprocessor receiving personal data from those regions.
        </li>
        <li>
          The <strong>EU-U.S. Data Privacy Framework</strong> for
          subprocessors that have certified to it.
        </li>
        <li>
          Supplementary measures where appropriate (encryption in transit,
          encryption at rest, access controls).
        </li>
      </ul>
      <p>
        You can request a copy of the relevant SCCs by emailing
        privacy@papercrane.bio.
      </p>

      <h2>8. Retention</h2>
      <div className="overflow-x-auto">
        <table className="w-full text-[14px] border-collapse">
          <thead>
            <tr className="border-b border-ink/15 text-left">
              <th className="py-2 pr-4 font-medium text-ink">Data</th>
              <th className="py-2 font-medium text-ink">Retention</th>
            </tr>
          </thead>
          <tbody className="text-graphite">
            <tr className="border-b border-ink/5">
              <td className="py-2 pr-4">Account info</td>
              <td className="py-2">Active account + 30 days after deletion</td>
            </tr>
            <tr className="border-b border-ink/5">
              <td className="py-2 pr-4">Customer Content (Free tier)</td>
              <td className="py-2"><strong>7 days</strong> rolling, then auto-deleted</td>
            </tr>
            <tr className="border-b border-ink/5">
              <td className="py-2 pr-4">Customer Content (Pro tier)</td>
              <td className="py-2"><strong>90 days</strong> rolling</td>
            </tr>
            <tr className="border-b border-ink/5">
              <td className="py-2 pr-4">Customer Content (Frontier tier)</td>
              <td className="py-2"><strong>365 days</strong> rolling, or per Order Form</td>
            </tr>
            <tr className="border-b border-ink/5">
              <td className="py-2 pr-4">Job logs (operational)</td>
              <td className="py-2">90 days</td>
            </tr>
            <tr className="border-b border-ink/5">
              <td className="py-2 pr-4">Aggregated, anonymized benchmark data</td>
              <td className="py-2">Retained indefinitely (no PII)</td>
            </tr>
            <tr className="border-b border-ink/5">
              <td className="py-2 pr-4">Billing and invoice records</td>
              <td className="py-2">7 years (tax/audit)</td>
            </tr>
            <tr className="border-b border-ink/5">
              <td className="py-2 pr-4">Support tickets</td>
              <td className="py-2">2 years after closure</td>
            </tr>
            <tr className="border-b border-ink/5">
              <td className="py-2 pr-4">Security/audit logs</td>
              <td className="py-2">1 year</td>
            </tr>
            <tr>
              <td className="py-2 pr-4">Backup snapshots</td>
              <td className="py-2">30 days, then overwritten</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p>
        Deletion requests under §9 will accelerate these timelines, subject
        to legal-hold exceptions.
      </p>

      <h2>9. Your rights</h2>
      <p>
        Depending on where you live, you have some or all of the following
        rights. We honor all of them globally as a baseline.
      </p>
      <ul>
        <li>
          <strong>Access</strong> — get a copy of the personal information
          we hold about you.
        </li>
        <li>
          <strong>Correction</strong> — fix anything inaccurate.
        </li>
        <li>
          <strong>Deletion</strong> — ask us to delete your account and
          Customer Content. We will, except where retention is required by
          law (e.g., tax records).
        </li>
        <li>
          <strong>Portability</strong> — get a machine-readable export
          (JSON or CSV) of your account info, designs, and job history.
        </li>
        <li>
          <strong>Restriction / objection</strong> — ask us to stop or
          limit certain processing, particularly direct marketing and
          profiling.
        </li>
        <li>
          <strong>Withdraw consent</strong> — for any processing based on
          consent, withdraw it at any time without affecting prior lawful
          processing.
        </li>
        <li>
          <strong>Non-discrimination</strong> (CCPA/CPRA) — we won&apos;t
          discriminate against you for exercising your rights.
        </li>
        <li>
          <strong>Lodge a complaint</strong> — you can complain to your
          local data-protection authority. We&apos;d appreciate a chance to
          fix it first.
        </li>
      </ul>
      <p>
        To exercise any of these, email{" "}
        <strong>privacy@papercrane.bio</strong> from the email address on
        your Account, or use the in-app{" "}
        <Link href="/privacy-choices" className="underline">
          Privacy choices
        </Link>{" "}
        page. We respond within 30 days (extendable by 60 days for complex
        requests under GDPR Art. 12(3)).
      </p>

      <h2>10. Security</h2>
      <ul>
        <li>
          <strong>Encryption in transit</strong> (TLS 1.2+) for all
          traffic.
        </li>
        <li>
          <strong>Encryption at rest</strong> for our database and object
          storage (AES-256 via Supabase / Vercel KV / S3-compatible
          storage).
        </li>
        <li>
          <strong>Access controls</strong> — least-privilege IAM, MFA for
          engineering staff, audit logs.
        </li>
        <li>
          <strong>Network isolation</strong> — production traffic is
          firewalled; engineering access goes through a bastion or
          short-lived credentials.
        </li>
        <li>
          <strong>Vulnerability management</strong> — dependency scanning,
          periodic external penetration tests, a public security contact,
          and a coordinated-disclosure policy.
        </li>
        <li>
          <strong>Incident response</strong> — we will notify affected
          users and regulators within the timelines required by GDPR Art.
          33–34 and applicable U.S. state laws.
        </li>
      </ul>
      <p>
        We are not yet SOC 2 attested as of the Effective Date. We are
        working toward it. For our current security questionnaire, email
        security@papercrane.bio.
      </p>

      <h2>11. Children</h2>
      <p>
        The Service is not directed to children under 16. We do not
        knowingly collect personal information from children under 16. If
        you believe a child has provided us with personal information,
        email privacy@papercrane.bio and we will delete it.
      </p>

      <h2>12. Changes to this Policy</h2>
      <p>
        We may update this Policy. The Effective Date at the top reflects
        the most recent version. For material changes, we will notify
        Account holders by email and post a banner in-app at least 30 days
        before the change takes effect. Continued use after that date is
        acceptance of the updated Policy.
      </p>

      <h2>13. Region-specific addenda</h2>
      <h3>13.1 California (CCPA/CPRA)</h3>
      <p>
        The categories of personal information we have collected, the
        purposes for which they are used, and the categories of recipients
        are described in §§2, 3, and 5. We do <strong>not</strong> sell or
        share personal information. California residents have the rights
        listed in §9. To exercise rights, email privacy@papercrane.bio.
        Authorized agents may submit requests on your behalf with written
        authorization.
      </p>
      <h3>13.2 European Economic Area / United Kingdom / Switzerland</h3>
      <p>
        The data controller is Paper Crane, Inc. The legal bases for
        processing are listed in §3. Transfers outside the EEA are governed
        by the safeguards in §7. You have the right to lodge a complaint
        with your supervisory authority (e.g., the Irish DPC, the UK ICO,
        the Swiss FDPIC).
      </p>
      <h3>13.3 Brazil (LGPD)</h3>
      <p>
        Our processing of personal data of individuals located in Brazil
        follows the LGPD&apos;s requirements. Data-subject rights mirror
        §9.
      </p>

      <h2>14. Contact</h2>
      <ul>
        <li>
          Privacy:{" "}
          <a href="mailto:privacy@papercrane.bio" className="underline">
            privacy@papercrane.bio
          </a>
        </li>
        <li>
          Security:{" "}
          <a href="mailto:security@papercrane.bio" className="underline">
            security@papercrane.bio
          </a>
        </li>
        <li>
          General:{" "}
          <a href="mailto:hello@papercrane.bio" className="underline">
            hello@papercrane.bio
          </a>
        </li>
        <li>Mail: Paper Crane, Inc., Atlanta, GA, USA</li>
      </ul>
      <p className="text-graphite text-[14px]">
        Thanks for trusting us with your science.
      </p>
    </LegalLayout>
  );
}
