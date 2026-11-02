"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { ArrowLeft } from "lucide-react";
import { z } from "zod";
import { trpc } from "@/lib/trpc/client";
import { useToast } from "@/components/toasts/useToast";
import { mapTrpcError } from "@/lib/errors/trpc-error-map";

const NewProjectInput = z.object({
  name: z.string().min(2).max(80),
  description: z.string().max(500).optional(),
});

function slugify(name: string): string {
  return (
    name
      .toLowerCase()
      .trim()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 64) || `project-${Date.now().toString(36)}`
  );
}

export default function NewProjectPage() {
  const router = useRouter();
  const utils = trpc.useUtils?.();
  const { toast } = useToast();
  const create = trpc.projects.create.useMutation({
    onSuccess: (p: { id: string }) => {
      utils?.projects.list.invalidate?.();
      toast({
        title: "Project created",
        description: "Heading to your new project.",
        variant: "success",
      });
      router.push(`/app/projects/${p.id}`);
    },
    onError: (err) => {
      // Project create has one common, very-specific failure mode: the
      // user picks a name whose slug clashes with an existing project in
      // the org. The CONFLICT path now says exactly that.
      const mapped = mapTrpcError(err, {
        resource: "project",
        conflictField: "name",
      });
      setError(mapped.message);
      toast({
        title: mapped.title,
        description: mapped.message,
        variant: "error",
      });
      if (mapped.action.kind === "login") {
        const next = mapped.action.nextPath ?? "/app/projects/new";
        setTimeout(() => router.push(`/login?next=${encodeURIComponent(next)}`), mapped.action.redirectAfterMs);
      }
    },
  });

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const nameRef = useRef<HTMLInputElement | null>(null);

  // Autofocus the name field on mount so power users can start typing
  // immediately. Microtask defer keeps the focus from fighting the page's
  // initial paint.
  useEffect(() => {
    queueMicrotask(() => nameRef.current?.focus());
  }, []);

  const previewSlug = name.trim() ? slugify(name) : "";

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    const parsed = NewProjectInput.safeParse({
      name: name.trim(),
      description: description.trim() || undefined,
    });
    if (!parsed.success) {
      const msg = parsed.error.issues[0]?.message ?? "Invalid input";
      setError(msg);
      toast({ title: "Check the form", description: msg, variant: "warning" });
      return;
    }

    create.mutate({
      name: parsed.data.name,
      slug: slugify(parsed.data.name),
      description: parsed.data.description,
    });
  };

  const submitting = create.isPending;
  const mutationError = create.error?.message;

  return (
    <div className="max-w-2xl">
      <Link
        href="/app/projects"
        className="inline-flex items-center gap-2 font-sans text-[13px] text-graphite hover:text-ink transition-colors"
      >
        <ArrowLeft className="w-3.5 h-3.5" />
        Back to projects
      </Link>

      <h1 className="mt-6 font-display text-display-md text-ink">
        New project
      </h1>

      <form
        onSubmit={onSubmit}
        className="mt-8 space-y-5"
      >
        <fieldset disabled={submitting} className="space-y-5">
          <label className="flex flex-col gap-1.5">
            <span className="font-sans text-[12px] text-graphite-soft">
              Name
            </span>
            <input
              ref={nameRef}
              type="text"
              required
              maxLength={80}
              placeholder="RBX1 campaign"
              value={name}
              onChange={(e) => setName(e.target.value)}
              data-testid="e2e-project-name"
              className="rounded-xl border border-lattice-strong bg-paper px-4 py-3 font-sans text-[15px] text-ink placeholder:text-graphite-soft focus:border-ink focus:outline-none disabled:opacity-60"
            />
            {previewSlug && (
              <span
                className="font-sans text-[12px] text-graphite-soft pt-0.5"
                aria-live="polite"
              >
                /projects/{previewSlug}
              </span>
            )}
          </label>

          <label className="flex flex-col gap-1.5">
            <span className="font-sans text-[12px] text-graphite-soft">
              Description{" "}
              <span className="text-graphite-soft/80">(optional)</span>
            </span>
            <textarea
              rows={4}
              maxLength={500}
              placeholder="Short notes on the target, goal, collaborators…"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="rounded-xl border border-lattice-strong bg-paper px-4 py-3 font-sans text-[15px] text-ink placeholder:text-graphite-soft focus:border-ink focus:outline-none resize-y disabled:opacity-60"
            />
          </label>
        </fieldset>

        {(error || mutationError) && (
          <p
            role="alert"
            className="rounded-xl bg-crane-glow px-4 py-3 font-sans text-[13px] text-crane-deep"
          >
            {error ?? mutationError}
          </p>
        )}

        <div className="flex items-center justify-end gap-3 pt-2">
          <Link
            href="/app/projects"
            aria-disabled={submitting}
            className="rounded-full px-5 py-2.5 font-sans text-[14px] text-graphite hover:text-ink transition-colors aria-disabled:pointer-events-none aria-disabled:opacity-50"
          >
            Cancel
          </Link>
          <button
            type="submit"
            disabled={submitting}
            data-testid="e2e-project-create-submit"
            className="btn-primary disabled:opacity-60 disabled:cursor-not-allowed"
          >
            {submitting ? "Creating…" : "Create project"}
          </button>
        </div>
      </form>
    </div>
  );
}
