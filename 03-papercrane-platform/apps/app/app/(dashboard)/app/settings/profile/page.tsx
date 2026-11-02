"use client";

import { Loader2, Save } from "lucide-react";
import Image from "next/image";
import { useEffect, useState } from "react";
import { createSupabaseBrowserClient } from "@/lib/supabase/client";

/**
 * `/app/settings/profile`: edit name, email, and avatar.
 *
 * Auth state lives in Supabase. We read the current user with
 * `supabase.auth.getUser()` and write back with `supabase.auth.updateUser`.
 *
 * Email changes trigger a Supabase confirmation email; we surface that as
 * a banner instead of pretending the change is instant. Avatar URL is a
 * plain string for now: once Wave 11 lands the storage bucket we'll
 * swap this for a real uploader.
 */

interface ProfileForm {
  name: string;
  email: string;
  avatarUrl: string;
}

const EMPTY: ProfileForm = { name: "", email: "", avatarUrl: "" };

export default function ProfileSettingsPage() {
  const [form, setForm] = useState<ProfileForm>(EMPTY);
  const [initialEmail, setInitialEmail] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<
    | { kind: "ok"; msg: string }
    | { kind: "err"; msg: string }
    | { kind: "pending-email"; msg: string }
    | null
  >(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const sb = createSupabaseBrowserClient();
        const { data, error } = await sb.auth.getUser();
        if (cancelled) return;
        if (error || !data.user) {
          setStatus({ kind: "err", msg: "Not signed in." });
          return;
        }
        const meta = (data.user.user_metadata ?? {}) as Record<string, unknown>;
        setForm({
          name: typeof meta.full_name === "string" ? meta.full_name : "",
          email: data.user.email ?? "",
          avatarUrl:
            typeof meta.avatar_url === "string" ? meta.avatar_url : "",
        });
        setInitialEmail(data.user.email ?? "");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const onChange =
    (key: keyof ProfileForm) => (e: React.ChangeEvent<HTMLInputElement>) => {
      setForm((f) => ({ ...f, [key]: e.target.value }));
    };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setStatus(null);
    try {
      const sb = createSupabaseBrowserClient();
      const updates: Parameters<typeof sb.auth.updateUser>[0] = {
        data: {
          full_name: form.name.trim(),
          avatar_url: form.avatarUrl.trim() || null,
        },
      };
      const trimmedEmail = form.email.trim();
      const emailChanged =
        trimmedEmail.length > 0 && trimmedEmail !== initialEmail;
      if (emailChanged) updates.email = trimmedEmail;

      const { error } = await sb.auth.updateUser(updates);
      if (error) {
        setStatus({ kind: "err", msg: error.message });
        return;
      }
      if (emailChanged) {
        setStatus({
          kind: "pending-email",
          msg: `We sent a confirmation link to ${trimmedEmail}. Click it to finish the change.`,
        });
      } else {
        setStatus({ kind: "ok", msg: "Profile saved." });
      }
    } catch (err) {
      setStatus({
        kind: "err",
        msg: err instanceof Error ? err.message : "Something went wrong.",
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-10">
      <header>
        <p className="font-sans text-[12px] text-graphite-soft">
          You
        </p>
        <h1 className="font-display text-display-md text-ink">Profile</h1>
        <p className="mt-2 max-w-xl font-sans text-[15px] text-graphite">
          How you appear to teammates and on shared dashboards. Email changes
          require confirmation by clicking the link Supabase emails to you.
        </p>
      </header>

      {status ? (
        <div
          role={status.kind === "err" ? "alert" : "status"}
          className={
            status.kind === "err"
              ? "rounded-lg border border-crane/40 bg-crane-glow px-5 py-3 font-sans text-[13px] text-crane-deep"
              : "rounded-lg border border-lattice bg-paper-fold px-5 py-3 font-sans text-[13px] text-ink"
          }
        >
          {status.msg}
        </div>
      ) : null}

      <section className="p-7">
        {loading ? (
          <div className="flex items-center gap-2 font-sans text-[14px] text-graphite">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading profile…
          </div>
        ) : (
          <form onSubmit={onSubmit} className="space-y-5 max-w-xl">
            <div className="flex items-center gap-4">
              <div className="relative h-16 w-16 overflow-hidden bg-paper">
                {form.avatarUrl ? (
                  // Use plain <img>: avatar URL can be any host, no remote
                  // patterns needed in next.config.
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={form.avatarUrl}
                    alt="Avatar preview"
                    className="h-full w-full object-cover"
                  />
                ) : (
                  <div
                    aria-hidden="true"
                    className="flex h-full w-full items-center justify-center font-display text-[20px] text-graphite-soft"
                  >
                    {(form.name.trim()[0] ?? form.email.trim()[0] ?? "?")
                      .toUpperCase()}
                  </div>
                )}
              </div>
              <div className="flex-1">
                <label className="flex flex-col gap-1.5">
                  <span className="font-sans text-[12px] text-graphite-soft">
                    Avatar URL
                  </span>
                  <input
                    type="url"
                    value={form.avatarUrl}
                    onChange={onChange("avatarUrl")}
                    placeholder="https://…"
                    className="rounded-xl border border-lattice-strong bg-paper px-4 py-2.5 font-sans text-[14px] text-ink placeholder:text-graphite-soft focus:border-ink focus:outline-none"
                  />
                </label>
              </div>
            </div>

            <label className="flex flex-col gap-1.5">
              <span className="font-sans text-[12px] text-graphite-soft">
                Name
              </span>
              <input
                type="text"
                required
                maxLength={80}
                value={form.name}
                onChange={onChange("name")}
                className="rounded-xl border border-lattice-strong bg-paper px-4 py-3 font-sans text-[15px] text-ink focus:border-ink focus:outline-none"
              />
            </label>

            <label className="flex flex-col gap-1.5">
              <span className="font-sans text-[12px] text-graphite-soft">
                Email
              </span>
              <input
                type="email"
                required
                value={form.email}
                onChange={onChange("email")}
                className="rounded-xl border border-lattice-strong bg-paper px-4 py-3 font-sans text-[15px] text-ink focus:border-ink focus:outline-none"
              />
              {form.email.trim() !== initialEmail && initialEmail ? (
                <span className="font-sans text-[12px] text-graphite">
                  We&apos;ll send a confirmation link before applying.
                </span>
              ) : null}
            </label>

            <div className="flex justify-end">
              <button
                type="submit"
                disabled={saving}
                className="btn-primary disabled:opacity-60"
              >
                {saving ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Save className="h-4 w-4" />
                )}
                {saving ? "Saving…" : "Save changes"}
              </button>
            </div>
          </form>
        )}
      </section>
    </div>
  );
}

// Re-export the unused Image to keep the next/image type chain happy in
// case future variants want to swap to optimised images. Avoids a stray
// `import` getting tree-shaken into a lint warning during refactors.
void Image;
