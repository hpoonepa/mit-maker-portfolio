import { Providers } from "../providers";
import { AdminNav } from "./AdminNav";

export const dynamic = "force-dynamic";

/**
 * Admin shell. Persistent nav between admin sections (feedback, invites,
 * etc.). Intentionally chrome-light: monospace, status-led, no marketing
 * flair: matches the Stripe-internal / Linear-settings reference.
 *
 * Admin pages use trpc client hooks, so this layout mounts the tRPC + toast
 * providers (the root layout intentionally does not: see app/providers.tsx).
 */
export default function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <Providers>
      <div className="min-h-screen bg-paper text-ink">
        <AdminNav />
        {children}
      </div>
    </Providers>
  );
}
