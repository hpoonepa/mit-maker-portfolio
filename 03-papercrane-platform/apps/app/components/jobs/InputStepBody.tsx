"use client";

import type { LigandSupport, Target, ToolInputKind } from "@papercrane/types";
import { StepIntro } from "./StepIntro";
import { TargetSelector } from "./TargetSelector";
import { ComplexInputStep, type ComplexInput } from "./ComplexInputStep";
import { BackboneInput, type BackboneValue } from "./BackboneInput";
import { SequenceInput, type SequenceValue } from "./SequenceInput";
import { LigandInput, type LigandValue } from "./LigandInput";

export interface InputStepBodyProps {
  /** Null until at least one tool is picked: the kind comes from the tools. */
  inputKind: ToolInputKind | null;
  ligandReq: LigandSupport;
  ligand: LigandValue;
  onLigandChange: (patch: Partial<LigandValue>) => void;

  targets: Target[];
  selectedTargetId: string | null;
  onSelectTarget: (id: string) => void;
  targetsLoading: boolean;
  /** Friendly, already-humanised message. Never a raw server error. */
  targetsError?: string;
  projectId?: string;
  onTargetCreationChange?: (creating: boolean) => void;

  complex: ComplexInput;
  onComplexChange: (patch: Partial<ComplexInput>) => void;
  backbone: BackboneValue;
  onBackboneChange: (patch: Partial<BackboneValue>) => void;
  sequences: SequenceValue;
  onSequencesChange: (patch: Partial<SequenceValue>) => void;
}

/**
 * The wizard's "Input" step. Which input we ask for is decided entirely by the
 * tools the user picked, so this renders one of four bodies (target / backbone
 * / co-fold pair / raw sequences) plus an optional small-molecule block.
 *
 * Extracted from the New Job page so each body keeps its own plain-language
 * header and glossary without bloating the page component.
 */
export function InputStepBody({
  inputKind,
  ligandReq,
  ligand,
  onLigandChange,
  targets,
  selectedTargetId,
  onSelectTarget,
  targetsLoading,
  targetsError,
  projectId,
  onTargetCreationChange,
  complex,
  onComplexChange,
  backbone,
  onBackboneChange,
  sequences,
  onSequencesChange,
}: InputStepBodyProps) {
  if (inputKind === null) {
    return (
      <div className="space-y-4">
        <StepIntro
          title="Set up your input"
          sub="This is where you say what protein to work on. We ask for different things depending on the tool you picked, so pick a tool first."
          ifSkipped="Nothing can run: every tool needs something to work on."
        />
        <div className="px-5 py-6 font-sans text-[13px] text-graphite">
          Go back to step 1 and choose at least one tool.
        </div>
      </div>
    );
  }

  // Shared optional/required small-molecule ligand block, rendered below the
  // main input for target/backbone kinds that take a ligand.
  const ligandBlock =
    ligandReq !== "none" ? (
      <LigandInput
        value={ligand}
        required={ligandReq === "required"}
        onChange={onLigandChange}
      />
    ) : null;

  if (inputKind === "target") {
    return (
      <div className="space-y-4">
        <StepIntro
          title="Choose the target protein"
          sub="Choose a saved structure or add one here. Your tool settings stay in place."
          defines={["target", "hotspot", "binder"]}
        />
        <TargetSelector
          targets={targets}
          selectedId={selectedTargetId}
          onSelect={onSelectTarget}
          loading={targetsLoading}
          error={targetsError}
          projectId={projectId}
          onCreationChange={onTargetCreationChange}
        />
        {ligandBlock}
      </div>
    );
  }

  if (inputKind === "backbone") {
    return (
      <div className="space-y-4">
        <StepIntro
          title="Choose a backbone"
          sub="A backbone is a protein's 3D shape with no sequence assigned yet. Give us one and the tool works out which amino acids should fill it."
          ifSkipped="The run can't start without the structure being redesigned."
          defines={["seed"]}
        />
        <BackboneInput value={backbone} onChange={onBackboneChange} />
        {ligandBlock}
      </div>
    );
  }

  if (inputKind === "complex") {
    return (
      <div className="space-y-4">
        <StepIntro
          title="Structures to fold together"
          sub="These tools predict how two known proteins sit against each other. The output is a predicted 3D structure of the pair, not a new design."
          ifSkipped="Both entries are required; the prediction is about the pair, not either one alone."
          defines={["target"]}
        />
        <ComplexInputStep value={complex} onChange={onComplexChange} />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <StepIntro
        title="Enter sequences"
        sub="Paste the amino-acid sequences you want scored: one per entry. These tools read sequence only, so no structure is needed."
        ifSkipped="There's nothing to score. Paste at least one sequence."
      />
      <SequenceInput value={sequences} onChange={onSequencesChange} />
    </div>
  );
}
