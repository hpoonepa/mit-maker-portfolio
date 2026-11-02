# Paper Crane — Beta Program

This is the operator's guide to inviting and supporting beta testers.

## What ships in Wave 15

- Invite-only signup (gated by `NEXT_PUBLIC_BETA_GATE=true`)
- `BetaInvite` model with single-use, multi-use, and unlimited codes
- Admin page at `/admin/invites` for minting codes
- `BETA` pill in the topbar that opens the feedback widget on click
- "What's new" modal that pops once on dashboard load with the latest entry
- Public `/whats-new` page with the full changelog

## Inviting a tester

1. Sign in as an org admin/owner.
2. Visit `/admin/invites`.
3. Mint codes:
   - **How many** — number of codes to create in one batch (1 to 100).
   - **Max uses** — `1` for single-use (default), N for multi-use, `0` for
     unlimited.
   - **Expires in (days)** — optional. Leave blank for never.
   - **Note** — optional human label so you can identify the batch later
     (e.g. "YC W26 dinner", "iGEM mentors", "Vedant's lab").
4. Copy the codes from the green "Just minted" panel. The same codes are
   visible in the table below for the rest of the session, but the green
   panel disappears on refresh.
5. Share the codes out-of-band (email, Slack DM, etc.). We deliberately do
   not email codes from the app to keep the audit trail simple.

### Code format

All codes are `PC-XXXX-XXXX` where each `X` is from a 32-char Crockford-ish
alphabet (`A-Z 0-9` minus `I`, `O`, `0`, `1` to reduce transcription
errors). The signup form uppercases input and trims whitespace before
validating, so `pc-abcd-efgh` and `PC-ABCD-EFGH` are equivalent.

## How a tester signs up

1. They open `https://app.papercrane.bio/signup` (or
   `/signup?invite=PC-ABCD-EFGH` — the link auto-fills the code).
2. The signup form refuses to submit until the code validates.
3. After Supabase creates the user, the auth callback claims the code
   atomically (`beta.claimInvite`). If two people race the last seat,
   exactly one wins.
4. They land in the standard onboarding wizard.
5. On their first dashboard view they see the "What's new" modal with the
   latest changelog entry.

## Turning the gate on or off

Set `NEXT_PUBLIC_BETA_GATE=true` on the web app's environment. To open
public signup, flip it to `false` (or unset). Codes you've already minted
keep working — the gate only controls whether the form *requires* one.

## Feedback flow

- Click the gold `BETA` pill in the topbar to open the feedback widget.
- The pill dispatches a `papercrane:open-feedback` CustomEvent that the
  widget listens for. Don't import the widget from the badge — keep them
  decoupled so either can be replaced independently.

## Operational notes

- **Never log codes.** The router masks codes in any error path. If you
  add new code paths, use `maskCode()` from `routers/beta.ts`.
- **Don't run `prisma migrate` blindly** in production. The migration in
  `migrations/20260427190000_wave15_beta_invites/` adds a column to
  `users` and creates `beta_invites`. Apply it with the team's normal
  release process.
- **RLS** — `beta_invites` denies all access except service-role. The
  router's admin check (`assertBetaAdmin`) is the only path to the table
  for non-service callers.
- **Changelog entries** live inline in
  `apps/app/components/beta/WhatsNew.tsx` (`CHANGELOG_ENTRIES`). Prepend
  new entries; the modal pops to anyone whose `last_changelog_seen` is
  not the head version.

## Common questions

**Can I see who claimed a code?**
Yes — `beta_invites.used_by_user_id` is set on first claim, joinable to
`users`. The admin UI does not surface this yet; query it directly for
now.

**A tester says "expired" but I just minted the code.**
Check the row's `expires_at`. If `0 days` was passed accidentally, the
code is born expired. Re-mint with a non-zero or empty expiry.

**Can I revoke a code?**
Set `expires_at = now()` directly via SQL. The `validateInvite` and
`claimInvite` paths both check expiry before incrementing. A future
admin UI button can encapsulate this; for now use a one-line SQL update.
