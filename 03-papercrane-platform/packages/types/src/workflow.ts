import { z } from "zod";

export const WorkflowIdSchema = z.enum([
  "binder-screen",
  "binder-standard",
  "binder-high-confidence",
]);
export type WorkflowId = z.infer<typeof WorkflowIdSchema>;

export interface PapercraneWorkflowStage {
  toolId: string;
  label: string;
  params: Record<string, unknown>;
}

export interface PapercraneWorkflow {
  id: WorkflowId;
  name: string;
  description: string;
  recommendedFor: string;
  stages: readonly PapercraneWorkflowStage[];
}

export const PAPERCRANE_WORKFLOWS: readonly PapercraneWorkflow[] = [
  {
    id: "binder-screen",
    name: "Rapid binder screen",
    description: "Generate binder backbones, then design sequences for them.",
    recommendedFor: "Early exploration and larger screens",
    stages: [
      { toolId: "rfdiffusion", label: "Generate backbones", params: { inference_steps: 30 } },
      { toolId: "proteinmpnn", label: "Design sequences", params: { temperature: 0.1 } },
    ],
  },
  {
    id: "binder-standard",
    name: "Binder design + validation",
    description: "Generate, sequence-design, and structurally validate every binder.",
    recommendedFor: "Most PI and postdoc binder campaigns",
    stages: [
      { toolId: "rfdiffusion", label: "Generate backbones", params: { inference_steps: 50 } },
      { toolId: "proteinmpnn", label: "Design sequences", params: { temperature: 0.1 } },
      {
        toolId: "boltz2",
        label: "Validate structures",
        params: { recycling_steps: 3, sampling_steps: 100 },
      },
    ],
  },
  {
    id: "binder-high-confidence",
    name: "High-confidence binder campaign",
    description: "Use deeper generation and validation settings for final candidates.",
    recommendedFor: "Smaller, decision-grade candidate sets",
    stages: [
      { toolId: "rfdiffusion", label: "Generate backbones", params: { inference_steps: 100 } },
      { toolId: "proteinmpnn", label: "Design sequences", params: { temperature: 0.08 } },
      {
        toolId: "boltz2",
        label: "Deep structural validation",
        params: { recycling_steps: 5, sampling_steps: 400, diffusion_samples: 2 },
      },
    ],
  },
] as const;

export function getPapercraneWorkflow(
  id: WorkflowId | string | undefined,
): PapercraneWorkflow | undefined {
  return PAPERCRANE_WORKFLOWS.find((workflow) => workflow.id === id);
}

export function workflowToolId(workflow: PapercraneWorkflow): string {
  return workflow.stages.map((stage) => stage.toolId).join("+");
}
