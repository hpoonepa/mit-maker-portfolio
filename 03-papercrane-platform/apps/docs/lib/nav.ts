export type NavItem = { title: string; href: string };
export type NavSection = { title: string; items: NavItem[] };

export const NAV: NavSection[] = [
  {
    title: "Start",
    items: [
      { title: "Overview", href: "/" },
      { title: "Getting started", href: "/getting-started" },
      { title: "Quickstart", href: "/quickstart" },
    ],
  },
  {
    title: "Concepts",
    items: [
      { title: "Projects & targets", href: "/concepts/projects-and-targets" },
      { title: "Jobs & pipelines", href: "/concepts/jobs-and-pipelines" },
      { title: "Designs & metrics", href: "/concepts/designs-and-metrics" },
    ],
  },
  {
    title: "Tools",
    items: [
      { title: "Catalog", href: "/tools" },
      { title: "RFdiffusion", href: "/tools/rfdiffusion" },
      { title: "BindCraft", href: "/tools/bindcraft" },
      { title: "Boltz-2", href: "/tools/boltz2" },
      { title: "AlphaFold 3", href: "/tools/alphafold3" },
      { title: "ESM-2", href: "/tools/esm2" },
    ],
  },
  {
    title: "API",
    items: [
      { title: "Overview", href: "/api" },
      { title: "Authentication", href: "/api/auth" },
      { title: "Seeds", href: "/api/seeds" },
      { title: "Webhooks", href: "/api/webhooks" },
    ],
  },
  {
    title: "Account",
    items: [
      { title: "Billing", href: "/billing" },
      { title: "FAQ", href: "/faq" },
    ],
  },
];
