# Paper Crane — Cookie Policy

**Effective: 2026-04-27** · **Last updated: 2026-04-27**

This Cookie Policy explains what cookies and similar storage we use on **papercrane.bio** and **app.papercrane.bio**, why we use them, and how you can manage them. It supplements our [Privacy Policy](/privacy).

---

## What's a cookie, briefly

A cookie is a small text file a site stores on your device. "Similar technologies" include `localStorage`, `sessionStorage`, `IndexedDB`, and pixels. Throughout this page, "cookie" covers all of them unless we say otherwise.

Cookies fall into two flavors:

- **Strictly necessary** — required for the Service to work. You can't usefully turn these off.
- **Optional** — analytics and preferences. You can turn these off without breaking the Service.

We do **not** use cookies for advertising, retargeting, or cross-site tracking.

---

## What we set

| Name | Type | Purpose | Set by | Expiry |
|---|---|---|---|---|
| `sb-access-token` | Strictly necessary | Authenticated session (Supabase) | Supabase / us | 1 hour, refreshed |
| `sb-refresh-token` | Strictly necessary | Refresh the access token | Supabase / us | 30 days |
| `pc_csrf` | Strictly necessary | CSRF protection on form submits and API mutations | us | Session |
| `pc_consent` | Strictly necessary | Records your cookie choices so we don't re-prompt | us (`localStorage`) | 1 year |
| `pc_theme` | Preference | Light/dark theme preference | us (`localStorage`) | 1 year |
| `pc_dismissed_banners` | Preference | Which in-app banners you've dismissed | us (`localStorage`) | 1 year |
| Plausible event ping | Analytics (cookieless) | Aggregated page-view counts for product analytics | Plausible | none (cookieless) |

We don't set Google Analytics, Meta Pixel, TikTok Pixel, LinkedIn Insight, or any other ad-network tag. We don't use server-side advertising IDs.

---

## Third-party cookies

The third parties that touch our pages are:

- **Cloudflare** — may set a `__cf_bm` cookie for bot management. This is a strictly-necessary cookie used for security and is automatically dropped after a short session.
- **Stripe** (only on the checkout/billing pages) — sets a session cookie for fraud detection while you're paying. Not used elsewhere.
- **Plausible** — does **not** set cookies. It uses cookieless event pings only.

We do not embed YouTube, Vimeo, Twitter, or other social widgets that drop cookies, on production pages where consent has not been granted.

---

## Your choices

You can manage cookies in three places:

1. **The cookie banner** — shown on your first visit to papercrane.bio. Choose **Accept all** (analytics on) or **Essential only** (analytics off).
2. **The Privacy choices page** at **/privacy-choices** — change your decision any time.
3. **Your browser settings** — most browsers let you block or delete cookies. If you block strictly-necessary cookies, the Service will not work.

Inside the logged-in dashboard at app.papercrane.bio, we don't show the banner because the only cookies we set there are strictly necessary for auth and CSRF; analytics are not enabled in the app by default. Your dashboard preferences are stored in `localStorage` on your device only.

---

## Do Not Track and Global Privacy Control

We honor the **Global Privacy Control (GPC)** signal as an opt-out from analytics, in addition to whatever you choose in the banner. We treat a clear GPC signal as if you selected "Essential only".

We do not separately respond to legacy DNT headers, which are ambiguous. GPC supersedes.

---

## Changes

If we add or remove a cookie or change a purpose, we'll update this page and bump the Last updated date. For material changes (new categories, new vendors), we'll re-prompt the cookie banner so you can re-decide.

---

## Contact

Questions about cookies? Email **privacy@papercrane.bio**.
