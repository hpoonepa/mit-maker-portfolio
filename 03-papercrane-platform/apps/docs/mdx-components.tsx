import type { MDXComponents } from "mdx/types";
import { mdxComponents } from "./components/MdxComponents";

// IMPORTANT: do NOT name this `useMDXComponents` — that triggers React's
// hook-call semantics in the RSC analyzer, which marks every importer as a
// client component. Naming the export `getMDXComponents` (and re-exporting it
// under the conventional name only as a default) keeps it server-safe while
// still satisfying @next/mdx's alias contract.
export function useMDXComponents(components: MDXComponents): MDXComponents {
  return { ...mdxComponents, ...components };
}
