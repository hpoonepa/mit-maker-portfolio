/**
 * Onboarding email 1/5 — Welcome.
 * Sent: immediately after signup.
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

export const subject = 'Your binder workflow starts here.';

export interface WelcomeProps {
  name?: string;
  quickstartUrl: string;
}

export function WelcomeEmail({ name, quickstartUrl }: WelcomeProps) {
  const greeting = name?.trim() ? name : 'there';
  return (
    <EmailLayout preview="Pick a target. We handle the rest.">
      <Section>
        <Text style={headingStyle}>Welcome, {greeting}.</Text>
        <Text style={paragraphStyle}>
          Paper Crane folds the modern binder design stack — RFdiffusion, BindCraft,
          Boltz-2, Chai-1 — into a single reproducible workflow. You bring a target;
          we bring the GPUs, the QC gauntlet, and a ranked list of designs.
        </Text>
        <Text style={paragraphStyle}>
          Your first run is on the house. Pick a PDB target and watch the pipeline
          unfold.
        </Text>
        <CTAButton href={quickstartUrl}>Start your first run</CTAButton>
        <Text style={subtleStyle}>— The Paper Crane team</Text>
      </Section>
    </EmailLayout>
  );
}

export default WelcomeEmail;
