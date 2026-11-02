/**
 * Job-failed notification.
 * Subject: "Your job failed: <error>"
 */
import * as React from 'react';
import { Section, Text } from '@react-email/components';
import { colors } from '@papercrane/brand';
import {
  CTAButton,
  EmailLayout,
  headingStyle,
  paragraphStyle,
  subtleStyle,
} from './_layout';

export interface JobFailedData {
  toolChain: string;
  projectName: string;
  /** Short error headline (max ~80 chars). */
  errorHeadline: string;
  /** Optional longer message — truncated to 400 chars by the renderer. */
  errorDetail?: string;
  /** Link that pre-fills a retry with the same params. */
  retryUrl: string;
  /** Job page deep link. */
  jobUrl: string;
}

export const jobFailedSubject = (d: JobFailedData): string =>
  `Your job failed: ${d.errorHeadline.slice(0, 80)}`;

export function JobFailedEmail(d: JobFailedData) {
  const detail = d.errorDetail?.slice(0, 400);
  return (
    <EmailLayout preview={`A ${d.toolChain} run hit a snag — here's how to retry.`}>
      <Section>
        <Text style={headingStyle}>That run didn&apos;t make it</Text>
        <Text style={paragraphStyle}>
          Your <strong>{d.toolChain}</strong> run on <strong>{d.projectName}</strong>{' '}
          failed. We didn&apos;t bill you for it.
        </Text>
        <Section
          style={{
            backgroundColor: colors.paperDeep,
            border: `1px solid ${colors.lattice}`,
            borderRadius: '6px',
            fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, monospace',
            fontSize: '12px',
            lineHeight: '18px',
            margin: '16px 0',
            padding: '12px 14px',
          }}
        >
          <Text style={{ color: colors.ink, fontWeight: 600, margin: 0 }}>
            {d.errorHeadline}
          </Text>
          {detail ? (
            <Text style={{ color: colors.graphite, margin: '6px 0 0 0' }}>{detail}</Text>
          ) : null}
        </Section>
        <CTAButton href={d.retryUrl}>Retry this run</CTAButton>
        <Text style={subtleStyle}>
          Or <a href={d.jobUrl}>open the job page</a> to inspect logs and tweak parameters
          first.
        </Text>
      </Section>
    </EmailLayout>
  );
}
