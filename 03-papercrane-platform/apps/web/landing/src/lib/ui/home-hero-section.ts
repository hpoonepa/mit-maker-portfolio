import SplitType from "split-type";
import { math, ease } from "../math";
import { properties } from "../properties";

export class HomeHeroSection {
  domHomeTitle: HTMLElement | null = null;
  domScrollCue: HTMLElement | null = null;
  splitWords: HTMLElement[] = [];
  scrollWords: HTMLElement[] = [];
  startTime = 0;
  initialized = false;

  init(): void {
    this.domHomeTitle = document.getElementById("home-hero-title");
    this.domScrollCue = document.getElementById("home-hero-scroll");

    if (this.domHomeTitle) {
      const split = new SplitType(this.domHomeTitle, { types: "lines, words" });
      for (const line of split.lines ?? []) {
        const el = line as HTMLElement;
        el.style.position = "relative";
        el.style.overflow = "hidden";
      }
      this.splitWords = (split.words ?? []) as HTMLElement[];
      for (const word of this.splitWords) {
        word.style.display = "inline-block";
        word.style.transform = "translate3d(0, 1.7em, 0) rotate(15deg)";
        word.style.transformOrigin = "left bottom";
      }
    }

    if (this.domScrollCue) {
      const split = new SplitType(this.domScrollCue, { types: "words" });
      this.scrollWords = (split.words ?? []) as HTMLElement[];
      for (const w of this.scrollWords) {
        w.style.display = "inline-block";
        w.style.transform = "scale(0)";
      }
    }

    this.startTime = properties.time;
    this.initialized = true;
  }

  update(): void {
    if (!this.initialized) return;
    const t = Math.max(0, properties.time - this.startTime - 0.3);

    for (let r = 0; r < this.splitWords.length; r++) {
      const word = this.splitWords[r];
      const a = t - r / 20;
      const ty = math.fit(a, 0, 1, 1.7, 0, ease.lusion);
      const rot = math.fit(a, 0, 0.7, 15, 0, ease.lusion);
      word.style.transform = `translate3d(0, ${ty}em, 0) rotate(${rot}deg)`;
    }

    for (let r = 0; r < this.scrollWords.length; r++) {
      const word = this.scrollWords[r];
      const a = math.fit(t - 0.6 - r / 10, 0, 0.6, 0, 1, ease.lusion);
      word.style.transform = `scale(${a})`;
    }
  }
}
