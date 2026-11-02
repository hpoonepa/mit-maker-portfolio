/**
 * Shared types for the Mol* viewer components.
 *
 * Paper Crane viewers accept a structure URL (CIF or PDB): usually a
 * presigned R2 URL returned by the tRPC `designs.presign` procedure. The
 * viewer stays purely client-side; the page server component is responsible
 * for handing down the URL.
 */

/** Supported structure file formats for Mol* trajectory parsing. */
export type StructureFormat = "cif" | "pdb";

/** A chain ID + residue number pair for a hotspot highlight. */
export interface DesignHighlight {
  /** PDB chain ID, e.g. "A" for target, "B" for binder. */
  chainId: string;
  /** 1-indexed residue sequence number (auth_seq_id). */
  resi: number;
  /**
   * Optional label shown on hover. If omitted, the viewer derives one from
   * the residue name + number.
   */
  label?: string;
  /**
   * Visual style for the highlight. Defaults to "sphere" (yellow sphere on
   * the alpha carbon) which is how the dashboard marks interface hotspots.
   */
  style?: "sphere" | "surface" | "outline";
}

/** Polymer representation style. */
export type RepresentationStyle = "cartoon" | "surface" | "ribbon" | "atoms";

/**
 * A single chain extracted from a loaded Mol* structure. Emitted via
 * `ViewerProps.onStructureLoad` so the parent can render a custom
 * SequencePanel without re-parsing the file.
 *
 * `chainId` is the PDB `auth_asym_id` so it matches what `onResidueClick`
 * emits: using `label_asym_id` would silently break the bidirectional
 * sync between the sequence strip and the 3D viewport.
 */
export interface SequencePanelResidue {
  /** PDB author residue number (`auth_seq_id`): same scheme as click events. */
  resi: number;
  /** One-letter amino acid code, or "X" for non-standard. */
  aa: string;
  /** Three-letter residue code, uppercased (e.g. "ARG"). */
  aa3: string;
}

export interface SequencePanelChain {
  chainId: string;
  residues: SequencePanelResidue[];
}

/** Camera snapshot shared between synced viewers in compare mode. */
export interface CameraState {
  /** Camera position in world space. */
  position: [number, number, number];
  /** Where the camera is looking. */
  target: [number, number, number];
  /** World-space "up" vector. */
  up: [number, number, number];
  /** Radius of the bounding sphere the camera is framing. */
  radius: number;
}

export interface ViewerProps {
  /**
   * Public (or presigned) URL to the structure file. The viewer fetches it
   * client-side; there is no SSR fallback because Mol* is browser-only.
   */
  structureUrl: string;
  /** File format. Inferred from URL extension when omitted. */
  format?: StructureFormat;
  /** Explicit target chain assignments. Omit for generic chain labels. */
  targetChainIds?: string[];
  /** Explicit binder chain assignments. Omit for generic chain labels. */
  binderChainIds?: string[];
  /** Hotspot residues on the target. Rendered as yellow spheres. */
  highlights?: DesignHighlight[];
  /**
   * Increment this value to animate the camera onto the current highlights.
   * A counter makes repeated clicks observable even when the highlights have
   * not changed.
   */
  focusHighlightsRequest?: number;
  /** Default representation. */
  representation?: RepresentationStyle;
  /**
   * When true the viewer auto-rotates. Respects
   * `prefers-reduced-motion: reduce` regardless of this flag.
   */
  autoRotate?: boolean;
  /** Fires whenever the camera settles after user interaction. */
  onCameraChange?: (camera: CameraState) => void;
  /** External camera to sync to (used by SideBySide). */
  syncedCamera?: CameraState | null;
  /** Optional CSS class applied to the wrapper. */
  className?: string;
  /** Accessible label for screen readers. */
  ariaLabel?: string;
  /**
   * Fires when the user clicks a residue in the 3D viewport. Consumed by
   * the 3D hotspot picker to toggle the selection Set. Receives the PDB
   * `auth_asym_id` (chain) and `auth_seq_id` (1-indexed residue) for the
   * clicked residue.
   */
  onResidueClick?: (id: { chain: string; resi: number }) => void;
  /**
   * Fires whenever the hovered residue changes. Emits `null` when the
   * cursor leaves a residue. Consumed by the 3D picker to show a residue
   * tooltip.
   */
  onResidueHover?: (id: { chain: string; resi: number } | null) => void;
  /**
   * Emitted once the structure finishes loading, with a per-chain residue
   * summary derived from the Mol* atomic hierarchy. Powers the custom
   * SequencePanel.
   */
  onStructureLoad?: (chains: SequencePanelChain[]) => void;
}
