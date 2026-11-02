import type { ParamField, ParamsValue } from "@/components/jobs/ParamsEditor";

type JsonSchema = {
  type?: string;
  description?: string;
  default?: unknown;
  enum?: unknown[];
  pattern?: string;
  minimum?: number;
  maximum?: number;
  exclusiveMinimum?: number;
  exclusiveMaximum?: number;
  minLength?: number;
  maxLength?: number;
  minItems?: number;
  maxItems?: number;
  required?: string[];
  properties?: Record<string, JsonSchema>;
  items?: JsonSchema;
};

const CANONICAL_INPUT_KEYS = new Set([
  "seeds",
  "params",
  "targetPdb",
  "targetPdbText",
  "targetPdbUrl",
  "target_pdb",
  "targetChain",
  "target_chain",
  "chain",
  "chainId",
  "partnerPdb",
  "partnerPdbText",
  "partnerPdbUrl",
  "partnerChain",
  "partner_chain",
  "sequence",
  "sequences",
  "ligand",
  "ligandSmiles",
  "ligand_sdf",
  "hotspots",
  "numDesigns",
  "num_designs",
  "num_seq_per_target",
]);

function humanize(key: string): string {
  const spaced = key
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/[_-]+/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

function safePattern(pattern: string | undefined): RegExp | undefined {
  if (!pattern) return undefined;
  try {
    return new RegExp(pattern);
  } catch {
    return undefined;
  }
}

function parameterRoot(schema: JsonSchema): JsonSchema {
  const params = schema.properties?.params;
  return params?.type === "object" && params.properties ? params : schema;
}

function fieldFromSchema(
  key: string,
  schema: JsonSchema,
  required: boolean,
  manifestDefault: unknown,
): ParamField | null {
  const label = humanize(key);
  const description = schema.description;
  const fallbackDefault = manifestDefault ?? schema.default;

  if (Array.isArray(schema.enum) && schema.enum.length > 0) {
    const options = schema.enum.filter(
      (value): value is string | number =>
        typeof value === "string" || typeof value === "number",
    );
    if (options.length !== schema.enum.length) return null;
    return {
      kind: "enum",
      key,
      label,
      description,
      options: options.map((value) => ({ value, label: String(value) })),
      ...(typeof fallbackDefault === "string" ||
      typeof fallbackDefault === "number"
        ? { default: fallbackDefault }
        : {}),
      required,
    };
  }

  if (schema.type === "string") {
    return {
      kind: "string",
      key,
      label,
      description,
      ...(typeof fallbackDefault === "string"
        ? { default: fallbackDefault }
        : {}),
      required,
      pattern: safePattern(schema.pattern),
      minLength: schema.minLength,
      maxLength: schema.maxLength,
    };
  }

  if (schema.type === "number" || schema.type === "integer") {
    return {
      kind: schema.type,
      key,
      label,
      description,
      ...(typeof fallbackDefault === "number"
        ? { default: fallbackDefault }
        : {}),
      min: schema.minimum,
      max: schema.maximum,
      exclusiveMin: schema.exclusiveMinimum,
      exclusiveMax: schema.exclusiveMaximum,
      required,
    };
  }

  if (schema.type === "boolean") {
    return {
      kind: "boolean",
      key,
      label,
      description,
      ...(typeof fallbackDefault === "boolean"
        ? { default: fallbackDefault }
        : {}),
      required,
    };
  }

  if (schema.type === "array" && schema.items?.type === "string") {
    return {
      kind: "array-string",
      key,
      label,
      description,
      ...(Array.isArray(fallbackDefault) &&
      fallbackDefault.every((value) => typeof value === "string")
        ? { default: fallbackDefault as string[] }
        : {}),
      minItems: schema.minItems,
      maxItems: schema.maxItems,
      required,
    };
  }

  if (
    schema.type === "array" &&
    (schema.items?.type === "number" || schema.items?.type === "integer")
  ) {
    return {
      kind: "array-number",
      key,
      label,
      description,
      ...(Array.isArray(fallbackDefault) &&
      fallbackDefault.every((value) => typeof value === "number")
        ? { default: fallbackDefault as number[] }
        : {}),
      minItems: schema.minItems,
      maxItems: schema.maxItems,
      itemMin: schema.items.minimum,
      itemMax: schema.items.maximum,
      integerItems: schema.items.type === "integer",
      required,
    };
  }

  if (schema.type === "object" && schema.properties) {
    const nestedRequired = new Set(schema.required ?? []);
    const manifestObject =
      manifestDefault &&
      typeof manifestDefault === "object" &&
      !Array.isArray(manifestDefault)
        ? (manifestDefault as Record<string, unknown>)
        : {};
    const fields = Object.entries(schema.properties)
      .map(([nestedKey, nestedSchema]) =>
        fieldFromSchema(
          nestedKey,
          nestedSchema,
          nestedRequired.has(nestedKey),
          manifestObject[nestedKey],
        ),
      )
      .filter((field): field is ParamField => field !== null);
    if (fields.length === 0) return null;
    return { kind: "object", key, label, description, fields, required };
  }

  return null;
}

/** Convert the simple subset used by Paper Crane manifests into form fields. */
export function parameterFieldsFromJsonSchema(
  inputSchema: Record<string, unknown> | undefined,
  manifestDefaults: Record<string, unknown> | undefined,
): ParamField[] {
  if (!inputSchema) return [];
  const root = parameterRoot(inputSchema as JsonSchema);
  const required = new Set(root.required ?? []);
  return Object.entries(root.properties ?? {})
    .filter(([key]) => !CANONICAL_INPUT_KEYS.has(key))
    .map(([key, schema]) =>
      fieldFromSchema(key, schema, required.has(key), manifestDefaults?.[key]),
    )
    .filter((field): field is ParamField => field !== null);
}

function defaultsFromFields(fields: ParamField[]): ParamsValue {
  const values: ParamsValue = {};
  for (const field of fields) {
    if (field.kind === "object") {
      const nested = defaultsFromFields(field.fields);
      if (Object.keys(nested).length > 0) values[field.key] = nested;
    } else if ("default" in field && field.default !== undefined) {
      values[field.key] = field.default;
    }
  }
  return values;
}

/** Schema defaults fill gaps; manifest defaults remain authoritative. */
export function resolvedParameterDefaults(
  inputSchema: Record<string, unknown> | undefined,
  manifestDefaults: Record<string, unknown> | undefined,
): ParamsValue {
  const configurableManifestDefaults = Object.fromEntries(
    Object.entries(manifestDefaults ?? {}).filter(
      ([key]) => !CANONICAL_INPUT_KEYS.has(key),
    ),
  );
  return {
    ...defaultsFromFields(
      parameterFieldsFromJsonSchema(inputSchema, manifestDefaults),
    ),
    ...configurableManifestDefaults,
  };
}
