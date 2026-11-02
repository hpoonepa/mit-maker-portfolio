/**
 * Step 6: Invite teammates (Wave 8, optional).
 *
 * Up to 5 email rows, sent through the real `members.invite` tRPC mutation.
 *
 * API shape note
 * --------------
 * `members.invite` takes a SINGLE `{ email, role }` pair (strict object), not
 * a batch. So we fan out one mutation per address and reconcile the results
 * per row. Everyone invited from onboarding joins as `member`: the server
 * forbids granting a role at or above your own, and `member` is the safe,
 * useful default (can see and run jobs, can't touch billing or membership).
 *
 * UX choices
 * ----------
 *   - Empty rows are silently dropped; duplicates are flagged, not sent twice.
 *   - Bad emails block the primary CTA but never block "Skip".
 *   - We only advance the wizard once every invite we attempted succeeded.
 *     Failures stay put with a plain-language reason on the offending row -
 *     but "Skip for now" remains live, so a transient API blip can never
 *     trap someone inside onboarding.
 *   - Addresses that already went out are remembered, so retrying after a
 *     partial failure doesn't re-send (and doesn't trip the duplicate-invite
 *     conflict on the server).
 */
"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { StepContainer } from "@/components/onboarding/StepContainer";
import { trpc } from "@/lib/trpc/client";
import { writeClientCache } from "@/lib/onboarding-state";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const MAX_INVITES = 5;

/** Role every onboarding invite is sent with. See file header. */
const INVITE_ROLE = "member" as const;

interface RowError {
  index: number;
  message: string;
}

/** A non-empty row, paired with the index it came from. */
interface Entry {
  index: number;
  email: string;
}

/**
 * Translate a server/network failure into something a first-time user can
 * act on. Raw tRPC messages ("cannot invite a role at or above your own")
 * are written for engineers, not for a PI on their first day.
 */
function friendlyInviteError(err: unknown, email: string): string {
  const raw = err instanceof Error ? err.message.toLowerCase() : "";
  if (raw.includes("already a member")) {
    return `${email} is already in this workspace.`;
  }
  if (raw.includes("pending invite")) {
    return `${email} already has an invite waiting: no need to send another.`;
  }
  if (
    raw.includes("only owners") ||
    raw.includes("forbidden") ||
    raw.includes("can invite")
  ) {
    return "You don't have permission to invite people to this workspace yet.";
  }
  if (raw.includes("unauthorized") || raw.includes("unauthenticated")) {
    return "Your sign-in expired. Refresh the page and try again.";
  }
  if (raw.includes("failed to fetch") || raw.includes("network")) {
    return "We couldn't reach Paper Crane. Check your connection and try again.";
  }
  return `We couldn't send the invite to ${email}. Try again in a moment.`;
}

export default function InviteTeamPage() {
  const router = useRouter();
  const setStep = trpc.onboarding.setStep.useMutation();
  const invite = trpc.members.invite.useMutation();
  const [emails, setEmails] = useState<string[]>(["", "", ""]);
  const [submitting, setSubmitting] = useState(false);
  const [errors, setErrors] = useState<RowError[]>([]);
  const [sent, setSent] = useState<string[]>([]);
  const [warning, setWarning] = useState<string | null>(null);

  const entries: Entry[] = emails
    .map((value, index) => ({ index, email: value.trim() }))
    .filter((e) => e.email.length > 0);
  const allValid = entries.every((e) => EMAIL_RE.test(e.email));
  const anyEntered = entries.length > 0;

  function setRow(i: number, value: string) {
    setEmails((prev) => {
      const next = [...prev];
      next[i] = value;
      return next;
    });
    setErrors((prev) => prev.filter((e) => e.index !== i));
    setWarning(null);
  }

  function addRow() {
    if (emails.length >= MAX_INVITES) return;
    setEmails((prev) => [...prev, ""]);
  }

  async function persistAndGo() {
    writeClientCache({ step: "done", persona: null });
    try {
      await setStep.mutateAsync({ step: "done" });
    } catch {
      // best-effort; the done page also calls markComplete
    }
    router.push("/onboarding/done");
  }

  /** Client-side boundary checks. Returns the rows we should actually send. */
  function validate(): { errors: RowError[]; toSend: Entry[] } {
    const found: RowError[] = [];
    const seen = new Set<string>();
    const toSend: Entry[] = [];

    for (const entry of entries) {
      const normalised = entry.email.toLowerCase();
      if (!EMAIL_RE.test(entry.email)) {
        found.push({
          index: entry.index,
          message: "That doesn't look like an email address: check for typos.",
        });
        continue;
      }
      if (seen.has(normalised)) {
        found.push({
          index: entry.index,
          message: "You've already listed this address above.",
        });
        continue;
      }
      seen.add(normalised);
      // Already delivered on a previous attempt: don't re-send.
      if (sent.includes(normalised)) continue;
      toSend.push({ index: entry.index, email: entry.email });
    }

    return { errors: found, toSend };
  }

  async function handleSend() {
    if (!anyEntered) {
      // "Continue" with no emails is just a skip: saves the user a click.
      await handleSkip();
      return;
    }

    const { errors: validationErrors, toSend } = validate();
    setErrors(validationErrors);
    setWarning(null);
    if (validationErrors.length > 0) return;

    if (toSend.length === 0) {
      // Everything was already sent on a previous attempt.
      setSubmitting(true);
      await persistAndGo();
      return;
    }

    setSubmitting(true);
    const results = await Promise.allSettled(
      toSend.map((entry) =>
        invite.mutateAsync({ email: entry.email, role: INVITE_ROLE }),
      ),
    );

    const failures: RowError[] = [];
    const delivered: string[] = [];
    results.forEach((result, i) => {
      const entry = toSend[i]!;
      if (result.status === "fulfilled") {
        delivered.push(entry.email.toLowerCase());
      } else {
        failures.push({
          index: entry.index,
          message: friendlyInviteError(result.reason, entry.email),
        });
      }
    });

    if (delivered.length > 0) setSent((prev) => [...prev, ...delivered]);

    if (failures.length > 0) {
      setErrors(failures);
      setWarning(
        delivered.length > 0
          ? `${delivered.length} invite${delivered.length === 1 ? "" : "s"} sent. Fix the address${failures.length === 1 ? "" : "es"} below and try again. You can also invite people later from Settings → Team.`
          : "None of the invites went out. Try again, or invite people later from Settings → Team.",
      );
      setSubmitting(false);
      return; // Stay on this step; the wizard does not advance.
    }

    await persistAndGo();
  }

  async function handleSkip() {
    setSubmitting(true);
    await persistAndGo();
  }

  return (
    <StepContainer
      eyebrow="Step 05 / Team"
      title="Invite your team"
      subtitle="This is optional. You can invite people later from Settings."
      primary={{
        label: submitting
          ? anyEntered
            ? "Sending invites…"
            : "One moment…"
          : anyEntered
            ? "Send invites & continue"
            : "Continue without invites",
        onClick: handleSend,
        disabled: submitting || (anyEntered && !allValid),
      }}
      secondary={{ label: "Back", href: "/onboarding/first-job" }}
      skip={{
        label: submitting ? "Skipping…" : "Skip for now",
        onClick: handleSkip,
        disabled: submitting,
      }}
    >
      <div className="space-y-3">
        {emails.map((value, i) => {
          const err = errors.find((e) => e.index === i);
          const wasSent = sent.includes(value.trim().toLowerCase()) && value.trim().length > 0;
          return (
            <div key={i}>
              <input
                type="email"
                value={value}
                onChange={(e) => setRow(i, e.target.value)}
                placeholder={i === 0 ? "alice@lab.edu" : "Another teammate"}
                disabled={submitting}
                autoComplete="off"
                aria-invalid={Boolean(err)}
                data-testid={`invite-email-${i}`}
                className={[
                  "w-full rounded-xl border bg-paper px-4 py-3 font-display text-base text-ink placeholder:text-graphite-soft focus:outline-none focus:ring-2 disabled:opacity-60",
                  err
                    ? "border-crane focus:border-crane focus:ring-crane-glow"
                    : "border-lattice focus:border-crane focus:ring-crane-glow",
                ].join(" ")}
              />
              {err && (
                <p className="mt-1 text-xs text-crane-deep" role="alert">
                  {err.message}
                </p>
              )}
              {!err && wasSent && (
                <p className="mt-1 text-xs text-graphite" role="status">
                  Invite sent.
                </p>
              )}
            </div>
          );
        })}

        {emails.length < MAX_INVITES && (
          <button
            type="button"
            onClick={addRow}
            disabled={submitting}
            className="text-xs font-sans text-graphite hover:text-ink disabled:opacity-40"
          >
            + Add another
          </button>
        )}
      </div>

      {warning && (
        <p className="text-xs text-graphite" role="status">
          {warning}
        </p>
      )}

      <div className="p-4 text-sm text-graphite">
        <p>
          <span className="text-ink">What this does:</span> each person gets an
          email link. When they accept, they join this workspace and can see and
          run design jobs alongside you.
        </p>
        <p className="mt-2 text-xs text-graphite-soft">
          Teammates join as <span className="text-graphite">members</span>.
          They can work on jobs and designs, but can&apos;t change billing or
          remove people. You stay the owner. Nothing is charged for adding teammates.
        </p>
        <p className="mt-2 text-xs text-graphite-soft">
          <span className="text-graphite">Next:</span> that&apos;s the last step.
          You&apos;ll land on your dashboard either way.
        </p>
      </div>
    </StepContainer>
  );
}
