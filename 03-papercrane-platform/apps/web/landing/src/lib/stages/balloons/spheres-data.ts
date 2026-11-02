// Floating torn-paper hero. Single kind, three size variants for visual variety.

export type StructureKind = "paper";
export type PaperVariant = "small" | "medium" | "large";

export type StructureSpec = {
  name: string;
  kind: StructureKind;
  variant: PaperVariant;
  radius: number;
  density: number;
  friction: number;
  restitution: number;
  color: string;
  isColored: boolean;
  isRough: boolean;
  isBlackWhite: boolean;
  sss: number;
  isSemitransparent: boolean;
};

const FANCY = "fancy";
const CREAM = "#efe6cd";
const INK = "#181410";
const PHYSICS = { density: 1, friction: 2, restitution: 0.2 };
const R = 1.1;

function s(
  name: string,
  variant: PaperVariant,
  color: string,
  isColored: boolean,
): StructureSpec {
  return {
    name,
    kind: "paper",
    variant,
    radius: R,
    ...PHYSICS,
    color,
    isColored,
    isRough: true,
    isBlackWhite: !isColored,
    sss: 0,
    isSemitransparent: false,
  };
}

// 36 sheets total. ~10 fancy / 14 cream / 12 ink.
export const SPHERES_DATA: StructureSpec[] = [
  // small (12)
  s("paper-s-fancy-a", "small", FANCY, true),
  s("paper-s-fancy-b", "small", FANCY, true),
  s("paper-s-fancy-c", "small", FANCY, true),
  s("paper-s-cream-a", "small", CREAM, false),
  s("paper-s-cream-b", "small", CREAM, false),
  s("paper-s-cream-c", "small", CREAM, false),
  s("paper-s-cream-d", "small", CREAM, false),
  s("paper-s-cream-e", "small", CREAM, false),
  s("paper-s-ink-a", "small", INK, false),
  s("paper-s-ink-b", "small", INK, false),
  s("paper-s-ink-c", "small", INK, false),
  s("paper-s-ink-d", "small", INK, false),
  // medium (14)
  s("paper-m-fancy-a", "medium", FANCY, true),
  s("paper-m-fancy-b", "medium", FANCY, true),
  s("paper-m-fancy-c", "medium", FANCY, true),
  s("paper-m-fancy-d", "medium", FANCY, true),
  s("paper-m-cream-a", "medium", CREAM, false),
  s("paper-m-cream-b", "medium", CREAM, false),
  s("paper-m-cream-c", "medium", CREAM, false),
  s("paper-m-cream-d", "medium", CREAM, false),
  s("paper-m-cream-e", "medium", CREAM, false),
  s("paper-m-ink-a", "medium", INK, false),
  s("paper-m-ink-b", "medium", INK, false),
  s("paper-m-ink-c", "medium", INK, false),
  s("paper-m-ink-d", "medium", INK, false),
  s("paper-m-ink-e", "medium", INK, false),
  // large (10)
  s("paper-l-fancy-a", "large", FANCY, true),
  s("paper-l-fancy-b", "large", FANCY, true),
  s("paper-l-fancy-c", "large", FANCY, true),
  s("paper-l-cream-a", "large", CREAM, false),
  s("paper-l-cream-b", "large", CREAM, false),
  s("paper-l-cream-c", "large", CREAM, false),
  s("paper-l-cream-d", "large", CREAM, false),
  s("paper-l-ink-a", "large", INK, false),
  s("paper-l-ink-b", "large", INK, false),
  s("paper-l-ink-c", "large", INK, false),
];

export { SPHERES_DATA as STRUCTURES_DATA };
export type { StructureSpec as BalloonSpec, PaperVariant as HelixVariant };
