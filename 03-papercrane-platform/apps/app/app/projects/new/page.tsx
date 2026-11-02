import { redirect } from "next/navigation";

/**
 * Redirect-only page: the canonical New Project form lives under
 * `(dashboard)/app/projects/new`. WelcomeModal, QuickStart, and SampleProjects
 * link here; this thin shim hands off (preserving the search string so
 * `?sample=...` and other params survive).
 */
export default async function NewProjectRedirect({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (typeof v === "string") qs.set(k, v);
    else if (Array.isArray(v) && v.length > 0) qs.set(k, v[0]!);
  }
  const suffix = qs.toString();
  redirect(`/app/projects/new${suffix ? `?${suffix}` : ""}`);
}
