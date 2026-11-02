import type { Metadata } from "next";
import { LegalLayout } from "@/components/legal/LegalLayout";
import { PrivacyChoices } from "@/components/legal/PrivacyChoices";
import { pageMetadata } from "@/lib/metadata";

const TITLE = "Privacy choices";
const DESCRIPTION =
  "Manage your cookie and analytics preferences for Paper Crane.";

export const metadata: Metadata = pageMetadata({
  title: TITLE,
  description: DESCRIPTION,
  path: "/privacy-choices",
  ogTitle: "Privacy choices",
  ogDesc: "Manage your cookie and analytics preferences.",
});

export default function PrivacyChoicesPage() {
  return (
    <LegalLayout
      eyebrow="§ Legal · Privacy choices"
      title="Privacy choices."
      effective="2026-04-27"
      intro={
        <>
          Change what you accepted in the cookie banner. We honor Global
          Privacy Control (GPC) and your most recent choice. Strictly
          necessary cookies (auth, CSRF) cannot be turned off because the
          Service depends on them.
        </>
      }
    >
      <PrivacyChoices />
    </LegalLayout>
  );
}
