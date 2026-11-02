"use client";

import { useId, useMemo } from "react";
import { cn } from "@/lib/utils";

/**
 * A compact JSON-Schema-ish field descriptor. Covers the primitive + simple
 * composite shapes we need for tool parameters: full JSON Schema is out of
 * scope here (YAGNI).
 */
export type ParamField =
  | {
      kind: "string";
      key: string;
      label: string;
      description?: string;
      placeholder?: string;
      default?: string;
      required?: boolean;
      pattern?: RegExp;
      minLength?: number;
      maxLength?: number;
    }
  | {
      kind: "number" | "integer";
      key: string;
      label: string;
      description?: string;
      default?: number;
      min?: number;
      max?: number;
      exclusiveMin?: number;
      exclusiveMax?: number;
      step?: number;
      required?: boolean;
    }
  | {
      kind: "boolean";
      key: string;
      label: string;
      description?: string;
      default?: boolean;
      required?: boolean;
    }
  | {
      kind: "enum";
      key: string;
      label: string;
      description?: string;
      options: Array<{ value: string | number; label: string }>;
      default?: string | number;
      required?: boolean;
    }
  | {
      kind: "array-string";
      key: string;
      label: string;
      description?: string;
      /** Comma-separated input in the UI. */
      default?: string[];
      minItems?: number;
      maxItems?: number;
      required?: boolean;
    }
  | {
      kind: "array-number";
      key: string;
      label: string;
      description?: string;
      /** Comma-separated input in the UI. */
      default?: number[];
      minItems?: number;
      maxItems?: number;
      itemMin?: number;
      itemMax?: number;
      integerItems?: boolean;
      required?: boolean;
    }
  | {
      kind: "object";
      key: string;
      label: string;
      description?: string;
      fields: ParamField[];
      required?: boolean;
    };

export type ParamsValue = Record<string, unknown>;

type ParamsEditorProps = {
  /** Ordered list of top-level fields. Empty = render nothing. */
  schema: ParamField[];
  value: ParamsValue;
  onChange: (next: ParamsValue) => void;
  /** Field-keyed error messages from zod. */
  errors?: Record<string, string>;
};

/**
 * Renders a form UI from a `ParamField[]` descriptor. No external form
 * library: parent holds state, we just call onChange with the merged
 * record.  Supports nested `object` one level deep, which is plenty for
 * tool-specific params.
 */
export function ParamsEditor({
  schema,
  value,
  onChange,
  errors,
}: ParamsEditorProps) {
  if (schema.length === 0) {
    return (
      <p className="font-sans text-[13px] text-graphite">
        This tool takes no extra parameters. Adjust seeds below and submit.
      </p>
    );
  }

  const setField = (key: string, v: unknown) => {
    onChange({ ...value, [key]: v });
  };

  return (
    <div className="grid gap-5 md:grid-cols-2">
      {schema.map((field) =>
        field.kind === "object" ? (
          <FieldObject
            key={field.key}
            field={field}
            value={(value[field.key] as ParamsValue) ?? {}}
            onChange={(v) => setField(field.key, v)}
            errors={errors}
          />
        ) : (
          <FieldPrimitive
            key={field.key}
            field={field}
            value={value[field.key]}
            onChange={(v) => setField(field.key, v)}
            error={errors?.[field.key]}
          />
        ),
      )}
    </div>
  );
}

function FieldObject({
  field,
  value,
  onChange,
  errors,
}: {
  field: Extract<ParamField, { kind: "object" }>;
  value: ParamsValue;
  onChange: (v: ParamsValue) => void;
  errors?: Record<string, string>;
}) {
  return (
    <fieldset className="md:col-span-2 p-4">
      <legend className="px-1 font-sans text-[12px] text-graphite-soft">
        {field.label}
      </legend>
      {field.description && (
        <p className="-mt-1 mb-3 font-sans text-[12px] text-graphite">
          {field.description}
        </p>
      )}
      <div className="grid gap-4 md:grid-cols-2">
        {field.fields.map((sub) => (
          <FieldPrimitive
            key={sub.key}
            field={sub as Exclude<ParamField, { kind: "object" }>}
            value={value[sub.key]}
            onChange={(v) => onChange({ ...value, [sub.key]: v })}
            error={errors?.[`${field.key}.${sub.key}`]}
          />
        ))}
      </div>
    </fieldset>
  );
}

function FieldPrimitive({
  field,
  value,
  onChange,
  error,
}: {
  field: Exclude<ParamField, { kind: "object" }>;
  value: unknown;
  onChange: (v: unknown) => void;
  error?: string;
}) {
  const id = useId();
  const descId = `${id}-desc`;
  const errId = `${id}-err`;
  const hasError = Boolean(error);
  const describedBy =
    [field.description ? descId : null, hasError ? errId : null]
      .filter(Boolean)
      .join(" ") || undefined;

  const common = {
    id,
    "aria-invalid": hasError || undefined,
    "aria-describedby": describedBy,
    className: cn(
      "rounded-xl border bg-paper px-4 py-3 font-sans text-[14px] text-ink placeholder:text-graphite-soft",
      "focus:border-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-ink focus-visible:ring-offset-1 focus-visible:ring-offset-paper",
      hasError ? "border-crane" : "border-lattice-strong",
    ),
  };

  return (
    <label className="flex flex-col gap-1.5" htmlFor={id}>
      <span className="font-sans text-[12px] text-graphite-soft">
        {field.label}
        {"required" in field && field.required && (
          <span aria-hidden="true" className="ml-1 text-crane">
            *
          </span>
        )}
      </span>

      {renderControl(field, value, onChange, common)}

      {field.description && (
        <span id={descId} className="font-sans text-[12px] text-graphite">
          {field.description}
        </span>
      )}
      {hasError && (
        <span
          id={errId}
          role="alert"
          className="font-sans text-[12px] text-crane-deep"
        >
          {error}
        </span>
      )}
    </label>
  );
}

function renderControl(
  field: Exclude<ParamField, { kind: "object" }>,
  value: unknown,
  onChange: (v: unknown) => void,
  common: {
    id: string;
    className: string;
    "aria-invalid"?: true;
    "aria-describedby"?: string;
  },
) {
  switch (field.kind) {
    case "string":
      return (
        <input
          {...common}
          type="text"
          value={typeof value === "string" ? value : (field.default ?? "")}
          placeholder={field.placeholder}
          required={field.required}
          onChange={(e) => onChange(e.target.value)}
        />
      );
    case "number":
    case "integer":
      return (
        <input
          {...common}
          type="number"
          value={
            typeof value === "number"
              ? value
              : typeof field.default === "number"
                ? field.default
                : ""
          }
          min={field.min}
          max={field.max}
          step={field.step ?? (field.kind === "integer" ? 1 : "any")}
          required={field.required}
          onChange={(e) => {
            if (e.target.value === "") {
              onChange(undefined);
              return;
            }
            const n = Number(e.target.value);
            onChange(Number.isFinite(n) ? n : undefined);
          }}
        />
      );
    case "boolean":
      return (
        <span className="flex items-center gap-2.5">
          <input
            id={common.id}
            type="checkbox"
            aria-invalid={common["aria-invalid"]}
            aria-describedby={common["aria-describedby"]}
            checked={Boolean(value ?? field.default)}
            onChange={(e) => onChange(e.target.checked)}
            className="h-4 w-4 rounded border-lattice-strong accent-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-ink"
          />
          <span className="font-sans text-[14px] text-ink">
            {field.description ?? "Enabled"}
          </span>
        </span>
      );
    case "enum":
      return (
        <select
          {...common}
          value={
            typeof value === "string" || typeof value === "number"
              ? String(value)
              : field.default !== undefined
                ? String(field.default)
                : ""
          }
          required={field.required}
          onChange={(e) => {
            if (!e.target.value) {
              onChange(undefined);
              return;
            }
            const selected = field.options.find(
              (option) => String(option.value) === e.target.value,
            );
            onChange(selected?.value ?? e.target.value);
          }}
        >
          {!field.required && <option value="">- none -</option>}
          {field.options.map((opt) => (
            <option key={String(opt.value)} value={String(opt.value)}>
              {opt.label}
            </option>
          ))}
        </select>
      );
    case "array-string": {
      const arr = Array.isArray(value)
        ? (value as string[])
        : (field.default ?? []);
      const csv = arr.join(", ");
      return (
        <input
          {...common}
          type="text"
          value={csv}
          placeholder="comma, separated, values"
          onChange={(e) => {
            const next = e.target.value
              .split(",")
              .map((s) => s.trim())
              .filter(Boolean);
            onChange(next);
          }}
        />
      );
    }
    case "array-number": {
      const arr = Array.isArray(value)
        ? (value as number[])
        : (field.default ?? []);
      return (
        <input
          {...common}
          type="text"
          inputMode="decimal"
          value={arr.join(", ")}
          placeholder="comma, separated, numbers"
          onChange={(e) => {
            const values = e.target.value
              .split(",")
              .map((item) => item.trim())
              .filter(Boolean)
              .map((item) => Number(item))
              .filter(Number.isFinite);
            onChange(values);
          }}
        />
      );
    }
  }
}

/**
 * Validate params using the schema. Returns a flat error map keyed by field
 * key (with dot-notation for nested object fields). Intentionally small -
 * the server does the zod-true validation; this is fast UX feedback.
 */
export function validateParams(
  schema: ParamField[],
  value: ParamsValue,
): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const field of schema) {
    if (field.kind === "object") {
      const rawNested = value[field.key];
      if (
        field.required &&
        (!rawNested ||
          typeof rawNested !== "object" ||
          Array.isArray(rawNested))
      ) {
        errors[field.key] = `${field.label} is required`;
        continue;
      }
      const nested =
        rawNested && typeof rawNested === "object" && !Array.isArray(rawNested)
          ? (rawNested as ParamsValue)
          : {};
      const nestedErrs = validateParams(field.fields, nested);
      for (const [k, v] of Object.entries(nestedErrs)) {
        errors[`${field.key}.${k}`] = v;
      }
      continue;
    }
    const v = value[field.key];
    if ("required" in field && field.required) {
      if (v === undefined || v === "" || (Array.isArray(v) && v.length === 0)) {
        errors[field.key] = `${field.label} is required`;
        continue;
      }
    }
    if (field.kind === "string" && v !== undefined && typeof v !== "string") {
      errors[field.key] = `${field.label} must be text`;
    }
    if (field.kind === "boolean" && v !== undefined && typeof v !== "boolean") {
      errors[field.key] = `${field.label} must be true or false`;
    }
    if (
      field.kind === "enum" &&
      v !== undefined &&
      !field.options.some((option) => Object.is(option.value, v))
    ) {
      errors[field.key] = `${field.label} is not a supported option`;
    }
    if (field.kind === "number" || field.kind === "integer") {
      if (v !== undefined && typeof v !== "number") {
        errors[field.key] = `${field.label} must be a number`;
      } else if (typeof v === "number") {
        if (field.kind === "integer" && !Number.isInteger(v)) {
          errors[field.key] = `${field.label} must be an integer`;
        } else if (field.min !== undefined && v < field.min) {
          errors[field.key] = `${field.label} must be ≥ ${field.min}`;
        } else if (
          field.exclusiveMin !== undefined &&
          v <= field.exclusiveMin
        ) {
          errors[field.key] = `${field.label} must be > ${field.exclusiveMin}`;
        } else if (field.max !== undefined && v > field.max) {
          errors[field.key] = `${field.label} must be ≤ ${field.max}`;
        } else if (
          field.exclusiveMax !== undefined &&
          v >= field.exclusiveMax
        ) {
          errors[field.key] = `${field.label} must be < ${field.exclusiveMax}`;
        }
      }
    }
    if (
      field.kind === "string" &&
      field.pattern &&
      typeof v === "string" &&
      v
    ) {
      if (!field.pattern.test(v)) {
        errors[field.key] = `${field.label} is malformed`;
      }
    }
    if (field.kind === "string" && typeof v === "string") {
      if (field.minLength !== undefined && v.length < field.minLength) {
        errors[field.key] =
          `${field.label} needs at least ${field.minLength} character(s)`;
      } else if (field.maxLength !== undefined && v.length > field.maxLength) {
        errors[field.key] =
          `${field.label} accepts at most ${field.maxLength} character(s)`;
      }
    }
    if (
      (field.kind === "array-string" || field.kind === "array-number") &&
      v !== undefined &&
      !Array.isArray(v)
    ) {
      errors[field.key] = `${field.label} must be a list`;
    }
    if (
      (field.kind === "array-string" || field.kind === "array-number") &&
      Array.isArray(v)
    ) {
      if (field.minItems !== undefined && v.length < field.minItems) {
        errors[field.key] =
          `${field.label} needs at least ${field.minItems} item(s)`;
      } else if (field.maxItems !== undefined && v.length > field.maxItems) {
        errors[field.key] =
          `${field.label} accepts at most ${field.maxItems} item(s)`;
      } else if (
        field.kind === "array-number" &&
        v.some(
          (item) =>
            typeof item !== "number" ||
            (field.integerItems && !Number.isInteger(item)) ||
            (field.itemMin !== undefined && item < field.itemMin) ||
            (field.itemMax !== undefined && item > field.itemMax),
        )
      ) {
        errors[field.key] = `${field.label} contains an out-of-range value`;
      }
    }
  }
  return errors;
}

/**
 * Build initial params by resolving each field's `default` (recursively for
 * nested objects). Called once when the user picks a tool.
 */
export function defaultParams(schema: ParamField[]): ParamsValue {
  const out: ParamsValue = {};
  for (const field of schema) {
    if (field.kind === "object") {
      out[field.key] = defaultParams(field.fields);
    } else if ("default" in field && field.default !== undefined) {
      out[field.key] = field.default;
    }
  }
  return out;
}

/**
 * Hook-free memoized default builder for stable object identity in React.
 */
export function useDefaultParams(schema: ParamField[]): ParamsValue {
  return useMemo(() => defaultParams(schema), [schema]);
}
