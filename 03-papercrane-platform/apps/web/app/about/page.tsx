import type { Metadata } from "next";
import { Navbar } from "@/components/Navbar";
import { Footer } from "@/components/sections/Footer";
import { Reveal } from "@/components/Reveal";
import { pageMetadata } from "@/lib/metadata";
import { breadcrumbJsonLd, jsonLdString } from "@/lib/structured-data";

const TITLE = "About";
const DESCRIPTION =
  "Paper Crane is the workflow layer for computational protein design. Built by iGEM grand-jamboree winners, advised by faculty at MIT, UCLA, and UPenn.";

export const metadata: Metadata = pageMetadata({
  title: TITLE,
  description: DESCRIPTION,
  path: "/about",
  ogTitle: "About",
  ogDesc: "Built by iGEM. Advised by MIT, UCLA, UPenn.",
});

const BREADCRUMBS = [
  { name: "Home", path: "/" },
  { name: "About", path: "/about" },
];

const founders = [
  {
    name: "Harsha Poonepalle",
    role: "Co-founder · Eng",
    location: "Lambert HS, GA · Class of 2027",
    bio: "iGEM co-captain, 2025 international winner. Wrote the original Mosaic pipeline — Protenix2025 → Modal/Vast.ai batch → Boltz2 → ipSAE/DockQ filtering — and ran the 50-seed campaigns it now schedules. Builds in public.",
  },
  {
    name: "Vedant Kalipatnapu",
    role: "Co-founder · Bio",
    location: "Lambert HS, GA · Class of 2027",
    bio: "iGEM co-captain, 2025 international winner. Wet-lab lead. The reason any of our designs actually express, fold, and bind on the bench.",
  },
];

// LOIs on file from MIT, UCLA, UPenn. Specific advisor names withheld
// until each has approved public listing. Do NOT replace placeholders
// with names unless the professor has signed off in writing.
const advisors = [
  {
    name: "MIT · Faculty advisor",
    affiliation: "Department of Biological Engineering",
    bio: "LOI on file. Public listing pending permission.",
    /* TODO: replace with named advisor once written approval received */
  },
  {
    name: "UCLA · Faculty advisor",
    affiliation: "Department of Bioengineering",
    bio: "LOI on file · computational protein design and de novo binders. Public listing pending permission.",
    /* TODO: replace with named advisor once written approval received */
  },
  {
    name: "UPenn · Faculty advisor",
    affiliation: "School of Engineering & Applied Science",
    bio: "LOI on file · structural biology and ML for biomolecules. Public listing pending permission.",
    /* TODO: replace with named advisor once written approval received */
  },
  {
    name: "Advisor seat · open",
    affiliation: "Industry · biotech / ML",
    bio: "Reserved for an operator who has shipped a therapeutic or a platform. Intros welcome.",
  },
];

const press = [
  {
    label: "iGEM Grand Jamboree · International Winners (Lambert GA, 2025)",
    href: "https://2025.igem.wiki/lambert-ga/",
  },
  {
    label: "YC S26 · Candidate",
    href: "mailto:hello@papercrane.bio?subject=Paper%20Crane%20YC%20press",
  },
  {
    label: "Press kit · logos, brand, founder photos",
    href: "mailto:press@papercrane.bio?subject=Paper%20Crane%20press%20kit",
  },
];

export default function AboutPage() {
  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: jsonLdString(breadcrumbJsonLd(BREADCRUMBS)) }}
      />
      <Navbar />
      <main id="main-content" tabIndex={-1} className="relative pt-32 md:pt-40">
        {/* Hero */}
        <section className="container-edge pb-16">
          <Reveal>
            <div className="mb-6 font-mono text-[10px] tracking-[0.22em] uppercase text-crane">
              <span className="inline-block h-1.5 w-1.5 rounded-full bg-crane mr-2 align-middle animate-pulse" />
              Beta launch · 2026-04-30
            </div>
          </Reveal>
          <Reveal>
            <div className="flex items-baseline gap-4 mb-10">
              <span className="eyebrow">§ About · Paper Crane</span>
              <span className="h-px flex-1 bg-lattice" />
              <span className="font-mono text-[10px] tracking-[0.2em] uppercase text-crane">
                YC S26
              </span>
            </div>
          </Reveal>

          <div className="grid lg:grid-cols-12 gap-10 items-end">
            <Reveal delay={1} className="lg:col-span-8">
              <h1 className="font-display text-display-xl balance leading-[0.92]">
                A thousand seeds,{" "}
                <em className="italic font-normal text-crane">
                  one binder that binds.
                </em>
              </h1>
            </Reveal>
            <Reveal delay={2} className="lg:col-span-4">
              <p className="font-sans text-[17px] leading-[1.55] text-graphite max-w-md">
                Two high-schoolers from Georgia, three faculty letters
                of intent, and one workflow we wrote because nothing
                else got us a binder before the wet-lab window closed.
              </p>
            </Reveal>
          </div>
        </section>

        {/* Senbazuru — the origin story */}
        <section className="py-section">
          <div className="container-edge">
            <Reveal>
              <div className="flex items-baseline gap-4 mb-12">
                <span className="eyebrow">§ Senbazuru</span>
                <span className="h-px flex-1 bg-lattice" />
                <span className="font-mono text-[10px] tracking-[0.2em] uppercase text-graphite-soft">
                  千羽鶴
                </span>
              </div>
            </Reveal>
            <div className="grid lg:grid-cols-12 gap-10">
              <Reveal delay={1} className="lg:col-span-5">
                <p className="font-mono text-[11px] tracking-[0.18em] uppercase text-graphite-soft mb-6">
                  The name
                </p>
                <p className="font-sans text-[16px] leading-[1.65] text-ink-soft max-w-md">
                  Japanese legend: fold a thousand paper cranes and you
                  are granted one wish. In our pipeline a thousand
                  seeded designs yield, on a good week, one binder that
                  actually binds. The math rhymes. So does the patience.
                </p>
                <p className="mt-6 font-sans text-[16px] leading-[1.65] text-ink-soft max-w-md">
                  Origami isn&rsquo;t a metaphor either. Erik Demaine
                  (MIT) proved paper-folding is computationally
                  equivalent to protein folding — both are flat sheets
                  searching for a single low-energy 3D shape. The crane
                  is also an East Asian symbol of healing. Therapeutics
                  are the end state.
                </p>
              </Reveal>
              <Reveal delay={2} className="lg:col-span-7 lg:pl-8 lg:border-l border-lattice">
                <blockquote className="font-display italic text-[34px] md:text-[44px] leading-[1.1] tracking-tight text-ink balance">
                  &ldquo;A thousand folds for one wish. A thousand
                  seeds{" "}
                  <span className="text-crane not-italic font-normal">
                    for one binder.
                  </span>{" "}
                  The patience is the product.&rdquo;
                </blockquote>
                <div className="mt-8 font-mono text-[10px] tracking-[0.22em] uppercase text-graphite-soft">
                  — paper crane, founders&rsquo; note
                </div>
              </Reveal>
            </div>
          </div>
        </section>

        {/* Why Paper Crane */}
        <section className="py-section bg-paper-fold">
          <div className="container-edge">
            <Reveal>
              <div className="flex items-baseline gap-4 mb-12">
                <span className="eyebrow">§ Why Paper Crane</span>
                <span className="h-px flex-1 bg-lattice" />
              </div>
            </Reveal>
            <div className="grid lg:grid-cols-12 gap-10">
              <Reveal delay={1} className="lg:col-span-4">
                <h2 className="font-display text-[36px] md:text-[44px] leading-[1.05] balance">
                  Designed,{" "}
                  <em className="italic font-normal text-graphite">
                    not discovered.
                  </em>
                </h2>
              </Reveal>
              <div className="lg:col-span-8 space-y-6 font-sans text-[17px] leading-[1.65] text-ink-soft max-w-2xl">
                <Reveal delay={2}>
                  <p>
                    We spent a full iGEM season running ProteinMPNN,
                    RFdiffusion, and BindCraft against the same target — by
                    hand, one seed at a time, on three different clusters with
                    three different broken Conda envs. We lost weekends to
                    CUDA mismatches before we shipped a single binder that
                    bound. The tools were all there. The workflow wasn&rsquo;t.
                  </p>
                </Reveal>
                <Reveal delay={3}>
                  <p>
                    Paper Crane is that workflow. Every major tool, behind one
                    API, with one cost meter and one pre-registered scoring
                    pipeline. You bring a target. We hand you ranked binders.
                    Free for academics, $299/mo for labs, custom for pharma.
                    No Conda. No bash for-loops. No three-day debugging
                    sessions over a CUDA version mismatch.
                  </p>
                </Reveal>
                <Reveal delay={4}>
                  <p>
                    The next generation of therapeutics will be{" "}
                    <em className="italic font-display text-ink">designed</em>,
                    not discovered. The platform underneath should be as
                    elegant as the proteins it builds. That&rsquo;s the only
                    thing we&rsquo;re trying to make true.
                  </p>
                </Reveal>
              </div>
            </div>
          </div>
        </section>

        {/* Founders */}
        <section className="py-section">
          <div className="container-edge">
            <Reveal>
              <div className="flex items-baseline gap-4 mb-8">
                <span className="eyebrow">§ Founders</span>
                <span className="h-px flex-1 bg-lattice" />
              </div>
            </Reveal>
            <Reveal delay={1}>
              <div className="mb-12 hairline-border bg-paper-fold rounded-sm px-6 py-5 max-w-2xl">
                <div className="font-mono text-[10px] tracking-[0.22em] uppercase text-crane mb-2">
                  We&rsquo;re beta-launching today
                </div>
                <p className="font-sans text-[15px] leading-[1.6] text-ink-soft">
                  Paper Crane opens to a small cohort of academic labs on
                  2026-04-30. If your wet-lab window is closing, write to{" "}
                  <a href="mailto:hello@papercrane.bio" className="text-ink underline decoration-lattice-strong underline-offset-4 hover:text-crane">
                    hello@papercrane.bio
                  </a>{" "}
                  — we&rsquo;ll get you a seat.
                </p>
              </div>
            </Reveal>
            <div className="grid md:grid-cols-2 gap-8">
              {founders.map((p, i) => (
                <Reveal key={p.name} delay={(i + 1) as 1 | 2}>
                  <div className="hairline-border bg-paper rounded-sm p-8 h-full flex flex-col">
                    <div className="font-mono text-[10px] tracking-[0.22em] uppercase text-crane mb-4">
                      {p.role}
                    </div>
                    {/* TODO: founder portrait — square 1:1, B/W or duotone, no stock selfies */}
                    <div className="aspect-square w-32 mb-6 border border-lattice bg-paper-fold flex items-center justify-center">
                      <span className="font-mono text-[9px] tracking-[0.2em] uppercase text-graphite-soft">
                        portrait
                      </span>
                    </div>
                    <div className="font-display text-[32px] leading-[1.1] tracking-tight">
                      {p.name}
                    </div>
                    <div className="mt-2 font-mono text-[10px] tracking-[0.18em] uppercase text-graphite-soft">
                      {p.location}
                    </div>
                    <p className="mt-4 font-sans text-[15px] leading-[1.6] text-ink-soft">
                      {p.bio}
                    </p>
                  </div>
                </Reveal>
              ))}
            </div>
          </div>
        </section>

        {/* Advisors */}
        <section className="py-section">
          <div className="container-edge">
            <Reveal>
              <div className="flex items-baseline gap-4 mb-12">
                <span className="eyebrow">§ Advisors</span>
                <span className="h-px flex-1 bg-lattice" />
              </div>
            </Reveal>
            <div className="grid md:grid-cols-2 gap-6">
              {advisors.map((a, i) => (
                <Reveal key={a.name} delay={((i % 4) + 1) as 1 | 2 | 3 | 4}>
                  <div className="border-l-2 border-lattice-strong pl-6 py-2">
                    <div className="font-mono text-[10px] tracking-[0.22em] uppercase text-graphite mb-2">
                      {a.affiliation}
                    </div>
                    <div className="font-display text-[22px] leading-[1.15]">
                      {a.name}
                    </div>
                    <p className="mt-2 font-sans text-[14px] leading-[1.6] text-ink-soft max-w-md">
                      {a.bio}
                    </p>
                  </div>
                </Reveal>
              ))}
            </div>
          </div>
        </section>

        {/* Press / Contact */}
        <section className="py-section bg-paper-fold">
          <div className="container-edge">
            <Reveal>
              <div className="flex items-baseline gap-4 mb-12">
                <span className="eyebrow">§ Press · Contact</span>
                <span className="h-px flex-1 bg-lattice" />
              </div>
            </Reveal>

            <div className="grid lg:grid-cols-12 gap-10">
              <Reveal delay={1} className="lg:col-span-6">
                <h2 className="font-display text-display-md balance leading-[0.98]">
                  Get in{" "}
                  <em className="italic font-normal text-crane">touch.</em>
                </h2>
                <ul className="mt-8 space-y-4">
                  {press.map((p) => (
                    <li key={p.label}>
                      <a
                        href={p.href}
                        className="group flex items-baseline justify-between border-b border-lattice py-3 hover:border-ink transition-colors"
                      >
                        <span className="font-sans text-[16px] text-ink">
                          {p.label}
                        </span>
                        <span className="font-mono text-[10px] tracking-[0.22em] uppercase text-graphite group-hover:text-crane transition-colors">
                          ↗
                        </span>
                      </a>
                    </li>
                  ))}
                </ul>
              </Reveal>

              <Reveal delay={2} className="lg:col-span-6">
                <div className="hairline-border bg-paper rounded-sm p-8 space-y-5">
                  <Contact label="General"   email="hello@papercrane.bio" />
                  <Contact label="Sales"     email="sales@papercrane.bio" />
                  <Contact label="Press"     email="press@papercrane.bio" />
                  <Contact label="Security"  email="security@papercrane.bio" />
                  <Contact label="Benchmark" email="benchmark@papercrane.bio" />
                </div>
              </Reveal>
            </div>
          </div>
        </section>
      </main>
      <Footer />
    </>
  );
}

function Contact({ label, email }: { label: string; email: string }) {
  return (
    <div className="grid grid-cols-[120px_1fr] items-baseline border-b border-lattice/60 pb-4 last:border-b-0 last:pb-0">
      <span className="font-mono text-[10px] tracking-[0.22em] uppercase text-graphite-soft">
        {label}
      </span>
      <a
        href={`mailto:${email}`}
        className="font-sans text-[15px] text-ink hover:text-crane transition-colors"
      >
        {email}
      </a>
    </div>
  );
}
