"use client";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { CreateTargetWizard } from "@/components/targets/CreateTargetWizard";

/**
 * Target creation flow.
 *
 * Hands off all the heavy lifting to `<CreateTargetWizard>` so the page
 * stays a thin shell: the wizard is also reusable from a modal in other
 * flows (e.g. "+ New target" inside a project page).
 *
 * Wiring (per Wave 14 §upload):
 *   1. User picks Upload tab → drops a .pdb/.cif (≤ 10 MB).
 *   2. Client calls `targets.getUploadUrl({ filename })` → receives a
 *      presigned PUT URL + staging key.
 *   3. Client streams the file directly to R2 via PUT (with content-type).
 *   4. Client calls `targets.createFromUpload({ uploadKey, name, projectId })`.
 *   5. Server fetches the bytes, parses chains/residues/mass, persists a
 *      `Target` row, returns it. Client redirects to /app/targets/<id>.
 */
export default function NewTargetPage() {
  return (
    <div className="max-w-3xl space-y-8">
      <div>
        <Link
          href="/app/targets"
          className="inline-flex items-center gap-2 font-sans text-[13px] text-graphite hover:text-ink transition-colors"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          Back to targets
        </Link>

        <h1 className="mt-6 font-display text-display-md text-ink">
          New target
        </h1>
        <p className="mt-2 font-sans text-[15px] text-graphite">
          Add a protein structure you can reuse in your jobs.
        </p>
      </div>

      <CreateTargetWizard />
    </div>
  );
}
