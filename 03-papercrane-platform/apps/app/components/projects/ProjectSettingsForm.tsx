"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Save } from "lucide-react";
import { trpc } from "@/lib/trpc/client";
import { useToast } from "@/components/toasts/useToast";
import { mapTrpcError } from "@/lib/errors/trpc-error-map";

export interface ProjectSettingsFormProps {
  projectId: string;
  initialName: string;
  initialDescription: string;
}

/**
 * Edit-name + edit-description form for a project. Powered by
 * `trpc.projects.update`. Lives inside the project Settings page; the
 * destructive Delete action lives in `ProjectDangerZone` below the form.
 *
 * Validation mirrors the server zod schema (name 1..120, description 0..2000)
 * so the user gets instant feedback without a roundtrip. Server is the source
 * of truth: any extra constraints surface via `mapTrpcError` and become
 * inline + toast errors.
 */
export function ProjectSettingsForm({
  projectId,
  initialName,
  initialDescription,
}: ProjectSettingsFormProps) {
  const router = useRouter();
  const utils = trpc.useUtils();
  const { toast } = useToast();

  const [name, setName] = useState(initialName);
  const [description, setDescription] = useState(initialDescription);
  const [fieldErrors, setFieldErrors] = useState<{
    name?: string;
    description?: string;
  }>({});

  const update = trpc.projects.update.useMutation({
    onSuccess: () => {
      toast({
        title: "Project saved",
        description: "Your changes are live.",
        variant: "success",
      });
      void utils.projects.list.invalidate();
      void utils.projects.get.invalidate({ id: projectId });
      router.refresh();
    },
    onError: (err) => {
      const mapped = mapTrpcError(err, { resource: "project" });
      toast({
        title: mapped.title,
        description: mapped.message,
        variant: "error",
      });
    },
  });

  const dirty =
    name.trim() !== initialName.trim() ||
    description.trim() !== initialDescription.trim();

  function validate(): boolean {
    const next: typeof fieldErrors = {};
    const trimmedName = name.trim();
    if (trimmedName.length < 1) next.name = "Name is required.";
    else if (trimmedName.length > 120) next.name = "Keep it under 120 characters.";
    if (description.length > 2000)
      next.description = "Keep description under 2000 characters.";
    setFieldErrors(next);
    return Object.keys(next).length === 0;
  }

  function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!validate()) return;
    update.mutate({
      id: projectId,
      name: name.trim(),
      description: description.trim(),
    });
  }

  return (
    <form
      onSubmit={onSubmit}
      data-testid="e2e-project-settings-form"
      className="space-y-6 rounded-lg border border-lattice bg-paper-fold/30 p-6"
    >
      <div>
        <label
          htmlFor="project-name"
          className="font-sans text-[12px] text-graphite-soft"
        >
          Name
        </label>
        <input
          id="project-name"
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          data-testid="e2e-project-settings-name"
          maxLength={120}
          className="mt-2 w-full rounded-lg border border-lattice bg-paper px-4 py-2.5 font-sans text-[15px] text-ink outline-none focus:border-lattice-strong"
        />
        {fieldErrors.name && (
          <p
            role="alert"
            className="mt-1.5 font-sans text-[12px] text-crane-deep"
          >
            {fieldErrors.name}
          </p>
        )}
      </div>

      <div>
        <label
          htmlFor="project-description"
          className="font-sans text-[12px] text-graphite-soft"
        >
          Description
        </label>
        <textarea
          id="project-description"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          data-testid="e2e-project-settings-description"
          rows={4}
          maxLength={2000}
          placeholder="What is this project for?"
          className="mt-2 w-full resize-y rounded-lg border border-lattice bg-paper px-4 py-2.5 font-sans text-[14px] text-ink outline-none placeholder:text-graphite-soft focus:border-lattice-strong"
        />
        <div className="mt-1 flex items-center justify-between">
          {fieldErrors.description ? (
            <p role="alert" className="font-sans text-[12px] text-crane-deep">
              {fieldErrors.description}
            </p>
          ) : (
            <span />
          )}
          <span className="font-mono text-[11px] text-graphite-soft tabular-nums">
            {description.length}/2000
          </span>
        </div>
      </div>

      <div className="flex items-center justify-end gap-2">
        <button
          type="button"
          onClick={() => {
            setName(initialName);
            setDescription(initialDescription);
            setFieldErrors({});
          }}
          disabled={!dirty || update.isPending}
          className="rounded-full px-5 py-2.5 font-sans text-[14px] text-graphite hover:text-ink transition-colors disabled:opacity-40"
        >
          Reset
        </button>
        <button
          type="submit"
          disabled={!dirty || update.isPending}
          data-testid="e2e-project-settings-save"
          className="inline-flex items-center gap-2 rounded-full bg-ink px-5 py-2.5 font-sans text-[14px] text-paper hover:bg-graphite transition-colors disabled:opacity-40 disabled:hover:bg-ink"
        >
          <Save className="h-4 w-4" />
          {update.isPending ? "Saving…" : "Save changes"}
        </button>
      </div>
    </form>
  );
}

export default ProjectSettingsForm;
