import { Providers } from "../providers";

/**
 * Signup shell. The signup page mounts <InviteCodeGate>, which uses tRPC
 * client hooks (`api.beta.validateCode.useMutation`). The root layout
 * intentionally does NOT wrap in <Providers> (see app/providers.tsx + the
 * admin layout for the same pattern), so we mount them here for the entire
 * signup flow (including /signup/check-email).
 */
export default function SignupLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <Providers>{children}</Providers>;
}
