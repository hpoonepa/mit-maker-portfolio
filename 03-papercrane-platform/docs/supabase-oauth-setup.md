# Supabase Google OAuth — Setup

This wires "Continue with Google" on `/login` and `/signup` to your Supabase
project. The button is already coded (`OAuthButtons` + `lib/supabase/oauth.ts`)
and the callback handler at `apps/app/app/auth/callback/route.ts` exchanges the
PKCE code for a session. Only the provider credentials need to be plugged in.

Project ref: `uoadxpkjobhoaasiqrje`
Supabase callback URL: `https://uoadxpkjobhoaasiqrje.supabase.co/auth/v1/callback`

---

## 1. Create OAuth credentials in Google Cloud Console

1. Go to <https://console.cloud.google.com/> and select (or create) a project
   for Paper Crane.
2. **APIs & Services → OAuth consent screen**
   - User type: **External**
   - App name: `Paper Crane`
   - User support email: your email
   - Developer contact: your email
   - Scopes: leave default (`openid`, `email`, `profile`)
   - Save and continue. While the app is in *Testing* mode, add your own
     Google account under **Test users** so you can sign in.
3. **APIs & Services → Credentials → Create Credentials → OAuth client ID**
   - Application type: **Web application**
   - Name: `Paper Crane Web`
   - **Authorized JavaScript origins**:
     - `http://localhost:3002` (local dev — adjust if you run on a different port)
     - `https://app.papercrane.bio` (production — replace with your real prod
       domain when you ship)
   - **Authorized redirect URIs** (this one matters most):
     - `https://uoadxpkjobhoaasiqrje.supabase.co/auth/v1/callback`
   - Click **Create**. Copy the **Client ID** and **Client Secret**.

> Do NOT paste the client secret into the repo, `.env.local`, or chat. It only
> goes into the Supabase dashboard.

---

## 2. Enable Google in Supabase

1. Open <https://supabase.com/dashboard/project/uoadxpkjobhoaasiqrje>
2. **Authentication → Providers → Google**
3. Toggle **Enable Google provider** ON
4. Paste the **Client ID (for OAuth)** and **Client Secret (for OAuth)** from
   step 1.
5. Leave **Authorized Client IDs** empty (only needed for Google One Tap on
   mobile).
6. Click **Save**.

---

## 3. Confirm the Site URL & redirect allow-list

Still in the Supabase dashboard:

1. **Authentication → URL Configuration**
2. **Site URL**: `http://localhost:3002` for local dev. Switch to your prod URL
   (e.g. `https://app.papercrane.bio`) before deploying.
3. **Redirect URLs** — add both, one per line:
   - `http://localhost:3002/auth/callback`
   - `https://app.papercrane.bio/auth/callback` (or your prod domain)
4. Save.

Supabase will reject any `redirectTo` that isn't on this allow-list, so the
button will silently fail if you forget this step.

---

## 4. Test it

1. From the repo root: `pnpm --filter app dev` (or your usual dev command).
2. Visit <http://localhost:3002/login>.
3. Click **Continue with Google**.
4. Expected:
   1. Redirect to `accounts.google.com` consent screen.
   2. Pick your Google account, accept consent.
   3. Redirect back to
      `https://uoadxpkjobhoaasiqrje.supabase.co/auth/v1/callback?code=...`.
   4. Supabase redirects to `http://localhost:3002/auth/callback?code=...`.
   5. Our handler exchanges the code, sets cookies, and lands you on `/app`
      (or `/onboarding` if your account has no org yet).
5. If you see `?error=` on `/login`, the message comes from Supabase — common
   causes: redirect URL not on the allow-list, OAuth consent screen still in
   "needs verification" with your account not added as a test user, or wrong
   client secret.

---

## 5. Production checklist (before launch)

- [ ] Replace the placeholder `https://app.papercrane.bio` above with the real
      production domain in **both** Google Cloud (origins + redirect URIs) and
      Supabase (Site URL + redirect allow-list).
- [ ] Move the Google OAuth consent screen from *Testing* to *In production*
      so users outside the test list can sign in. This requires a privacy
      policy URL and homepage URL — both already live at papercrane.bio.
- [ ] Set `NEXT_PUBLIC_APP_URL` in the deploy env to the prod domain so the
      callback URL the browser sends matches the allow-list.
