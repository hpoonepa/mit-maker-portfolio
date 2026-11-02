/**
 * Onboarding email 4/5 — Two week tips.
 * Sent: 14 days after signup.
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

export const subject = 'Three patterns power users follow.';

export interface Week2Props {
  name?: string;
  patternsUrl: string;
}

export function Week2TipsEmail({ name, patternsUrl }: Week2Props) {
  const greeting = name?.trim() ? name : 'there';
  return (
    <EmailLayout preview="Three things the heaviest users do differently.">
      <Section>
        <Text style={headingStyle}>Two weeks in, {greeting}.</Text>
        <Text style={paragraphStyle}>
          Three habits separate fast campaigns from slow ones. First, set hotspots
          before you generate — the QC gauntlet rewards intent. Second, run BindCraft
          and RFdiffusion in parallel, then merge by ipSAE. Third, validate with
          Boltz-2 before ordering: it catches the false positives that ipTM misses.
        </Text>
        <CTAButton href={patternsUrl}>See the patterns guide</CTAButton>
        <Text style={subtleStyle}>— The Paper Crane team</Text>
      </Section>
    </EmailLayout>
  );
}

export default Week2TipsEmail;
