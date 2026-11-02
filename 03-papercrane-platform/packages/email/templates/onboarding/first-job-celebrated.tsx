/**
 * Onboarding email 2/5 — First job celebrated.
 * Sent: when a user's first design job completes.
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

export const subject = 'You folded your first paper crane.';

export interface FirstJobProps {
  name?: string;
  resultsUrl: string;
  topRankCount?: number;
}

export function FirstJobCelebratedEmail({ name, resultsUrl, topRankCount }: FirstJobProps) {
  const greeting = name?.trim() ? name : 'there';
  return (
    <EmailLayout preview="Your first design job finished. Take a look at what came out.">
      <Section>
        <Text style={headingStyle}>That&apos;s one fold down, {greeting}.</Text>
        <Text style={paragraphStyle}>
          Your first run finished. Every design was scored against the same QC
          gauntlet we use internally — pLDDT, ipSAE, ipTM, and interface metrics —
          so what you see at the top is what we&apos;d move forward ourselves.
        </Text>
        <Text style={paragraphStyle}>
          {topRankCount
            ? `${topRankCount} designs cleared our default thresholds. Open the run to inspect, filter, and export.`
            : 'Open the run to inspect, filter, and export the ranked designs.'}
        </Text>
        <CTAButton href={resultsUrl}>View your results</CTAButton>
        <Text style={subtleStyle}>— The Paper Crane team</Text>
      </Section>
    </EmailLayout>
  );
}

export default FirstJobCelebratedEmail;
