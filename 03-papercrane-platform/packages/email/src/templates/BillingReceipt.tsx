/**
 * Monthly billing receipt — sent after Stripe invoice.paid.
 * Subject: "Paper Crane receipt — <month> <year>"
 */
import * as React from 'react';
import { Section, Text } from '@react-email/components';
import { colors } from '@papercrane/brand';
import { CTAButton, EmailLayout, headingStyle, paragraphStyle, subtleStyle } from './_layout';

export interface BillingLineItem {
  label: string;
  /** USD amount in dollars (already converted from Stripe cents). */
  amountUsd: number;
}

export interface BillingReceiptData {
  /** "March 2026" */
  periodLabel: string;
  /** Org being billed. */
  orgName: string;
  /** Stripe-hosted invoice URL. */
  invoiceUrl: string;
  /** Stripe-hosted PDF download. */
  invoicePdfUrl?: string;
  lineItems: BillingLineItem[];
  totalUsd: number;
  /** Last 4 digits of card charged. */
  cardLast4?: string;
}

export const billingReceiptSubject = (d: BillingReceiptData): string =>
  `Paper Crane receipt — ${d.periodLabel}`;

const fmtUsd = (n: number): string =>
  `$${n.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',')}`;

export function BillingReceiptEmail(d: BillingReceiptData) {
  return (
    <EmailLayout preview={`${d.periodLabel} receipt for ${d.orgName} — ${fmtUsd(d.totalUsd)}.`}>
      <Section>
        <Text style={headingStyle}>{d.periodLabel} receipt</Text>
        <Text style={paragraphStyle}>
          Thanks for using Paper Crane. Here&apos;s what <strong>{d.orgName}</strong> ran
          this month.
        </Text>

        <table
          cellPadding={0}
          cellSpacing={0}
          width="100%"
          style={{
            borderCollapse: 'collapse',
            margin: '16px 0',
          }}
        >
          <tbody>
            {d.lineItems.map((li, i) => (
              <tr key={`${li.label}-${i}`}>
                <td
                  style={{
                    borderBottom: `1px solid ${colors.lattice}`,
                    color: colors.inkSoft,
                    fontSize: '14px',
                    padding: '10px 0',
                  }}
                >
                  {li.label}
                </td>
                <td
                  align="right"
                  style={{
                    borderBottom: `1px solid ${colors.lattice}`,
                    color: colors.ink,
                    fontFamily:
                      'ui-monospace, SFMono-Regular, Menlo, Monaco, monospace',
                    fontSize: '14px',
                    padding: '10px 0',
                  }}
                >
                  {fmtUsd(li.amountUsd)}
                </td>
              </tr>
            ))}
            <tr>
              <td
                style={{
                  color: colors.ink,
                  fontSize: '15px',
                  fontWeight: 600,
                  padding: '14px 0 0 0',
                }}
              >
                Total
              </td>
              <td
                align="right"
                style={{
                  color: colors.ink,
                  fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, monospace',
                  fontSize: '15px',
                  fontWeight: 600,
                  padding: '14px 0 0 0',
                }}
              >
                {fmtUsd(d.totalUsd)}
              </td>
            </tr>
          </tbody>
        </table>

        {d.cardLast4 ? (
          <Text style={subtleStyle}>Charged to card ending in {d.cardLast4}.</Text>
        ) : null}

        <CTAButton href={d.invoiceUrl}>View full invoice</CTAButton>

        {d.invoicePdfUrl ? (
          <Text style={subtleStyle}>
            Need a PDF? <a href={d.invoicePdfUrl}>Download from Stripe</a>.
          </Text>
        ) : null}
      </Section>
    </EmailLayout>
  );
}
