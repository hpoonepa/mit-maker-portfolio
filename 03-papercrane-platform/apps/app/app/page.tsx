import type { Metadata } from "next";
import { redirect } from "next/navigation";

/**
 * Root of the authenticated app deployment (app.papercrane.bio).
 *
 * There is no landing page here: that lives on `apps/web` at papercrane.bio.
 * Anyone hitting `/` is routed to `/dashboard`, where middleware enforces auth:
 *   - signed-in users land on the dashboard shell
 *   - unauthenticated users get bounced to /login with a redirectTo
 */
export const metadata: Metadata = {
  robots: { index: false, follow: false },
};

export default function RootRedirect() {
  redirect("/dashboard");
}
