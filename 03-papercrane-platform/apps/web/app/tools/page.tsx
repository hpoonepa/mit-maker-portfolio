import type { Metadata } from "next";
import { Navbar } from "@/components/Navbar";
import { Footer } from "@/components/sections/Footer";
import { PublicToolCatalog } from "@/components/PublicToolCatalog";
import { PUBLIC_TOOL_CATALOG } from "@/lib/tool-catalog";
import { pageMetadata } from "@/lib/metadata";

export const metadata: Metadata = pageMetadata({
  title: "Tool catalog",
  description: "Browse all 52 protein design, prediction, sequence, and scoring tools in the Paper Crane catalog.",
  path: "/tools",
  ogTitle: "The Paper Crane tool catalog",
  ogDesc: "52 version-pinned protein tools, one reproducible workflow.",
});

export default function ToolsPage() {
  return (
    <>
      <Navbar />
      <main id="main-content" tabIndex={-1} className="relative pt-28 md:pt-32">
        <div className="container-edge pb-24">
          <header className="mb-14 max-w-3xl">
            <span className="eyebrow">§ The catalog</span>
            <h1 className="mt-5 font-display text-display-lg leading-[0.95] text-ink">Every tool. One workflow.</h1>
            <p className="mt-6 max-w-2xl text-[17px] leading-[1.6] text-graphite">
              The complete Paper Crane catalog, synced from the same version-pinned manifests that power the platform. GA and beta readiness are shown explicitly; catalog-only tools stay visible without pretending they are runnable.
            </p>
            <p className="mt-5 font-mono text-[11px] uppercase tracking-[0.2em] text-graphite-soft">
              {PUBLIC_TOOL_CATALOG.length} tools · {PUBLIC_TOOL_CATALOG.filter((tool) => tool.status === "ga").length} GA · {PUBLIC_TOOL_CATALOG.filter((tool) => tool.status === "beta").length} beta
            </p>
          </header>
          <PublicToolCatalog />
        </div>
      </main>
      <Footer />
    </>
  );
}
