export const VIEWER_BACKGROUND = 0x0b1711;
export const TARGET_COLOR = 0xb3c8bc;
export const BINDER_COLOR = 0x91d3a3;
export const HOTSPOT_COLOR = 0xe2bd65;
const CHAIN_COLORS = [
  BINDER_COLOR,
  0x90bce0,
  0xdfbf86,
  0xc6a4db,
  0xe6aaa4,
  0x91d6cd,
];

export function chainColor(
  index: number,
  chainId: string,
  targets: readonly string[],
  binders: readonly string[],
): number {
  if (binders.includes(chainId)) return BINDER_COLOR;
  if (targets.includes(chainId)) return TARGET_COLOR;
  return CHAIN_COLORS[index % CHAIN_COLORS.length]!;
}

export function cssColor(color: number): string {
  return `#${color.toString(16).padStart(6, "0")}`;
}
