import type { ReactElement, ReactNode } from "react";
import { Children, isValidElement, cloneElement } from "react";
import Link from "next/link";
import { Navbar } from "@/components/Navbar";
import { Footer } from "@/components/sections/Footer";
import { Reveal } from "@/components/Reveal";

/**
 * Shared chrome for legal pages (Terms, Privacy, Cookie).
 * Keeps typography, spacing, and "back to home" affordance consistent.
 *
 * Adds:
 *  - prominent "Effective" date pill (mono, bordered)
 *  - sticky table-of-contents sidebar built from <h2> children
 *  - auto-generated section anchor ids on every <h2>
 *  - reading-width control via the .legal-prose class
 */

function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^\w\s-]/g, "")
    .trim()
    .replace(/\s+/g, "-")
    .slice(0, 60);
}

function nodeToText(node: ReactNode): string {
  if (node === null || node === undefined || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(nodeToText).join("");
  if (isValidElement(node)) {
    const props = node.props as { children?: ReactNode };
    return nodeToText(props.children);
  }
  return "";
}

type TocItem = { id: string; label: string };

/**
 * Walk children, give every <h2> a stable id, collect the toc list.
 * We mutate by cloning — children are not consumed elsewhere.
 */
function buildTocAndAnnotate(
  children: ReactNode,
): { toc: TocItem[]; annotated: ReactNode } {
  const toc: TocItem[] = [];
  const seen = new Set<string>();

  const annotated = Children.map(children, (child, index) => {
    if (!isValidElement(child)) return child;
    if (child.type === "h2") {
      const el = child as ReactElement<{
        id?: string;
        children?: ReactNode;
        className?: string;
      }>;
      const text = nodeToText(el.props.children);
      let id = el.props.id ?? slugify(text);
      if (!id) id = `section-${index}`;
      let unique = id;
      let n = 2;
      while (seen.has(unique)) unique = `${id}-${n++}`;
      seen.add(unique);
      toc.push({ id: unique, label: text });
      return cloneElement(el, { id: unique });
    }
    return child;
  });

  return { toc, annotated };
}

export function LegalLayout({
  eyebrow,
  title,
  effective,
  intro,
  children,
}: {
  eyebrow: string;
  title: string;
  effective: string;
  intro?: ReactNode;
  children: ReactNode;
}) {
  const { toc, annotated } = buildTocAndAnnotate(children);

  return (
    <>
      <Navbar />
      <main
        id="main-content"
        tabIndex={-1}
        className="relative pt-32 md:pt-40 [&_h2]:scroll-mt-28"
      >
        <section className="container-edge pb-24">
          <Reveal>
            <div className="flex items-baseline gap-4 mb-10">
              <span className="eyebrow">{eyebrow}</span>
              <span className="hairline flex-1" />
            </div>

            <div className="flex flex-wrap items-end justify-between gap-6">
              <h1 className="font-display text-[clamp(40px,6vw,72px)] leading-[1.05] text-ink">
                {title}
              </h1>
              <div
                className="inline-flex items-center gap-2 border border-ink/15 px-3 py-1.5 font-mono text-[11px] tracking-[0.22em] uppercase text-ink"
                aria-label={`Effective date ${effective}`}
              >
                <span className="h-1.5 w-1.5 rounded-full bg-crane-deep" aria-hidden />
                Effective <time dateTime={effective}>{effective}</time>
              </div>
            </div>

            {intro ? (
              <div className="mt-6 max-w-[62ch] text-graphite text-[17px] leading-relaxed">
                {intro}
              </div>
            ) : null}
          </Reveal>

          {toc.length > 1 ? (
            <details className="mt-10 lg:hidden border border-ink/15 bg-paper/60 [&_summary::-webkit-details-marker]:hidden">
              <summary className="flex items-center justify-between cursor-pointer list-none px-4 py-3 font-mono text-[11px] tracking-[0.22em] uppercase text-ink">
                <span>On this page · {toc.length} sections</span>
                <span aria-hidden className="text-graphite-soft">+</span>
              </summary>
              <ol className="px-4 pb-4 space-y-1.5 text-[14px] leading-snug border-t border-ink/10 pt-3">
                {toc.map((item) => (
                  <li key={item.id}>
                    <a
                      href={`#${item.id}`}
                      className="block py-1 text-graphite hover:text-ink"
                    >
                      {item.label}
                    </a>
                  </li>
                ))}
              </ol>
            </details>
          ) : null}

          <div className="mt-12 grid gap-12 lg:grid-cols-[220px_minmax(0,1fr)]">
            {toc.length > 1 ? (
              <aside className="hidden lg:block">
                <nav
                  aria-label="On this page"
                  className="sticky top-32 max-h-[calc(100vh-10rem)] overflow-y-auto pr-2"
                >
                  <div className="font-mono text-[10px] tracking-[0.24em] uppercase text-graphite-soft mb-3">
                    On this page
                  </div>
                  <ol className="space-y-1.5 text-[13px] leading-snug border-l border-ink/10">
                    {toc.map((item) => (
                      <li key={item.id}>
                        <a
                          href={`#${item.id}`}
                          className="block -ml-px border-l border-transparent pl-3 py-0.5 text-graphite hover:border-crane-deep hover:text-ink transition-colors"
                        >
                          {item.label}
                        </a>
                      </li>
                    ))}
                  </ol>
                </nav>
              </aside>
            ) : null}

            <article className="legal-prose max-w-[72ch] text-ink/90">
              {annotated}
            </article>
          </div>

          <div className="mt-16 flex flex-wrap items-center gap-x-6 gap-y-3 text-sm text-graphite-soft">
            <a
              href="#main-content"
              className="font-mono text-[11px] tracking-[0.18em] uppercase text-ink/70 hover:text-ink"
            >
              ↑ Back to top
            </a>
            <span aria-hidden className="h-3 w-px bg-ink/15" />
            <Link
              href="/"
              className="underline decoration-crane-deep/40 underline-offset-4 hover:text-ink"
            >
              Home
            </Link>
            <Link
              href="/terms"
              className="underline decoration-crane-deep/40 underline-offset-4 hover:text-ink"
            >
              Terms
            </Link>
            <Link
              href="/privacy"
              className="underline decoration-crane-deep/40 underline-offset-4 hover:text-ink"
            >
              Privacy
            </Link>
            <Link
              href="/cookie-policy"
              className="underline decoration-crane-deep/40 underline-offset-4 hover:text-ink"
            >
              Cookies
            </Link>
            <Link
              href="/privacy-choices"
              className="underline decoration-crane-deep/40 underline-offset-4 hover:text-ink"
            >
              Privacy choices
            </Link>
            <Link
              href="/contact"
              className="underline decoration-crane-deep/40 underline-offset-4 hover:text-ink"
            >
              Contact
            </Link>
          </div>
        </section>
      </main>
      <Footer />
    </>
  );
}
