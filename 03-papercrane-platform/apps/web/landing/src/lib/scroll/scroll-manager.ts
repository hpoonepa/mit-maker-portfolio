import { ScrollPane } from "./scroll-pane";
import { properties } from "../properties";

export class ScrollManager extends ScrollPane {
  domScrollIndicator: HTMLElement | null = null;
  domScrollIndicatorBar: HTMLElement | null = null;
  domScrollIndicatorHeight = 1;
  easedScrollStrength = 0;
  scrollIndicatorActiveRatio = 0;
  lastMouseInteractiveTime = -Infinity;
  isIndicatorActive = false;
  // Verified from Lusion's bundle: minimum bar scale Y.
  MIN_BAR_SCALE_Y = 0.2;

  init(opts: {
    contentDom: HTMLElement;
    domScrollIndicator?: HTMLElement | null;
    domScrollIndicatorBar?: HTMLElement | null;
  }): void {
    super.init({ contentDom: opts.contentDom });
    this.domScrollIndicator = opts.domScrollIndicator ?? null;
    this.domScrollIndicatorBar = opts.domScrollIndicatorBar ?? null;
    if (this.domScrollIndicator) {
      this.domScrollIndicatorHeight = this.domScrollIndicator.getBoundingClientRect().height;
    }
  }

  update(dt: number): void {
    super.update(dt);

    this.easedScrollStrength += Math.abs(this.scrollViewDelta);
    this.easedScrollStrength += (0 - this.easedScrollStrength) * (1 - Math.exp(-10 * dt));
    this.easedScrollStrength = Math.min(this.easedScrollStrength, 1);

    if (Math.abs(this.scrollViewDelta) > 1e-4) {
      this.lastMouseInteractiveTime = properties.time;
      this.isIndicatorActive = true;
    } else if (properties.time > this.lastMouseInteractiveTime + 0.5) {
      this.isIndicatorActive = false;
    }
    this.scrollIndicatorActiveRatio = Math.max(
      0,
      Math.min(1, this.scrollIndicatorActiveRatio + (this.isIndicatorActive ? 2 : -2) * dt),
    );

    if (this.domScrollIndicator) {
      this.domScrollIndicator.style.opacity = String(this.scrollIndicatorActiveRatio);
    }

    if (this.domScrollIndicatorBar && this.contentSize > 0) {
      const barScale = Math.max(this.MIN_BAR_SCALE_Y, 1 / (1 + this.contentSize));
      const barPos = (this.scrollView / this.contentSize) * (1 - barScale);
      this.domScrollIndicatorBar.style.height = `${this.domScrollIndicatorHeight * barScale}px`;
      this.domScrollIndicatorBar.style.transform = `translate3d(0, ${this.domScrollIndicatorHeight * barPos}px, 0)`;
    }
  }
}

export const scrollManager = new ScrollManager();
