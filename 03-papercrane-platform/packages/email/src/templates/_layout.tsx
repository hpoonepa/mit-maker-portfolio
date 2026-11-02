/**
 * Shared email layout — header (crane mark + wordmark), body slot, footer.
 *
 * All styling is inline (object literals -> style={...}) because most email
 * clients strip <style> tags and class selectors. We import design tokens
 * from @papercrane/brand so emails track the rest of the product.
 *
 * Width is locked to 560px (Litmus / Gmail / Outlook safe band). The "paper"
 * surface uses the same off-white as the app, with a thin lattice hairline
 * mimicking the marketing site's grid overlay.
 */
import * as React from 'react';
import {
  Body,
  Container,
  Head,
  Hr,
  Html,
  Img,
  Link,
  Preview,
  Section,
  Text,
} from '@react-email/components';
import { brand, colors, logoSvg } from '@papercrane/brand';

export interface LayoutProps {
  /** Short, single-line preview pulled into inbox row by Gmail/Apple Mail. */
  preview: string;
  /** Optional override for the unsubscribe URL (transactional defaults to settings page). */
  unsubscribeUrl?: string;
  children: React.ReactNode;
}

const PAPER_CRANE_ADDRESS = 'Paper Crane Bio, Inc. - 2261 Market St #4848, San Francisco, CA 94114';

/** Inline-encoded SVG so no external image fetches are required. */
const cranePngFallback = `data:image/svg+xml;utf8,${encodeURIComponent(logoSvg)}`;

const layoutStyles = {
  body: {
    backgroundColor: colors.paperFold,
    fontFamily:
      '-apple-system, BlinkMacSystemFont, "Segoe UI", "Helvetica Neue", Arial, sans-serif',
    margin: 0,
    padding: '24px 0',
    color: colors.ink,
  },
  container: {
    backgroundColor: colors.paper,
    border: `1px solid ${colors.paperDeep}`,
    borderRadius: '8px',
    margin: '0 auto',
    maxWidth: '560px',
    padding: '32px',
  },
  header: {
    paddingBottom: '24px',
  },
  brandRow: {
    display: 'flex',
    alignItems: 'center',
  },
  logo: {
    height: '36px',
    width: '36px',
    verticalAlign: 'middle',
  },
  wordmark: {
    color: colors.ink,
    fontSize: '18px',
    fontWeight: 600 as const,
    letterSpacing: '-0.01em',
    margin: '0 0 0 12px',
    verticalAlign: 'middle',
    display: 'inline-block' as const,
  },
  rule: {
    borderColor: colors.lattice,
    borderTopWidth: '1px',
    margin: '24px 0',
  },
  footer: {
    color: colors.graphiteSoft,
    fontSize: '12px',
    lineHeight: '18px',
    paddingTop: '24px',
  },
  footerLink: {
    color: colors.graphite,
    textDecoration: 'underline',
  },
};

export function EmailLayout({ preview, unsubscribeUrl, children }: LayoutProps) {
  const unsubHref = unsubscribeUrl ?? 'https://app.papercrane.bio/settings/notifications';
  return (
    <Html lang="en">
      <Head />
      <Preview>{preview}</Preview>
      <Body style={layoutStyles.body}>
        <Container style={layoutStyles.container}>
          <Section style={layoutStyles.header}>
            <table cellPadding={0} cellSpacing={0} style={layoutStyles.brandRow}>
              <tbody>
                <tr>
                  <td>
                    <Img
                      src={cranePngFallback}
                      alt="Paper Crane"
                      width={36}
                      height={36}
                      style={layoutStyles.logo}
                    />
                  </td>
                  <td>
                    <Text style={layoutStyles.wordmark}>{brand.name}</Text>
                  </td>
                </tr>
              </tbody>
            </table>
          </Section>

          {children}

          <Hr style={layoutStyles.rule} />

          <Section style={layoutStyles.footer}>
            <Text style={{ margin: 0, color: colors.graphiteSoft }}>
              You&apos;re getting this because you have a Paper Crane account.{' '}
              <Link href={unsubHref} style={layoutStyles.footerLink}>
                Unsubscribe or change preferences
              </Link>
              .
            </Text>
            <Text style={{ margin: '8px 0 0 0', color: colors.graphiteSoft }}>
              {PAPER_CRANE_ADDRESS}
            </Text>
          </Section>
        </Container>
      </Body>
    </Html>
  );
}

/** Reusable button — email-safe, falls back to a styled anchor in plain clients. */
export function CTAButton(props: { href: string; children: React.ReactNode }) {
  return (
    <table cellPadding={0} cellSpacing={0} style={{ margin: '24px 0' }}>
      <tbody>
        <tr>
          <td
            align="center"
            style={{
              backgroundColor: colors.crane,
              borderRadius: '6px',
              padding: '12px 20px',
            }}
          >
            <Link
              href={props.href}
              style={{
                color: colors.paper,
                fontSize: '14px',
                fontWeight: 600,
                textDecoration: 'none',
              }}
            >
              {props.children}
            </Link>
          </td>
        </tr>
      </tbody>
    </table>
  );
}

/** Heading used inside template bodies. */
export const headingStyle: React.CSSProperties = {
  color: colors.ink,
  fontFamily: 'Georgia, "Times New Roman", serif',
  fontSize: '24px',
  fontWeight: 600,
  letterSpacing: '-0.01em',
  lineHeight: '32px',
  margin: '0 0 12px 0',
};

/** Body text. */
export const paragraphStyle: React.CSSProperties = {
  color: colors.inkSoft,
  fontSize: '15px',
  lineHeight: '22px',
  margin: '0 0 12px 0',
};

/** Muted helper line. */
export const subtleStyle: React.CSSProperties = {
  color: colors.graphite,
  fontSize: '13px',
  lineHeight: '20px',
  margin: '12px 0 0 0',
};
