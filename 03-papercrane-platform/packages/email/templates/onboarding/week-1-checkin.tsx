/**
 * Onboarding email 3/5 — One week check-in.
 * Sent: 7 days after signup.
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

export const subject = 'How was your first week with Paper Crane?';

export interface Week1Props {
  name?: string;
  feedbackUrl: string;
}

export function Week1CheckinEmail({ name, feedbackUrl }: Week1Props) {
  const greeting = name?.trim() ? name : 'there';
  return (
    <EmailLayout preview="A short check-in — what worked, what didn't.">
      <Section>
        <Text style={headingStyle}>One week in, {greeting}.</Text>
        <Text style={paragraphStyle}>
          You&apos;ve had a few runs to feel the shape of the workflow. We&apos;d
          like to hear the honest version: where it felt fast, where it dragged,
          which tool you reached for first, and what we should fix next.
        </Text>
        <Text style={paragraphStyle}>
          A founder reads every reply. Five sentences is plenty.
        </Text>
        <CTAButton href={feedbackUrl}>Tell us what you think</CTAButton>
        <Text style={subtleStyle}>— The Paper Crane team</Text>
      </Section>
    </EmailLayout>
  );
}

export default Week1CheckinEmail;
