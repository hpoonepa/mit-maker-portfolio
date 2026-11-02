export type DomRange = {
  ratio: number;
  isActive: boolean;
  width: number;
  height: number;
  screenX: number;
  screenY: number;
};

export class ScrollPane {
  target = 0;
  current = 0;
  scrollPixel = 0;
  scrollView = 0;
  scrollViewDelta = 0;
  viewSizePixel = 0;
  contentSize = 1;
  isActive = true;
  contentDom: HTMLElement | null = null;

  init(opts: { contentDom: HTMLElement }): void {
    this.contentDom = opts.contentDom;
    this.recompute();
    window.addEventListener("resize", () => this.recompute());
    window.addEventListener(
      "wheel",
      (e) => {
        e.preventDefault();
        this.target += e.deltaY;
      },
      { passive: false },
    );
    this.bindTouch();
  }

  recompute(): void {
    this.viewSizePixel = window.innerHeight;
    const contentH = this.contentDom?.scrollHeight ?? this.viewSizePixel;
    this.contentSize = Math.max(0, (contentH - this.viewSizePixel) / this.viewSizePixel);
  }

  bindTouch(): void {
    let touchY = 0;
    window.addEventListener(
      "touchstart",
      (e) => {
        if (e.touches[0]) touchY = e.touches[0].clientY;
      },
      { passive: true },
    );
    window.addEventListener(
      "touchmove",
      (e) => {
        if (!e.touches[0]) return;
        const dy = touchY - e.touches[0].clientY;
        touchY = e.touches[0].clientY;
        this.target += dy;
      },
      { passive: true },
    );
  }

  update(dt: number): void {
    // Verified from Lusion's bundle: damping factor k=10 in `1 - exp(-10 * dt)`.
    const damp = 1 - Math.exp(-10 * dt);
    const prev = this.current;
    const max = this.contentSize * this.viewSizePixel;
    this.target = Math.max(0, Math.min(this.target, max));
    this.current += (this.target - this.current) * damp;
    this.scrollViewDelta = (this.current - prev) / Math.max(1, this.viewSizePixel);
    this.scrollPixel = this.current;
    this.scrollView = this.current / Math.max(1, this.viewSizePixel);
  }

  getDomRange(elem: HTMLElement): DomRange {
    const rect = elem.getBoundingClientRect();
    // Element top relative to virtual scroll position
    const top = rect.top + this.current;
    const bottom = top + rect.height;
    const viewTop = this.current;
    const viewBottom = viewTop + this.viewSizePixel;
    const overlapTop = Math.max(viewTop, top);
    const overlapBottom = Math.min(viewBottom, bottom);
    const overlapHeight = Math.max(0, overlapBottom - overlapTop);
    const isActive = overlapHeight > 0;
    const ratio = isActive
      ? Math.max(
          0,
          Math.min(1, (viewTop - top) / Math.max(1, rect.height - this.viewSizePixel)),
        )
      : 0;
    return {
      ratio,
      isActive,
      width: rect.width,
      height: overlapHeight,
      screenX: rect.left,
      screenY: overlapTop - viewTop,
    };
  }
}
