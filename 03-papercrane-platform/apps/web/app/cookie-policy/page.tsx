import type { Metadata } from "next";
import Link from "next/link";
import { LegalLayout } from "@/components/legal/LegalLayout";
import { pageMetadata } from "@/lib/metadata";

const TITLE = "Cookie Policy";
const DESCRIPTION =
  "Paper Crane Cookie Policy. The full list of cookies and similar storage we use, why, and how to manage your choices.";

export const metadata: Metadata = pageMetadata({
  title: TITLE,
  description: DESCRIPTION,
  path: "/cookie-policy",
  ogTitle: "Cookies",
  ogDesc: "Essential cookies + privacy-friendly analytics. No ad trackers.",
});

export default function CookiePolicyPage() {
  return (
    <LegalLayout
      eyebrow="§ Legal · Cookies"
      title="Cookie Policy."
      effective="2026-04-27"
      intro={
        <>
          What cookies and similar storage we use on{" "}
          <strong className="text-ink">papercrane.bio</strong> and{" "}
          <strong className="text-ink">app.papercrane.bio</strong>, why we
          use them, and how to manage them. This page supplements our{" "}
          <Link href="/privacy" className="underline">
            Privacy Policy
          </Link>
          .
        </>
      }
    >
      <h2>What&apos;s a cookie, briefly</h2>
      <p>
        A cookie is a small text file a site stores on your device.
        &quot;Similar technologies&quot; include <code>localStorage</code>,{" "}
        <code>sessionStorage</code>, <code>IndexedDB</code>, and pixels.
        Throughout this page, &quot;cookie&quot; covers all of them.
      </p>
      <p>Cookies fall into two flavors:</p>
      <ul>
        <li>
          <strong>Strictly necessary</strong> — required for the Service to
          work. You can&apos;t usefully turn these off.
        </li>
        <li>
          <strong>Optional</strong> — analytics and preferences. You can
          turn these off without breaking the Service.
        </li>
      </ul>
      <p>
        We do <strong>not</strong> use cookies for advertising, retargeting,
        or cross-site tracking.
      </p>

      <h2>What we set</h2>
      <div className="overflow-x-auto">
        <table className="w-full text-[14px] border-collapse">
          <thead>
            <tr className="border-b border-ink/15 text-left">
              <th className="py-2 pr-4 font-medium text-ink">Name</th>
              <th className="py-2 pr-4 font-medium text-ink">Type</th>
              <th className="py-2 pr-4 font-medium text-ink">Purpose</th>
              <th className="py-2 pr-4 font-medium text-ink">Set by</th>
              <th className="py-2 font-medium text-ink">Expiry</th>
            </tr>
          </thead>
          <tbody className="text-graphite align-top">
            <tr className="border-b border-ink/5">
              <td className="py-2 pr-4 font-mono text-[12px]">sb-access-token</td>
              <td className="py-2 pr-4">Strictly necessary</td>
              <td className="py-2 pr-4">Authenticated session</td>
              <td className="py-2 pr-4">Supabase / us</td>
              <td className="py-2">1 hour, refreshed</td>
            </tr>
            <tr className="border-b border-ink/5">
              <td className="py-2 pr-4 font-mono text-[12px]">sb-refresh-token</td>
              <td className="py-2 pr-4">Strictly necessary</td>
              <td className="py-2 pr-4">Refresh access token</td>
              <td className="py-2 pr-4">Supabase / us</td>
              <td className="py-2">30 days</td>
            </tr>
            <tr className="border-b border-ink/5">
              <td className="py-2 pr-4 font-mono text-[12px]">pc_csrf</td>
              <td className="py-2 pr-4">Strictly necessary</td>
              <td className="py-2 pr-4">CSRF protection</td>
              <td className="py-2 pr-4">us</td>
              <td className="py-2">Session</td>
            </tr>
            <tr className="border-b border-ink/5">
              <td className="py-2 pr-4 font-mono text-[12px]">pc_consent</td>
              <td className="py-2 pr-4">Strictly necessary</td>
              <td className="py-2 pr-4">Records cookie choices</td>
              <td className="py-2 pr-4">us (localStorage)</td>
              <td className="py-2">1 year</td>
            </tr>
            <tr className="border-b border-ink/5">
              <td className="py-2 pr-4 font-mono text-[12px]">pc_theme</td>
              <td className="py-2 pr-4">Preference</td>
              <td className="py-2 pr-4">Light/dark theme</td>
              <td className="py-2 pr-4">us (localStorage)</td>
              <td className="py-2">1 year</td>
            </tr>
            <tr className="border-b border-ink/5">
              <td className="py-2 pr-4 font-mono text-[12px]">pc_dismissed_banners</td>
              <td className="py-2 pr-4">Preference</td>
              <td className="py-2 pr-4">Dismissed in-app banners</td>
              <td className="py-2 pr-4">us (localStorage)</td>
              <td className="py-2">1 year</td>
            </tr>
            <tr>
              <td className="py-2 pr-4 font-mono text-[12px]">Plausible event ping</td>
              <td className="py-2 pr-4">Analytics (cookieless)</td>
              <td className="py-2 pr-4">Aggregated page-view counts</td>
              <td className="py-2 pr-4">Plausible</td>
              <td className="py-2">none (cookieless)</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p>
        We don&apos;t set Google Analytics, Meta Pixel, TikTok Pixel,
        LinkedIn Insight, or any other ad-network tag. We don&apos;t use
        server-side advertising IDs.
      </p>

      <h2>Third-party cookies</h2>
      <ul>
        <li>
          <strong>Cloudflare</strong> may set a <code>__cf_bm</code> cookie
          for bot management. Strictly necessary, dropped after a short
          session.
        </li>
        <li>
          <strong>Stripe</strong> (only on the checkout/billing pages) sets
          a session cookie for fraud detection while you&apos;re paying.
          Not used elsewhere.
        </li>
        <li>
          <strong>Plausible</strong> does not set cookies. It uses
          cookieless event pings only.
        </li>
      </ul>
      <p>
        We do not embed YouTube, Vimeo, Twitter, or other social widgets
        that drop cookies on production pages where consent has not been
        granted.
      </p>

      <h2>Your choices</h2>
      <ol>
        <li>
          The <strong>cookie banner</strong> on your first visit. Choose{" "}
          <em>Accept all</em> (analytics on) or <em>Essential only</em>{" "}
          (analytics off).
        </li>
        <li>
          The{" "}
          <Link href="/privacy-choices" className="underline">
            Privacy choices
          </Link>{" "}
          page — change your decision any time.
        </li>
        <li>
          Your <strong>browser settings</strong>. Most browsers let you
          block or delete cookies. If you block strictly-necessary cookies,
          the Service will not work.
        </li>
      </ol>
      <p>
        Inside the logged-in dashboard at app.papercrane.bio we don&apos;t
        show the banner because the only cookies we set there are
        strictly necessary for auth and CSRF; analytics are not enabled in
        the app by default. Your dashboard preferences are stored in{" "}
        <code>localStorage</code> on your device only.
      </p>

      <h2>Do Not Track and Global Privacy Control</h2>
      <p>
        We honor the <strong>Global Privacy Control (GPC)</strong> signal as
        an opt-out from analytics, in addition to whatever you choose in
        the banner. We treat a clear GPC signal as if you selected
        &quot;Essential only&quot;.
      </p>
      <p>
        We do not separately respond to legacy DNT headers, which are
        ambiguous. GPC supersedes.
      </p>

      <h2>Changes</h2>
      <p>
        If we add or remove a cookie or change a purpose, we&apos;ll update
        this page and bump the Effective date. For material changes (new
        categories, new vendors), we&apos;ll re-prompt the cookie banner
        so you can re-decide.
      </p>

      <h2>Contact</h2>
      <p>
        Questions about cookies? Email{" "}
        <a href="mailto:privacy@papercrane.bio" className="underline">
          privacy@papercrane.bio
        </a>
        .
      </p>
    </LegalLayout>
  );
}
