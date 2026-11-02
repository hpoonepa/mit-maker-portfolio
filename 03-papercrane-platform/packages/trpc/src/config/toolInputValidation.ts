import Ajv, { type ErrorObject, type ValidateFunction } from "ajv";
import Ajv2020 from "ajv/dist/2020";
import addFormats from "ajv-formats";

type JsonObject = Record<string, unknown>;

export interface ToolInputValidationResult {
  valid: boolean;
  message?: string;
  /** True when an older catalog row only stores a schema path reference. */
  skipped?: boolean;
  /** True when the catalog schema itself is broken, rather than user input. */
  configurationError?: boolean;
}

const PLATFORM_METADATA_KEYS = new Set(["projectId", "targetId"]);

const CANONICAL_INPUT_KEYS = new Set([
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
]);

const RESERVED_TRANSPORT_KEYS = new Set([
  "_papercrane",
  "params",
  "toolParams",
  "prevOutput",
  "seeds",
  "numDesigns",
  "num_designs",
  "num_seq_per_target",
]);

const ajvDraft7 = new Ajv({
  allErrors: true,
  strict: false,
  allowUnionTypes: true,
});
const ajv2020 = new Ajv2020({
  allErrors: true,
  strict: false,
  allowUnionTypes: true,
});
addFormats(ajvDraft7);
addFormats(ajv2020);
const validators = new Map<string, ValidateFunction>();

function isObject(value: unknown): value is JsonObject {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function parameterSchema(inputSchema: JsonObject): JsonObject {
  const properties = isObject(inputSchema.properties)
    ? inputSchema.properties
    : null;
  const params = properties?.params;
  if (!isObject(params) || params.type !== "object") return inputSchema;

  // Keep root-level definitions available to refs inside the params object.
  // Several sequence-analysis schemas use
  // `#/definitions/sequenceRecord` from within `properties.params`.
  return {
    ...params,
    ...(typeof inputSchema.$schema === "string"
      ? { $schema: inputSchema.$schema }
      : {}),
    ...(isObject(inputSchema.definitions)
      ? { definitions: inputSchema.definitions }
      : {}),
    ...(isObject(inputSchema.$defs) ? { $defs: inputSchema.$defs } : {}),
  };
}

function validatorFor(schema: JsonObject): ValidateFunction {
  const dialect =
    typeof schema.$schema === "string" && schema.$schema.includes("2020-12")
      ? "2020"
      : "draft7";
  const key = `${dialect}:${JSON.stringify(schema)}`;
  const cached = validators.get(key);
  if (cached) return cached;

  // Parameter sub-schemas can carry a repeated local `$id`; omit it from the
  // compiled copy so separately versioned catalog rows cannot collide in Ajv.
  const compilable = { ...schema };
  delete compilable.$id;
  const validator =
    dialect === "2020"
      ? ajv2020.compile(compilable)
      : ajvDraft7.compile(compilable);
  validators.set(key, validator);
  return validator;
}

function errorMessage(errors: ErrorObject[] | null | undefined): string {
  const details = (errors ?? []).slice(0, 3).map((error) => {
    const path = error.instancePath || "/";
    if (error.keyword === "additionalProperties") {
      const property = (error.params as { additionalProperty?: string })
        .additionalProperty;
      return `${path} contains unsupported parameter '${property ?? "unknown"}'`;
    }
    return `${path} ${error.message ?? "is invalid"}`;
  });
  return details.length > 0
    ? `Invalid tool parameters: ${details.join("; ")}`
    : "Invalid tool parameters.";
}

/**
 * Validate user-controlled tool parameters against the manifest schema.
 * Canonical target/sequence/storage fields are validated by DesignRequest and
 * ownership checks elsewhere, so they are removed before this per-tool pass.
 */
export function validateToolParameters(
  inputSchema: unknown,
  defaultParams: unknown,
  requestToolParams: unknown,
): ToolInputValidationResult {
  if (!isObject(inputSchema)) return { valid: true, skipped: true };
  if (
    Object.keys(inputSchema).length === 1 &&
    typeof inputSchema.$ref === "string"
  ) {
    return { valid: true, skipped: true };
  }

  const defaults = isObject(defaultParams) ? defaultParams : {};
  const supplied = isObject(requestToolParams) ? requestToolParams : {};
  const reservedKey = Object.keys(supplied).find((key) =>
    RESERVED_TRANSPORT_KEYS.has(key),
  );
  if (reservedKey) {
    return {
      valid: false,
      message: `Invalid tool parameters: '${reservedKey}' is managed by Paper Crane.`,
    };
  }
  const schema = parameterSchema(inputSchema);
  const schemaProperties = isObject(schema.properties)
    ? schema.properties
    : null;
  const userParams = Object.fromEntries(
    Object.entries(supplied).filter(([key]) => {
      if (PLATFORM_METADATA_KEYS.has(key)) return false;
      // Canonical inputs are mirrored into toolParams for Python adapters.
      // Validate them when this tool declares the field; ignore compatibility
      // aliases that are not part of its parameter schema.
      if (CANONICAL_INPUT_KEYS.has(key) && schemaProperties) {
        return Object.prototype.hasOwnProperty.call(schemaProperties, key);
      }
      return !CANONICAL_INPUT_KEYS.has(key) || schemaProperties === null;
    }),
  );
  const effective = { ...defaults, ...userParams };

  try {
    const validator = validatorFor(schema);
    return validator(effective)
      ? { valid: true }
      : { valid: false, message: errorMessage(validator.errors) };
  } catch {
    // A bad embedded schema is a deployment problem, not permission to bypass
    // validation. Legacy path-only rows are handled above; malformed embedded
    // rows fail closed until `pnpm db:seed:tools` refreshes the catalog.
    return {
      valid: false,
      configurationError: true,
      message:
        "This tool's parameter schema could not be validated. Refresh the tool catalog before running it.",
    };
  }
}
