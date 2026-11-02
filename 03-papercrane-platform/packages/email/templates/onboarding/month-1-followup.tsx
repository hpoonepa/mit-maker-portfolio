/**
 * Onboarding email 5/5 — Thirty day follow-up.
 * Sent: 30 days after signup.
 */
import * as React from 'react';
import { Section, Text } from '@react-email/components';
import {
  CTAButton,
  EmailLayout,
  headingStyle,
  paragraphStyle,
  subtleStyle,
} from '../../src/templates/_layout';

export const subject = "30 days. What's next?";

export interface Month1Props {
  name?: string;
  roadmapUrl: string;
}

export function Month1FollowupEmail({ name, roadmapUrl }: Month1Props) {
  const greeting = name?.trim() ? name : 'there';
  return (
    <EmailLayout preview="Thirty days in. Here's what we're building next.">
      <Section>
        <Text style={headingStyle}>Thirty days, {greeting}.</Text>
        <Text style={paragraphStyle}>
          You&apos;ve seen the workflow at full speed. The next month brings deeper
          tools — campaign-level dashboards, automated negative design, and a wet-lab
          handoff format that drops straight into Twist or IDT.
        </Text>
        <Text style={paragraphStyle}>
          If a specific target or tool would unlock your next experiment, we want to
          hear it before we ship.
        </Text>
        <CTAButton href={roadmapUrl}>See what&apos;s coming</CTAButton>
        <Text style={subtleStyle}>— The Paper Crane team</Text>
      </Section>
    </EmailLayout>
  );
}

export default Month1FollowupEmail;
