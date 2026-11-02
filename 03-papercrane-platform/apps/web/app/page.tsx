import type { Metadata } from "next";
import { Navbar } from "@/components/Navbar";
import { Hero } from "@/components/sections/Hero";
import { PressStrip } from "@/components/sections/PressStrip";
import { Problem } from "@/components/sections/Problem";
import { HowItWorks } from "@/components/sections/HowItWorks";
import { Tools } from "@/components/sections/Tools";
import { Benchmark } from "@/components/sections/Benchmark";
import { Pricing } from "@/components/sections/Pricing";
import { About } from "@/components/sections/About";
import { FAQ } from "@/components/sections/FAQ";
import { CTA } from "@/components/sections/CTA";
import { Footer } from "@/components/sections/Footer";
import { canonicalUrl } from "@/lib/metadata";

export const metadata: Metadata = {
  // Title intentionally omitted: the layout default reads
  // "Paper Crane — Every protein design tool. One workflow." which is the
  // canonical home title. Setting it here would inject the template suffix.
  alternates: { canonical: canonicalUrl("/") },
};

export default function HomePage() {
  return (
    <>
      <Navbar />
      <main id="main-content" tabIndex={-1} className="relative">
        <Hero />
        <PressStrip />
        <Problem />
        <HowItWorks />
        <Tools />
        <Benchmark />
        <Pricing />
        <About />
        <FAQ />
        <CTA />
      </main>
      <Footer />
    </>
  );
}
