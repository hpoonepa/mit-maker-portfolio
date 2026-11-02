import type { ReactNode } from "react";
import { redirect } from "next/navigation";
import { Providers } from "@/app/providers";
import { getSessionUser } from "@/lib/supabase/server";

/**
 * Layout for /projects/* pages that live outside the (dashboard) group.
 *
 * The hotspot picker page (`/projects/[projectId]/target`) is a Client
 * Component that calls tRPC hooks (`trpc.targets.list.useQuery`,
 * `trpc.targets.saveHotspots.useMutation`). Without `<Providers>` wrapping
 * the subtree it throws `Unable to find tRPC Context` and the route 500s.
 *
 * Auth is enforced here (defense-in-depth alongside middleware).
 */
export default async function ProjectsLayout({
  children,
}: {
  children: ReactNode;
}) {
  const user = await getSessionUser();
  if (!user) {
    redirect("/login");
  }
  return <Providers>{children}</Providers>;
}
