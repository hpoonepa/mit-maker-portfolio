"use client";

import { SlidersHorizontal } from "lucide-react";
import type { ToolManifest } from "@papercrane/types";

import { ParamsEditor, validateParams } from "./ParamsEditor";
import {
  parameterFieldsFromJsonSchema,
  resolvedParameterDefaults,
} from "@/lib/jobs/jsonSchemaParams";
import {
  parseToolParamsJson,
  serializeToolParams,
} from "@/lib/jobs/toolParams";

type ToolWithDefaults = ToolManifest & {
  defaultParams?: Record<string, unknown>;
  inputSchema?: Record<string, unknown>;
};

type ToolParamsPanelProps = {
  tools: ToolWithDefaults[];
  rawByTool: Record<string, string>;
  onChange: (toolId: string, raw: string) => void;
};

/** Optional JSON escape hatch for adapter-specific controls. */
export function ToolParamsPanel({
  tools,
  rawByTool,
  onChange,
}: ToolParamsPanelProps) {
  if (tools.length === 0) return null;

  return (
    <details className="px-5 py-4">
      <summary className="flex cursor-pointer list-none items-center gap-2 font-sans text-[13px] text-ink marker:content-none">
        <SlidersHorizontal
          className="h-4 w-4 text-graphite"
          aria-hidden="true"
        />
        Advanced tool parameters
        <span className="font-sans text-[12px] text-graphite-soft">
          optional
        </span>
      </summary>
      <p className="mt-3 max-w-3xl font-sans text-[12.5px] leading-relaxed text-graphite">
        Supported manifest fields are shown as controls with their documented
        ranges. Use raw JSON only for parameters the form does not expose.
      </p>
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        {tools.map((tool) => {
          const fields = parameterFieldsFromJsonSchema(
            tool.inputSchema,
            tool.defaultParams,
          );
          const defaults = resolvedParameterDefaults(
            tool.inputSchema,
            tool.defaultParams,
          );
          const defaultRaw = serializeToolParams(defaults);
          const raw = rawByTool[tool.toolId] ?? defaultRaw;
          const parsed = parseToolParamsJson(raw);
          const errors = parsed.value
            ? validateParams(fields, parsed.value)
            : undefined;
          const errorId = `tool-params-${tool.toolId}-error`;
          return (
            <div
              key={tool.toolId}
              className="bg-paper px-4 py-4"
            >
              <div className="flex items-baseline justify-between gap-3">
                <span className="font-display text-[14px] text-ink">
                  {tool.name}
                </span>
                <span className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => onChange(tool.toolId, defaultRaw)}
                    className="font-sans text-[11px] text-graphite-soft underline-offset-2 hover:text-ink hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-ink"
                  >
                    Reset defaults
                  </button>
                  <span className="font-sans text-[12px] text-graphite-soft">
                    {tool.toolId}
                  </span>
                </span>
              </div>
              {fields.length > 0 && parsed.value && (
                <div className="mt-4">
                  <ParamsEditor
                    schema={fields}
                    value={parsed.value}
                    onChange={(value) =>
                      onChange(tool.toolId, serializeToolParams(value))
                    }
                    errors={errors}
                  />
                </div>
              )}
              <details className="mt-4" open={fields.length === 0 || undefined}>
                <summary className="cursor-pointer font-sans text-[12px] text-graphite-soft hover:text-ink">
                  {fields.length > 0 ? "Edit raw JSON" : "Parameters JSON"}
                </summary>
                <textarea
                  value={raw}
                  rows={6}
                  spellCheck={false}
                  aria-label={`${tool.name} raw parameters`}
                  aria-invalid={Boolean(parsed.error) || undefined}
                  aria-describedby={parsed.error ? errorId : undefined}
                  onChange={(event) =>
                    onChange(tool.toolId, event.target.value)
                  }
                  className="mt-2 w-full resize-y rounded-lg border border-lattice-strong bg-paper px-3.5 py-3 font-mono text-[12px] leading-relaxed text-ink focus:border-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-ink/20 aria-[invalid=true]:border-crane"
                />
              </details>
              {parsed.error && (
                <span
                  id={errorId}
                  role="alert"
                  className="mt-1.5 block font-sans text-[12px] text-crane-deep"
                >
                  {parsed.error}
                </span>
              )}
            </div>
          );
        })}
      </div>
    </details>
  );
}
