import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { Logo } from "../src/logo";
import { colors, logoSvg } from "../src/index";

describe("Logo", () => {
  it("renders an svg with role=img", () => {
    const { container } = render(<Logo />);
    const svg = container.querySelector("svg");
    expect(svg).not.toBeNull();
    expect(svg?.getAttribute("role")).toBe("img");
  });

  it("uses the default size of 32 when not provided", () => {
    const { container } = render(<Logo />);
    const svg = container.querySelector("svg");
    expect(svg?.getAttribute("width")).toBe("32");
    expect(svg?.getAttribute("height")).toBe("32");
  });

  it("respects the size prop for mark variant", () => {
    const { container } = render(<Logo size={128} />);
    const svg = container.querySelector("svg");
    expect(svg?.getAttribute("width")).toBe("128");
    expect(svg?.getAttribute("height")).toBe("128");
  });

  it("defaults to the crane fill color", () => {
    const { container } = render(<Logo />);
    const path = container.querySelector("path");
    expect(path?.getAttribute("fill")).toBe(colors.crane);
  });

  it("accepts a custom color", () => {
    const { container } = render(<Logo color="#123456" />);
    const path = container.querySelector("path");
    expect(path?.getAttribute("fill")).toBe("#123456");
  });

  it("uses the default aria-label 'Paper Crane'", () => {
    const { getByRole } = render(<Logo />);
    expect(getByRole("img").getAttribute("aria-label")).toBe("Paper Crane");
  });

  it("supports a custom title/aria-label", () => {
    const { getByRole } = render(<Logo title="Paper Crane App" />);
    expect(getByRole("img").getAttribute("aria-label")).toBe("Paper Crane App");
  });

  it("renders a wordmark variant with text", () => {
    const { container } = render(<Logo variant="wordmark" />);
    const text = container.querySelector("text");
    expect(text?.textContent).toBe("Paper Crane");
  });

  it("renders a lockup variant with both glyph and text", () => {
    const { container } = render(<Logo variant="lockup" size={48} />);
    expect(container.querySelector("path")).not.toBeNull();
    expect(container.querySelector("text")?.textContent).toBe("Paper Crane");
  });

  it("uses viewBox 0 0 100 100 for the mark", () => {
    const { container } = render(<Logo variant="mark" />);
    const svg = container.querySelector("svg");
    expect(svg?.getAttribute("viewBox")).toBe("0 0 100 100");
  });

  it("forwards extra SVG props", () => {
    const { container } = render(<Logo className="custom-class" data-testid="logo" />);
    const svg = container.querySelector("svg");
    expect(svg?.getAttribute("class")).toBe("custom-class");
    expect(svg?.getAttribute("data-testid")).toBe("logo");
  });
});

describe("logoSvg string export", () => {
  it("is a valid SVG with viewBox 0 0 100 100", () => {
    expect(logoSvg).toContain('viewBox="0 0 100 100"');
    expect(logoSvg).toContain("<svg");
    expect(logoSvg).toContain("</svg>");
  });

  it("embeds the crane brand color", () => {
    expect(logoSvg).toContain(colors.crane);
  });
});

describe("colors export", () => {
  it("exposes all brand tokens with hex values", () => {
    expect(colors.crane).toMatch(/^#[0-9A-Fa-f]{6}$/);
    expect(colors.paper).toMatch(/^#[0-9A-Fa-f]{6}$/);
    expect(colors.ink).toMatch(/^#[0-9A-Fa-f]{6}$/);
  });
});
