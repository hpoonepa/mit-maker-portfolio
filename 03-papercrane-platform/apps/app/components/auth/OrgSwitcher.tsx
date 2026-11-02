"use client";

import { Check, ChevronDown, Plus } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

export interface OrgSummary {
  id: string;
  slug: string;
  name: string;
}

export interface OrgSwitcherProps {
  /** All orgs the user is a member of. Pass `[]` to render in single-org mode. */
  orgs: OrgSummary[];
  /** Currently selected org. Required: its name + initial drive the trigger. */
  current: OrgSummary;
  /**
   * Cookie name read by the server to scope queries to the active org.
   * Defaults to `current-org-id` per the auth-flow spec.
   */
  cookieName?: string;
  /**
   * Called when the user clicks "Create org" in the dropdown. The owning
   * component opens a modal (or routes to /onboarding/create-org). We don't
   * own the modal here so this stays usable from any context (TopBar, command
   * palette, settings page).
   */
  onCreateOrg?: () => void;
}

/**
 * Multi-org switcher dropdown rendered in the dashboard nav.
 *
 * Switching strategy
 * ------------------
 * The server resolves `auth.orgId` from the user's default membership unless
 * a `current-org-id` cookie is present, in which case it scopes to that org.
 * Switching writes the cookie and calls `router.refresh()`: RSC re-renders
 * with the new org context, no full page reload needed.
 *
 * The cookie is intentionally not httpOnly: we only read it on the server
 * for routing, and writing from the browser keeps the switch instant.
 * Membership is always re-verified server-side, so a tampered cookie can't
 * grant access: worst case the user falls back to their default org.
 */
export function OrgSwitcher({
  orgs,
  current,
  cookieName = "current-org-id",
  onCreateOrg,
}: OrgSwitcherProps) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    window.addEventListener("mousedown", onClick);
    return () => window.removeEventListener("mousedown", onClick);
  }, []);

  const switchTo = (org: OrgSummary) => {
    if (org.id === current.id) {
      setOpen(false);
      return;
    }
    // Set cookie. 1y, path=/, SameSite=Lax: we want it on top-level nav
    // back from email links etc., but no need for cross-site.
    document.cookie = `${cookieName}=${encodeURIComponent(org.id)}; Path=/; Max-Age=${60 * 60 * 24 * 365}; SameSite=Lax`;
    setOpen(false);
    router.refresh();
  };

  const handleCreate = () => {
    setOpen(false);
    if (onCreateOrg) {
      onCreateOrg();
    } else {
      router.push("/onboarding/create-org");
    }
  };

  const others = orgs.filter((o) => o.id !== current.id);
  const hasMultiple = orgs.length > 1;

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        data-testid="org-switcher-trigger"
        className="flex items-center gap-2 rounded-full border border-lattice bg-paper px-3 py-1.5 font-sans text-[13px] text-ink transition-colors hover:border-lattice-strong"
      >
        <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-ink text-paper font-mono text-[10px]">
          {current.name[0]?.toUpperCase() ?? "?"}
        </span>
        <span className="max-w-[160px] truncate">{current.name}</span>
        <ChevronDown className="w-3.5 h-3.5 text-graphite-soft" />
      </button>

      {open && (
        <div
          role="menu"
          className="absolute left-0 top-full z-40 mt-2 w-64 rounded-lg border border-lattice bg-paper shadow-lg p-2"
        >
          <div className="px-3 py-1.5 font-sans text-[12px] text-graphite-soft">
            Current
          </div>
          <div className="flex items-center justify-between rounded-xl bg-paper-fold px-3 py-2 font-sans text-[13px] text-ink">
            <span className="truncate">{current.name}</span>
            <span className="font-mono text-[11px] text-graphite-soft">
              {current.slug}
            </span>
          </div>

          {hasMultiple && (
            <>
              <div className="mt-3 px-3 py-1.5 font-sans text-[12px] text-graphite-soft">
                Switch to
              </div>
              <ul className="flex flex-col gap-0.5">
                {others.map((org) => (
                  <li key={org.id}>
                    <button
                      type="button"
                      onClick={() => switchTo(org)}
                      data-testid={`org-switcher-item-${org.slug}`}
                      className="flex w-full items-center justify-between rounded-xl px-3 py-2 font-sans text-[13px] text-ink transition-colors hover:bg-paper-fold"
                    >
                      <span className="flex items-center gap-2 min-w-0">
                        <span className="inline-flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full bg-paper-fold border border-lattice text-ink font-mono text-[10px]">
                          {org.name[0]?.toUpperCase() ?? "?"}
                        </span>
                        <span className="truncate">{org.name}</span>
                      </span>
                      <Check className="w-3.5 h-3.5 text-paper" />
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}

          <div className="my-2 h-px bg-lattice" />

          <button
            type="button"
            onClick={handleCreate}
            data-testid="org-switcher-create"
            className="flex w-full items-center gap-2 rounded-xl px-3 py-2 font-sans text-[13px] text-ink transition-colors hover:bg-paper-fold"
          >
            <Plus className="w-3.5 h-3.5 text-graphite" />
            Create org
          </button>
        </div>
      )}
    </div>
  );
}
