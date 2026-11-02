/**
 * Invite email — sent when a member is invited to an org.
 * Subject: "<inviter> invited you to join <org>"
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

export interface InviteData {
  inviterName: string;
  orgName: string;
  role: 'viewer' | 'member' | 'admin' | 'owner';
  acceptUrl: string;
  /** Hours until the invite expires; informational. */
  expiresInHours?: number;
}

export const inviteSubject = (d: InviteData): string =>
  `${d.inviterName} invited you to join ${d.orgName}`;

export function InviteEmail(d: InviteData) {
  const expires = d.expiresInHours ?? 168;
  return (
    <EmailLayout preview={`${d.inviterName} wants you on their Paper Crane team.`}>
      <Section>
        <Text style={headingStyle}>You&apos;re invited to {d.orgName}</Text>
        <Text style={paragraphStyle}>
          <strong>{d.inviterName}</strong> added you as a <strong>{d.role}</strong> on{' '}
          <strong>{d.orgName}</strong>. Accept to start running RFdiffusion, BindCraft, and
          Boltz-2 alongside the team.
        </Text>
        <CTAButton href={d.acceptUrl}>Accept invite</CTAButton>
        <Text style={subtleStyle}>
          This link expires in {expires} hours. If the button doesn&apos;t work, paste this
          URL into your browser: {d.acceptUrl}
        </Text>
      </Section>
    </EmailLayout>
  );
}
