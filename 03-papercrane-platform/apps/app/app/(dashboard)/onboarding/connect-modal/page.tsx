/**
 * Step 5: Connect Modal account (Wave 8, optional).
 *
 * If the user pastes a Modal token here, we'll route real GPU jobs
 * through their account. If they skip, we drop into "stub mode": jobs
 * are accepted by the API but not actually dispatched to a GPU; the
 * dashboard shows a synthetic preview run so the rest of the product
 * is explorable.
 *
 * Skipping is a first-class option: the "Skip for now" button is
 * shown prominently next to the primary CTA (not buried in a footer
 * link) because real Modal credentials aren't a precondition for the
 * rest of onboarding.
 *
 */
"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { StepContainer } from "@/components/onboarding/StepContainer";
import { trpc } from "@/lib/trpc/client";
import { writeClientCache } from "@/lib/onboarding-state";

export default function ConnectModalPage() {
  const router = useRouter();
  const setStep = trpc.onboarding.setStep.useMutation();
  const connectModal = trpc.modalAccounts.connect.useMutation();
  const [tokenId, setTokenId] = useState("");
  const [tokenSecret, setTokenSecret] = useState("");
  const [environment, setEnvironment] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const valid = /^ak-[A-Za-z0-9._-]{8,}$/.test(tokenId.trim())
    && /^as-[A-Za-z0-9._-]{8,}$/.test(tokenSecret.trim());

  async function persistAndGo() {
    writeClientCache({ step: "invite-team", persona: null });
    try {
      await setStep.mutateAsync({ step: "invite-team" });
    } catch {
      // ignore; resume logic will re-sync
    }
    router.push("/onboarding/invite-team");
  }

  async function handleConnect() {
    if (!valid) {
      setError("Use the paired ak- token ID and as- token secret from Modal.");
      return;
    }
    setError(null);
    setSubmitting(true);
    try {
      await connectModal.mutateAsync({
        tokenId: tokenId.trim(),
        tokenSecret: tokenSecret.trim(),
        environment: environment.trim() || undefined,
      });
      await persistAndGo();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not connect Modal.");
      setSubmitting(false);
    }
  }

  async function handleSkip() {
    setSubmitting(true);
    await persistAndGo();
  }

  return (
    <StepContainer
      eyebrow="Step 05 / Compute"
      title="Connect Modal for real GPUs"
      subtitle="Paste a Modal token to dispatch jobs to your account, or skip and we'll run a stub preview instead."
      primary={{
        label: submitting && valid ? "Connecting..." : "Connect Modal",
        onClick: handleConnect,
        disabled: submitting || !valid,
      }}
      secondary={{ label: "Back", href: "/onboarding/first-job" }}
      skip={{
        label: submitting && !valid ? "Skipping…" : "Skip for now",
        onClick: handleSkip,
      }}
    >
      <label className="block">
        <span className="mb-2 block font-sans text-[0.66rem] text-graphite">
          Modal token ID
        </span>
        <input
          type="password"
          value={tokenId}
          onChange={(e) => {
            setTokenId(e.target.value);
            if (error) setError(null);
          }}
          placeholder="ak-..."
          autoComplete="off"
          spellCheck={false}
          data-testid="modal-token-id"
          className="w-full rounded-xl border border-lattice bg-paper px-4 py-3 font-mono text-sm text-ink placeholder:text-graphite-soft focus:border-crane focus:outline-none focus:ring-2 focus:ring-crane-glow"
        />
      </label>

      <label className="block">
        <span className="mb-2 block font-sans text-[0.66rem] text-graphite">
          Modal token secret
        </span>
        <input
          type="password"
          value={tokenSecret}
          onChange={(e) => {
            setTokenSecret(e.target.value);
            if (error) setError(null);
          }}
          placeholder="as-..."
          autoComplete="off"
          spellCheck={false}
          data-testid="modal-token-secret"
          className="w-full rounded-xl border border-lattice bg-paper px-4 py-3 font-mono text-sm text-ink placeholder:text-graphite-soft focus:border-crane focus:outline-none focus:ring-2 focus:ring-crane-glow"
        />
      </label>

      {error && (
        <p className="text-xs text-crane-deep" role="alert">
          {error}
        </p>
      )}

      <label className="block">
        <span className="mb-2 block font-sans text-[0.66rem] text-graphite">
          Modal environment (optional)
        </span>
        <input
          type="text"
          value={environment}
          onChange={(e) => setEnvironment(e.target.value)}
          placeholder="main"
          autoComplete="off"
          spellCheck={false}
          data-testid="modal-environment"
          className="w-full rounded-xl border border-lattice bg-paper px-4 py-3 font-mono text-sm text-ink placeholder:text-graphite-soft focus:border-crane focus:outline-none focus:ring-2 focus:ring-crane-glow"
        />
      </label>

      <div className="p-4 text-sm text-graphite">
        <p>
          Generate a token at{" "}
          <a
            href="https://modal.com/settings/tokens"
            target="_blank"
            rel="noreferrer"
            className="text-crane hover:underline"
          >
            modal.com/settings/tokens
          </a>
          . You can revoke it any time: Paper Crane only uses it to dispatch
          jobs you submit. The token itself selects your Modal workspace.
        </p>
        <p className="mt-2 text-xs text-graphite-soft">
          You can skip this step. Stub-mode jobs return synthetic results; real
          runs are available after you connect.{" "}
          <Link href="/docs#modal" className="text-crane hover:underline">
            How stub mode works
          </Link>
          .
        </p>
      </div>
    </StepContainer>
  );
}
