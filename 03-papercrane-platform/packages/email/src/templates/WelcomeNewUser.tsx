/**
 * Welcome email — sent on first signup.
 * Subject: "Welcome to Paper Crane — your first design is on us"
 */
import * as React from 'react';
import { Section, Text } from '@react-email/components';
import {
  CTAButton,
  EmailLayout,
  headingStyle,
  paragraphStyle,
  subtleStyle,
} from './_layout';

export interface WelcomeData {
  userName?: string;
  /** Quickstart deep link — e.g. /onboarding/first-target. */
  quickstartUrl: string;
  /** Docs link, in case they want to read first. */
  docsUrl?: string;
}

export const welcomeSubject = (_d: WelcomeData): string =>
  'Welcome to Paper Crane — your first design is on us';

export function WelcomeEmail(d: WelcomeData) {
  const name = d.userName?.trim() ? d.userName : 'there';
  const docs = d.docsUrl ?? 'https://papercrane.bio/docs';
  return (
    <EmailLayout preview="Your first binder design run is on us — pick a target to start.">
      <Section>
        <Text style={headingStyle}>Welcome, {name}.</Text>
        <Text style={paragraphStyle}>
          Paper Crane runs every modern protein binder design tool — RFdiffusion,
          BindCraft, Boltz-2, Chai-1 — under one workflow you can reproduce. We&apos;ll
          credit your account so your first run costs you nothing.
        </Text>
        <Text style={paragraphStyle}>
          Pick a PDB target, hit go, and we&apos;ll handle the GPU plumbing, the QC
          gauntlet, and the structure validation. You get back a ranked list of designs
          ready for the wet lab.
        </Text>
        <CTAButton href={d.quickstartUrl}>Run your first design</CTAButton>
        <Text style={subtleStyle}>
          Prefer to read the methodology first? <a href={docs}>The docs are here.</a>
        </Text>
      </Section>
    </EmailLayout>
  );
}
