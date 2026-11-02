/**
 * Job-complete notification.
 * Subject: "Your <tool_chain> job for <project> finished — N designs"
 */
import * as React from 'react';
import { Img, Section, Text } from '@react-email/components';
import { colors } from '@papercrane/brand';
import {
  CTAButton,
  EmailLayout,
  headingStyle,
  paragraphStyle,
  subtleStyle,
} from './_layout';

export interface JobCompleteData {
  toolChain: string;
  projectName: string;
  /** Total designs produced (after QC). */
  designCount: number;
  /** Wall-clock runtime, human-formatted (e.g. "12m 34s"). */
  runtime: string;
  /** Top design preview thumbnail (PNG/JPG URL or data URI). Optional. */
  topThumbnailUrl?: string;
  /** Top design metric headline (e.g. "iPSAE 0.89"). */
  topMetric?: string;
  /** Deep link to the job page in the app. */
  jobUrl: string;
  /** Deep link to the designs gallery filtered by this job. */
  designsUrl: string;
}

export const jobCompleteSubject = (d: JobCompleteData): string =>
  `Your ${d.toolChain} job for ${d.projectName} finished — ${d.designCount} design${
    d.designCount === 1 ? '' : 's'
  }`;

export function JobCompleteEmail(d: JobCompleteData) {
  return (
    <EmailLayout
      preview={`${d.designCount} new designs from ${d.toolChain} are ready to review.`}
    >
      <Section>
        <Text style={headingStyle}>Your designs are ready</Text>
        <Text style={paragraphStyle}>
          The <strong>{d.toolChain}</strong> chain on <strong>{d.projectName}</strong> just
          wrapped — {d.designCount} design{d.designCount === 1 ? '' : 's'} survived QC in{' '}
          {d.runtime}.
        </Text>

        {d.topThumbnailUrl ? (
          <Section
            style={{
              backgroundColor: colors.paperFold,
              border: `1px solid ${colors.lattice}`,
              borderRadius: '6px',
              margin: '16px 0',
              padding: '16px',
              textAlign: 'center' as const,
            }}
          >
            <Img
              src={d.topThumbnailUrl}
              alt="Top design preview"
              width={240}
              height={160}
              style={{
                borderRadius: '4px',
                display: 'block',
                margin: '0 auto',
              }}
            />
            {d.topMetric ? (
              <Text
                style={{
                  color: colors.graphite,
                  fontSize: '12px',
                  margin: '8px 0 0 0',
                }}
              >
                Top hit: {d.topMetric}
              </Text>
            ) : null}
          </Section>
        ) : null}

        <CTAButton href={d.designsUrl}>Open designs gallery</CTAButton>

        <Text style={subtleStyle}>
          Want the raw run logs and metrics? <a href={d.jobUrl}>View the full job page</a>.
        </Text>
      </Section>
    </EmailLayout>
  );
}
