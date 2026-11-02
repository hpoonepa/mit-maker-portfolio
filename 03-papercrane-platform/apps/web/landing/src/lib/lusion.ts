/**
 * Paper Crane × Lusion — interaction layer.
 *
 * Adds a custom cursor, scroll-driven reveals, magnetic CTAs, soft 3-D tilt on
 * cards, parallax on the hero crane, and a marquee duplicator. All effects are
 * disabled if the user prefers reduced motion or on touch devices (where they
 * become noise).
 */

const lerp = (a: number, b: number, t: number): number => a + (b - a) * t;

/* ─────────────────────────────────────────────
   Custom cursor — small dot + lerping ring
   ───────────────────────────────────────────── */

class Cursor {
  private dot: HTMLElement | null;
  private ring: HTMLElement | null;
  private mx = 0;
  private my = 0;
  private rx = 0;
  private ry = 0;
  private visible = false;

  constructor() {
    this.dot = document.querySelector(".cursor__dot");
    this.ring = document.querySelector(".cursor__ring");
    if (!this.dot || !this.ring) return;

    document.body.classList.add("cursor-on");
    window.addEventListener("mousemove", this.onMove, { passive: true });
    window.addEventListener("mouseleave", () => this.setVisible(false));
    window.addEventListener("mouseenter", () => this.setVisible(true));

    const triggers = document.querySelectorAll<HTMLElement>(
      'a, button, input, [data-cursor="hover"]'
    );
    triggers.forEach((el) => {
      el.addEventListener("mouseenter", () => this.setActive(true));
      el.addEventListener("mouseleave", () => this.setActive(false));
    });

    requestAnimationFrame(this.tick);
  }

  private setVisible(on: boolean) {
    this.visible = on;
    this.dot?.classList.toggle("is-visible", on);
    this.ring?.classList.toggle("is-visible", on);
  }

  private setActive(on: boolean) {
    this.ring?.classList.toggle("is-active", on);
  }

  private onMove = (e: MouseEvent) => {
    this.mx = e.clientX;
    this.my = e.clientY;
    if (!this.visible) this.setVisible(true);
  };

  private tick = () => {
    this.rx = lerp(this.rx, this.mx, 0.18);
    this.ry = lerp(this.ry, this.my, 0.18);
    if (this.dot)
      this.dot.style.transform = `translate3d(${this.mx}px, ${this.my}px, 0)`;
    if (this.ring)
      this.ring.style.transform = `translate3d(${this.rx}px, ${this.ry}px, 0)`;
    requestAnimationFrame(this.tick);
  };
}

/* ─────────────────────────────────────────────
   Reveal — fade + translate as elements enter
   ───────────────────────────────────────────── */

class Reveal {
  constructor() {
    const targets = document.querySelectorAll<HTMLElement>("[data-reveal]");
    if (!targets.length) return;
    const obs = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          entry.target.classList.add("is-revealed");
          obs.unobserve(entry.target);
        });
      },
      { threshold: 0.08, rootMargin: "0px 0px -8% 0px" }
    );
    targets.forEach((el) => obs.observe(el));
  }
}

/* ─────────────────────────────────────────────
   Magnetic — buttons that pull toward cursor
   ───────────────────────────────────────────── */

class Magnetic {
  constructor() {
    document
      .querySelectorAll<HTMLElement>("[data-magnetic]")
      .forEach((node) => this.bind(node));
  }

  private bind(node: HTMLElement) {
    let raf = 0;
    let tx = 0;
    let ty = 0;
    let x = 0;
    let y = 0;
    const strength = parseFloat(node.dataset.magnetic || "0.3");

    const tick = () => {
      x = lerp(x, tx, 0.18);
      y = lerp(y, ty, 0.18);
      node.style.transform = `translate3d(${x.toFixed(2)}px, ${y.toFixed(2)}px, 0)`;
      if (Math.abs(x - tx) > 0.05 || Math.abs(y - ty) > 0.05) {
        raf = requestAnimationFrame(tick);
      } else {
        node.style.transform = `translate3d(${tx}px, ${ty}px, 0)`;
        raf = 0;
      }
    };

    node.addEventListener("mousemove", (e) => {
      const rect = node.getBoundingClientRect();
      tx = (e.clientX - rect.left - rect.width / 2) * strength;
      ty = (e.clientY - rect.top - rect.height / 2) * strength;
      if (!raf) raf = requestAnimationFrame(tick);
    });

    node.addEventListener("mouseleave", () => {
      tx = 0;
      ty = 0;
      if (!raf) raf = requestAnimationFrame(tick);
    });
  }
}

/* ─────────────────────────────────────────────
   Tilt — soft 3-D lean on cards
   ───────────────────────────────────────────── */

class Tilt {
  constructor() {
    document
      .querySelectorAll<HTMLElement>("[data-tilt]")
      .forEach((node) => this.bind(node));
  }

  private bind(node: HTMLElement) {
    const max = parseFloat(node.dataset.tilt || "5");
    let raf = 0;
    let tx = 0;
    let ty = 0;
    let x = 0;
    let y = 0;
    const baseTransform = getComputedStyle(node).transform;
    const baseRotate = parseRotate(baseTransform);

    const apply = () => {
      const rxBase = baseRotate.deg;
      node.style.transform = `${
        baseRotate.has ? `rotate(${rxBase}deg) ` : ""
      }perspective(1100px) rotateX(${y.toFixed(2)}deg) rotateY(${x.toFixed(2)}deg)`;
    };

    const tick = () => {
      x = lerp(x, tx, 0.16);
      y = lerp(y, ty, 0.16);
      apply();
      if (Math.abs(x - tx) > 0.03 || Math.abs(y - ty) > 0.03) {
        raf = requestAnimationFrame(tick);
      } else {
        raf = 0;
      }
    };

    node.addEventListener("mousemove", (e) => {
      const rect = node.getBoundingClientRect();
      const px = (e.clientX - rect.left) / rect.width;
      const py = (e.clientY - rect.top) / rect.height;
      tx = (px - 0.5) * max * 2;
      ty = -(py - 0.5) * max * 2;
      if (!raf) raf = requestAnimationFrame(tick);
    });

    node.addEventListener("mouseleave", () => {
      tx = 0;
      ty = 0;
      if (!raf) raf = requestAnimationFrame(tick);
    });
  }
}

const parseRotate = (t: string): { has: boolean; deg: number } => {
  // detect a base rotation set in CSS so we don't fight the random res-card tilt
  const m = t.match(/matrix\(([^)]+)\)/);
  if (!m) return { has: false, deg: 0 };
  const [a, b] = m[1].split(",").map(parseFloat);
  const deg = (Math.atan2(b, a) * 180) / Math.PI;
  return { has: Math.abs(deg) > 0.05, deg };
};

/* ─────────────────────────────────────────────
   Hero parallax — crane drifts as you scroll
   ───────────────────────────────────────────── */

class HeroParallax {
  private crane: HTMLElement | null;
  private headline: HTMLElement | null;
  private hero: HTMLElement | null;
  private raf = 0;

  constructor() {
    this.crane = document.querySelector(".hero__crane");
    this.headline = document.querySelector(".hero__inner");
    this.hero = document.querySelector(".hero");
    if (!this.hero) return;
    window.addEventListener("scroll", this.schedule, { passive: true });
    this.tick();
  }

  private schedule = () => {
    if (this.raf) return;
    this.raf = requestAnimationFrame(this.tick);
  };

  private tick = () => {
    if (!this.hero) return;
    const rect = this.hero.getBoundingClientRect();
    const progress = Math.max(0, -rect.top / rect.height);
    if (this.crane) {
      this.crane.style.transform = `translate3d(${progress * 80}px, ${
        progress * -120
      }px, 0) scale(${1 + progress * 0.06})`;
    }
    if (this.headline) {
      this.headline.style.transform = `translate3d(0, ${progress * -40}px, 0)`;
      this.headline.style.opacity = String(Math.max(0, 1 - progress * 1.4));
    }
    this.raf = 0;
  };
}

/* ─────────────────────────────────────────────
   Marquee — duplicate chip rows for seamless loop
   ───────────────────────────────────────────── */

class Marquee {
  constructor() {
    document
      .querySelectorAll<HTMLElement>("[data-marquee]")
      .forEach((node) => {
        const inner = node.firstElementChild as HTMLElement | null;
        if (!inner) return;
        const clone = inner.cloneNode(true) as HTMLElement;
        clone.setAttribute("aria-hidden", "true");
        node.appendChild(clone);
      });
  }
}

/* ─────────────────────────────────────────────
   Number count-up — animates digits in [data-counter] when in view
   ───────────────────────────────────────────── */

class CountUp {
  constructor() {
    const targets = document.querySelectorAll<HTMLElement>("[data-counter]");
    if (!targets.length) return;
    const obs = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          this.run(entry.target as HTMLElement);
          obs.unobserve(entry.target);
        });
      },
      { threshold: 0.5 }
    );
    targets.forEach((t) => obs.observe(t));
  }

  private run(el: HTMLElement) {
    const original = el.textContent || "";
    const matches = original.match(/(\d+)/g);
    if (!matches) return;
    const targets = matches.map((m) => parseInt(m, 10));
    const duration = 1300;
    const start = performance.now();
    const ease = (t: number) => 1 - Math.pow(1 - t, 3);

    const tick = (now: number) => {
      const t = Math.min((now - start) / duration, 1);
      const eased = ease(t);
      let i = 0;
      const out = original.replace(/\d+/g, () => {
        const target = targets[i++];
        return String(Math.round(target * eased));
      });
      el.textContent = out;
      if (t < 1) requestAnimationFrame(tick);
      else el.textContent = original;
    };
    requestAnimationFrame(tick);
  }
}

/* ─────────────────────────────────────────────
   Thesis ladder parallax — each big line drifts at slightly diff speed
   ───────────────────────────────────────────── */

class LadderParallax {
  private lines: HTMLElement[] = [];
  private raf = 0;

  constructor() {
    this.lines = Array.from(
      document.querySelectorAll<HTMLElement>(
        ".thesis__line-1, .thesis__line-2, .thesis__line-3"
      )
    );
    if (!this.lines.length) return;
    window.addEventListener("scroll", this.schedule, { passive: true });
    this.tick();
  }

  private schedule = () => {
    if (this.raf) return;
    this.raf = requestAnimationFrame(this.tick);
  };

  private tick = () => {
    this.raf = 0;
    if (!this.lines.length) return;
    const ref = this.lines[0].getBoundingClientRect();
    const center = ref.top + ref.height / 2 - window.innerHeight / 2;
    const norm = -center / window.innerHeight; // ~ -0.5..0.5
    const speeds = [0.2, 0.4, 0.7];
    this.lines.forEach((line, i) => {
      line.style.transform = `translate3d(0, ${(norm * speeds[i] * 80).toFixed(2)}px, 0)`;
    });
  };
}

/* ─────────────────────────────────────────────
   Bar chart draw-in
   ───────────────────────────────────────────── */

class BarReveal {
  constructor() {
    const bars = document.querySelectorAll<HTMLElement>("[data-bar]");
    if (!bars.length) return;
    const obs = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          const el = entry.target as HTMLElement;
          requestAnimationFrame(() => {
            el.style.width = el.dataset.bar || "0%";
          });
          obs.unobserve(el);
        });
      },
      { threshold: 0.4 }
    );
    bars.forEach((bar) => obs.observe(bar));
  }
}

/* ─────────────────────────────────────────────
   Hero ambient glow — radial gradient lerps toward cursor
   ───────────────────────────────────────────── */

class HeroGlow {
  private hero: HTMLElement | null;
  private mx = 50;
  private my = 50;
  private cx = 50;
  private cy = 50;
  private active = false;

  constructor() {
    this.hero = document.querySelector(".hero");
    if (!this.hero) return;
    const onMove = (e: MouseEvent) => {
      const rect = this.hero!.getBoundingClientRect();
      this.mx = ((e.clientX - rect.left) / rect.width) * 100;
      this.my = ((e.clientY - rect.top) / rect.height) * 100;
      this.active = true;
    };
    this.hero.addEventListener("mousemove", onMove, { passive: true });
    this.hero.addEventListener("mouseleave", () => {
      this.active = false;
      this.mx = 50;
      this.my = 50;
    });
    requestAnimationFrame(this.tick);
  }

  private tick = () => {
    this.cx = lerp(this.cx, this.mx, 0.06);
    this.cy = lerp(this.cy, this.my, 0.06);
    if (this.hero) {
      this.hero.style.setProperty("--mx", `${this.cx.toFixed(2)}%`);
      this.hero.style.setProperty("--my", `${this.cy.toFixed(2)}%`);
    }
    requestAnimationFrame(this.tick);
  };
}

/* ─────────────────────────────────────────────
   Surface spotlight — feeds --mx/--my to cards and form panels
   ───────────────────────────────────────────── */

class SurfaceSpotlight {
  constructor() {
    document
      .querySelectorAll<HTMLElement>(
        ".tool-card, .tier, .person, .chart-card, .stat-card, .qslip, .terminal, .waitlist-form, .compliance"
      )
      .forEach((node) => this.bind(node));
  }

  private bind(node: HTMLElement) {
    node.addEventListener(
      "pointermove",
      (event) => {
        const rect = node.getBoundingClientRect();
        const x = ((event.clientX - rect.left) / rect.width) * 100;
        const y = ((event.clientY - rect.top) / rect.height) * 100;
        node.style.setProperty("--mx", `${x.toFixed(2)}%`);
        node.style.setProperty("--my", `${y.toFixed(2)}%`);
      },
      { passive: true }
    );
  }
}

/* ─────────────────────────────────────────────
   Section position indicator — right-edge dots
   ───────────────────────────────────────────── */

class SectionTracker {
  private rail: HTMLElement | null = null;
  private dots: HTMLElement[] = [];
  private sections: HTMLElement[] = [];
  private active = -1;
  private raf = 0;

  constructor() {
    // Support both the new .rail and the legacy .tracker container names.
    this.rail =
      document.querySelector<HTMLElement>(".rail") ??
      document.querySelector<HTMLElement>(".tracker");
    if (!this.rail) return;

    this.dots = Array.from(
      this.rail.querySelectorAll<HTMLElement>(".rail__dot, .tracker__dot")
    );
    this.sections = this.dots
      .map((d) => document.querySelector<HTMLElement>(`#${d.dataset.target}`))
      .filter((s): s is HTMLElement => s != null);

    this.dots.forEach((dot, i) => {
      dot.addEventListener("click", () => {
        this.sections[i]?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });

    // Pin each dot's --y value to its target section's relative position in
    // the page so the dots sit on the rail at the same scroll percentage as
    // their section. Recompute on resize since layout can shift.
    this.layoutDots();
    window.addEventListener("resize", () => this.layoutDots(), { passive: true });

    window.addEventListener("scroll", this.schedule, { passive: true });
    this.tick();
  }

  private layoutDots = () => {
    const docH = document.documentElement.scrollHeight - window.innerHeight;
    if (docH <= 0) return;
    this.dots.forEach((dot, i) => {
      const sec = this.sections[i];
      if (!sec) return;
      // Use the section's mid-height position; clamp to [0.02, 0.98] so dots
      // never sit flush against the rail caps.
      const offset = sec.offsetTop + sec.offsetHeight * 0.4;
      const y = Math.max(0.02, Math.min(0.98, offset / docH));
      dot.style.setProperty("--y", String(y));
    });
  };

  private schedule = () => {
    if (this.raf) return;
    this.raf = requestAnimationFrame(this.tick);
  };

  private tick = () => {
    this.raf = 0;
    const docH = document.documentElement.scrollHeight - window.innerHeight;
    const progress = docH > 0 ? Math.max(0, Math.min(1, window.scrollY / docH)) : 0;

    // Drive the rail's CSS variable so the crane translates and the brushy
    // progress stroke draws.
    if (this.rail) this.rail.style.setProperty("--rail-progress", progress.toFixed(4));

    // Active section: whichever section's top has crossed the 40% line.
    const mid = window.innerHeight * 0.4;
    let active = 0;
    this.sections.forEach((s, i) => {
      const rect = s.getBoundingClientRect();
      if (rect.top <= mid) active = i;
    });
    if (active !== this.active) {
      this.active = active;
      this.dots.forEach((d, i) => d.classList.toggle("is-active", i === active));
      // Surface the active section onto the rail for the compact readout
      // (data-num / data-name drive the .rail::after "02 · THESIS" label).
      const ad = this.dots[active];
      if (ad && this.rail) {
        this.rail.setAttribute("data-num", ad.dataset.num ?? "");
        this.rail.setAttribute("data-name", ad.dataset.name ?? "");
      }
    }
  };
}

/* ─────────────────────────────────────────────
   Word-stagger reveal — splits into masked words
   ───────────────────────────────────────────── */

class SplitReveal {
  constructor() {
    const targets = document.querySelectorAll<HTMLElement>("[data-split-reveal]");
    if (!targets.length) return;

    targets.forEach((el) => this.split(el));

    const obs = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          entry.target.classList.add("is-revealed");
          obs.unobserve(entry.target);
        });
      },
      { threshold: 0.15, rootMargin: "0px 0px -8% 0px" }
    );
    targets.forEach((el) => obs.observe(el));
  }

  private split(el: HTMLElement) {
    const text = el.textContent?.trim() ?? "";
    if (!text) return;
    el.textContent = "";
    const words = text.split(/\s+/);
    words.forEach((word, i) => {
      const wrap = document.createElement("span");
      wrap.className = "word";
      const inner = document.createElement("span");
      inner.style.setProperty("--i", String(i));
      inner.textContent = word;
      wrap.appendChild(inner);
      el.appendChild(wrap);
      el.appendChild(document.createTextNode(" "));
    });
  }
}

/* ─────────────────────────────────────────────
   Hamburger menu — full-screen overlay
   ───────────────────────────────────────────── */

class MenuOverlay {
  private toggle: HTMLButtonElement | null;
  private overlay: HTMLElement | null;
  private items: HTMLLIElement[];
  private open = false;

  constructor() {
    this.toggle = document.querySelector(".menu-toggle");
    this.overlay = document.querySelector(".menu-overlay");
    this.items = Array.from(
      document.querySelectorAll<HTMLLIElement>(".menu-overlay__list li")
    );
    if (!this.toggle || !this.overlay) return;

    this.items.forEach((li, i) => li.style.setProperty("--i", String(i)));

    this.toggle.addEventListener("click", () => this.setOpen(!this.open));

    this.overlay.querySelectorAll("a").forEach((a) => {
      a.addEventListener("click", () => this.setOpen(false));
    });

    window.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && this.open) this.setOpen(false);
    });
  }

  private setOpen(open: boolean) {
    if (!this.toggle || !this.overlay) return;
    this.open = open;
    this.toggle.setAttribute("aria-expanded", String(open));
    this.toggle.setAttribute("aria-label", open ? "Close menu" : "Open menu");
    this.overlay.classList.toggle("is-open", open);
    this.overlay.setAttribute("aria-hidden", String(!open));
    if (open) this.overlay.removeAttribute("inert");
    else this.overlay.setAttribute("inert", "");
    document.body.classList.toggle("menu-locked", open);
  }
}

/* ─────────────────────────────────────────────
   ScrollPath — SVG <path> stroke draws with scroll progress
   (vanilla port of framer-motion useScroll + stroke-dashoffset)
   ───────────────────────────────────────────── */

class ScrollPath {
  private targets: { path: SVGPathElement; host: HTMLElement; length: number }[] = [];
  private raf = 0;

  constructor() {
    // Defer measurement to next frame: getTotalLength() and host layout
    // need rendered geometry, not just parsed DOM.
    requestAnimationFrame(() => this.setup());
  }

  private setup() {
    const paths = document.querySelectorAll<SVGPathElement>("[data-scroll-path]");
    paths.forEach((path) => {
      const host = (path.closest<HTMLElement>("[data-scroll-host]") ?? path) as HTMLElement;
      const length = path.getTotalLength();
      if (!length) return;
      path.style.strokeDasharray = String(length);
      path.style.strokeDashoffset = String(length);
      this.targets.push({ path, host, length });
    });
    if (!this.targets.length) return;
    window.addEventListener("scroll", this.schedule, { passive: true });
    window.addEventListener("resize", this.schedule, { passive: true });
    this.tick();
  }

  private schedule = () => {
    if (this.raf) return;
    this.raf = requestAnimationFrame(this.tick);
  };

  private tick = () => {
    this.raf = 0;
    const vh = window.innerHeight;
    for (const { path, host, length } of this.targets) {
      const rect = host.getBoundingClientRect();
      // 0 when host top is at vh (just entering), 1 when host bottom passed top
      const total = rect.height + vh;
      const seen = vh - rect.top;
      const p = Math.max(0, Math.min(1, seen / total));
      path.style.strokeDashoffset = String(length * (1 - p));
    }
  };
}

/* ─────────────────────────────────────────────
   ScrollScale — perspective rotateX + scale on scroll-in
   (vanilla port of framer-motion useScroll + transform)
   ───────────────────────────────────────────── */

class ScrollScale {
  private targets: HTMLElement[] = [];
  private raf = 0;

  constructor() {
    this.targets = Array.from(
      document.querySelectorAll<HTMLElement>("[data-scroll-scale]")
    );
    if (!this.targets.length) return;
    this.targets.forEach((el) => {
      el.style.transformStyle = "preserve-3d";
      el.style.willChange = "transform";
    });
    window.addEventListener("scroll", this.schedule, { passive: true });
    window.addEventListener("resize", this.schedule, { passive: true });
    this.tick();
  }

  private schedule = () => {
    if (this.raf) return;
    this.raf = requestAnimationFrame(this.tick);
  };

  private tick = () => {
    this.raf = 0;
    const vh = window.innerHeight;
    for (const el of this.targets) {
      const rect = el.getBoundingClientRect();
      // Trigger thresholds are configurable per-element via data attrs:
      //   data-scroll-scale-start   — start factor (× vh). Default 1.0 means
      //                                animation kicks in as soon as the
      //                                element top reaches viewport bottom.
      //                                Lower values delay the start (e.g.
      //                                0.55 = wait until element top is past
      //                                the lower half of the viewport).
      //   data-scroll-scale-end     — end factor (× vh). Default 0.3.
      const startFactor = parseFloat(el.dataset.scrollScaleStart ?? "1");
      const endFactor = parseFloat(el.dataset.scrollScaleEnd ?? "0.3");
      const start = vh * startFactor;
      const end = vh * endFactor;
      const raw = (start - rect.top) / (start - end);
      const p = Math.max(0, Math.min(1, raw));
      const ease = 1 - Math.pow(1 - p, 3);

      const rotateX = 18 * (1 - ease);
      const scale = 0.94 + 0.06 * ease;
      const ty = 40 * (1 - ease);
      el.style.transform = `perspective(1400px) translate3d(0, ${ty.toFixed(
        2
      )}px, 0) rotateX(${rotateX.toFixed(2)}deg) scale(${scale.toFixed(3)})`;
    }
  };
}

/* ─────────────────────────────────────────────
   TapeDrop — tape strips slide down as note cards enter the viewport
   ───────────────────────────────────────────── */

class TapeDrop {
  private targets: { tape: HTMLElement; host: HTMLElement }[] = [];
  private raf = 0;

  constructor() {
    this.targets = Array.from(
      document.querySelectorAll<HTMLElement>(
        ".qslip__tape, .slip__tape, .pullquote__tape"
      )
    )
      .map((tape) => {
        const host =
          tape.closest<HTMLElement>(".qslip, .slip, .pullquote") ??
          tape.parentElement;
        return host ? { tape, host } : null;
      })
      .filter((target): target is { tape: HTMLElement; host: HTMLElement } =>
        Boolean(target)
      );

    if (!this.targets.length) return;
    window.addEventListener("scroll", this.schedule, { passive: true });
    window.addEventListener("resize", this.schedule, { passive: true });
    this.tick();
  }

  private schedule = () => {
    if (this.raf) return;
    this.raf = requestAnimationFrame(this.tick);
  };

  private tick = () => {
    this.raf = 0;
    const vh = window.innerHeight;
    const start = vh * 0.92;
    const end = vh * 0.42;

    for (const { tape, host } of this.targets) {
      const rect = host.getBoundingClientRect();
      const raw = (start - rect.top) / (start - end);
      const p = Math.max(0, Math.min(1, raw));
      const eased = 1 - Math.pow(1 - p, 3);
      tape.style.setProperty("--tape-drop", `${(-18 + eased * 18).toFixed(2)}px`);
    }
  };
}

/* ─────────────────────────────────────────────
   Scroll state — toggle body.is-scrolled for nav fade
   ───────────────────────────────────────────── */

class ScrollState {
  constructor() {
    let raf = 0;
    const update = () => {
      raf = 0;
      document.body.classList.toggle("is-scrolled", window.scrollY > 32);
    };
    window.addEventListener(
      "scroll",
      () => {
        if (raf) return;
        raf = requestAnimationFrame(update);
      },
      { passive: true }
    );
    update();
  }
}

/* ─────────────────────────────────────────────
   Page load fade
   ───────────────────────────────────────────── */

const onReady = () => {
  document.body.classList.add("is-ready");
  requestAnimationFrame(() => {
    requestAnimationFrame(() => document.body.classList.add("is-loaded"));
  });
};

/* ─────────────────────────────────────────────
   Init
   ───────────────────────────────────────────── */

export function initLusion(): void {
  if (typeof window === "undefined") return;
  const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const isFinePointer = matchMedia("(pointer: fine)").matches;

  // Reveal + marquee + menu + split + page fade run for everyone.
  new Reveal();
  new SplitReveal();
  new Marquee();
  new BarReveal();
  new CountUp();
  new MenuOverlay();
  new SectionTracker();
  new ScrollState();

  if (!reduceMotion) {
    void import("./shader-polish").then(({ initShaderPolish }) => {
      initShaderPolish();
    });
    new ScrollPath();
    new ScrollScale();
    new TapeDrop();
  }

  if (isFinePointer) new SurfaceSpotlight();

  if (!reduceMotion && isFinePointer) {
    new Magnetic();
    new Tilt();
    new HeroGlow();
    new LadderParallax();
  }

  if (document.readyState === "complete") onReady();
  else window.addEventListener("load", onReady, { once: true });
}
