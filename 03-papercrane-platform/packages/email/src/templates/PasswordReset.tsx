/**
 * Password reset email — single-use link, expires in 1 hour.
 * Subject: "Reset your Paper Crane password"
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

export interface PasswordResetData {
  /** Display name; falls back to "there" if undefined. */
  userName?: string;
  resetUrl: string;
  expiresInMinutes?: number;
}

export const passwordResetSubject = (_d: PasswordResetData): string =>
  'Reset your Paper Crane password';

export function PasswordResetEmail(d: PasswordResetData) {
  const expires = d.expiresInMinutes ?? 60;
  const name = d.userName?.trim() ? d.userName : 'there';
  return (
    <EmailLayout preview="Reset your password — link expires soon.">
      <Section>
        <Text style={headingStyle}>Reset your password</Text>
        <Text style={paragraphStyle}>
          Hey {name} — someone (hopefully you) asked to reset the password on your Paper
          Crane account. Click below to choose a new one.
        </Text>
        <CTAButton href={d.resetUrl}>Choose new password</CTAButton>
        <Text style={subtleStyle}>
          This link works once and expires in {expires} minutes. Didn&apos;t request this?
          Ignore this email — your password stays the same.
        </Text>
      </Section>
    </EmailLayout>
  );
}
