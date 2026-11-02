import type { components, paths } from "./types.generated";

export type ApiErrorEnvelope = components["schemas"]["ErrorResponse"];
export type MatchDetail = components["schemas"]["MatchDetail"];
export type JobEvent = components["schemas"]["JobEvent"];

export type Decoder<T> = (value: unknown) => T;
type HttpMethod = "get" | "post" | "put" | "patch" | "delete";
type OperationAt<
  Path extends keyof paths,
  Method extends HttpMethod,
> = Method extends keyof paths[Path]
  ? Exclude<paths[Path][Method], undefined>
  : never;
type IsMultipartOperation<Operation> = Operation extends {
  requestBody: { content: { "multipart/form-data": unknown } };
}
  ? true
  : false;
type SupportedMethod<Path extends keyof paths> = {
  [Method in HttpMethod]: Method extends keyof paths[Path]
    ? [Exclude<paths[Path][Method], undefined>] extends [never]
      ? never
      : IsMultipartOperation<
            Exclude<paths[Path][Method], undefined>
          > extends true
        ? never
        : Method
    : never;
}[HttpMethod];
type AssertTrue<Value extends true> = Value;
type MultipartRequestIsExcluded = AssertTrue<
  "post" extends SupportedMethod<"/api/v1/matches"> ? false : true
>;
type ParametersAt<Operation, Kind extends "path" | "query"> =
  Operation extends { parameters: infer Parameters }
    ? Kind extends keyof Parameters
      ? Parameters[Kind]
      : never
    : never;
type RequestBodyAt<Operation> = Operation extends {
  requestBody: { content: { "application/json": infer Body } };
}
  ? Body
  : never;
type MultipartBodyAt<Operation> = Operation extends {
  requestBody: { content: { "multipart/form-data": infer Body } };
}
  ? Body
  : never;
type ResponseContent<Response> = Response extends { content: infer Content }
  ? Content extends { "application/json": infer Body }
    ? Body
    : Content extends { "text/event-stream": infer Body }
      ? Body
      : undefined
  : undefined;
type SuccessResponses<Operation> = Operation extends {
  responses: infer Responses;
}
  ? {
      [Status in keyof Responses]: Status extends 200 | 201 | 202 | 204
        ? ResponseContent<Responses[Status]>
        : never;
    }[keyof Responses]
  : never;

type RequestField<Name extends string, Value> = [Value] extends [never]
  ? {}
  : undefined extends Value
    ? { [Key in Name]?: Value }
    : { [Key in Name]: Value };
type DecoderField<Value> = [Exclude<Value, undefined>] extends [never]
  ? { decode?: never }
  : { decode: Decoder<Exclude<Value, undefined>> };

export type RequestOptions<
  Path extends keyof paths,
  Method extends HttpMethod,
> = RequestField<
  "path",
  ParametersAt<OperationAt<Path, Method>, "path">
> &
  RequestField<
    "query",
    ParametersAt<OperationAt<Path, Method>, "query">
  > &
  RequestField<"body", RequestBodyAt<OperationAt<Path, Method>>> &
  DecoderField<SuccessResponses<OperationAt<Path, Method>>> & {
    signal?: AbortSignal;
  };

interface RuntimeRequestOptions {
  path?: object;
  query?: object;
  body?: unknown;
  signal?: AbortSignal;
  decode?: Decoder<unknown>;
}

function decodeErrorEnvelope(value: unknown): ApiErrorEnvelope | null {
  if (
    typeof value !== "object" ||
    value === null ||
    Array.isArray(value) ||
    !("code" in value) ||
    !("message" in value) ||
    !("requestId" in value) ||
    !("details" in value)
  ) {
    return null;
  }
  const details = value.details;
  if (
    typeof value.code !== "string" ||
    typeof value.message !== "string" ||
    typeof value.requestId !== "string" ||
    !(
      details === null ||
      (typeof details === "object" && !Array.isArray(details))
    )
  ) {
    return null;
  }
  const normalizedDetails: Record<string, unknown> | null =
    details === null ? null : {};
  if (normalizedDetails !== null && details !== null) {
    for (const [name, detail] of Object.entries(details)) {
      normalizedDetails[name] = detail;
    }
  }
  return {
    code: value.code,
    message: value.message,
    requestId: value.requestId,
    details: normalizedDetails,
  };
}

function parseJson(text: string): unknown {
  try {
    const value: unknown = JSON.parse(text);
    return value;
  } catch {
    throw new ApiError(
      0,
      "invalid_response",
      "the local API returned malformed JSON",
      null,
      "client",
    );
  }
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown> | null;
  readonly requestId: string;

  constructor(
    status: number,
    code: string,
    message: string,
    details: Record<string, unknown> | null,
    requestId: string,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
  }

  static fromEnvelope(status: number, envelope: ApiErrorEnvelope): ApiError {
    return new ApiError(
      status,
      envelope.code,
      envelope.message,
      envelope.details ?? null,
      envelope.requestId,
    );
  }
}

function resolvePath(template: string, parameters: object | undefined): string {
  let resolved = template;
  if (parameters !== undefined) {
    for (const [name, value] of Object.entries(parameters)) {
      if (typeof value !== "string" && typeof value !== "number") {
        throw new ApiError(
          0,
          "invalid_path_parameter",
          "an API path parameter is invalid",
          null,
          "client",
        );
      }
      resolved = resolved.replace(`{${name}}`, encodeURIComponent(String(value)));
    }
  }
  if (/\{[^}]+\}/u.test(resolved)) {
    throw new ApiError(
      0,
      "missing_path_parameter",
      "a required API path parameter is missing",
      null,
      "client",
    );
  }
  return resolved;
}

function appendQuery(url: string, query: object | undefined): string {
  if (query === undefined) {
    return url;
  }
  const search = new URLSearchParams();
  for (const [name, value] of Object.entries(query)) {
    if (value === undefined || value === null) {
      continue;
    }
    if (Array.isArray(value)) {
      for (const item of value) {
        if (typeof item === "string" || typeof item === "number" || typeof item === "boolean") {
          search.append(name, String(item));
        }
      }
    } else if (
      typeof value === "string" ||
      typeof value === "number" ||
      typeof value === "boolean"
    ) {
      search.set(name, String(value));
    }
  }
  const encoded = search.toString();
  return encoded ? `${url}?${encoded}` : url;
}

function safeFailure(error: unknown): ApiError {
  if (error instanceof ApiError) {
    return error;
  }
  if (error instanceof DOMException && error.name === "AbortError") {
    return new ApiError(
      0,
      "request_aborted",
      "the local API request was cancelled",
      null,
      "client",
    );
  }
  return new ApiError(
    0,
    "network_error",
    "the local API could not be reached",
    null,
    "client",
  );
}

export function request<
  Path extends keyof paths,
  Method extends SupportedMethod<Path>,
>(
  path: Path,
  method: Method,
  options: RequestOptions<Path, Method>,
): Promise<SuccessResponses<OperationAt<Path, Method>>>;
export async function request(
  path: string,
  method: HttpMethod,
  options: RuntimeRequestOptions = {},
): Promise<unknown> {
  const url = appendQuery(resolvePath(path, options.path), options.query);
  const headers = new Headers({ Accept: "application/json" });
  let body: BodyInit | undefined;
  if (options.body !== undefined) {
    if (options.body instanceof FormData) {
      body = options.body;
    } else {
      headers.set("Content-Type", "application/json");
      body = JSON.stringify(options.body);
    }
  }
  try {
    const response = await fetch(url, {
      method: method.toUpperCase(),
      headers,
      body,
      signal: options.signal,
      credentials: "same-origin",
    });
    if (response.status === 204) {
      if (!response.ok) {
        throw new ApiError(
          response.status,
          "invalid_error_response",
          "the local API returned an invalid error response",
          null,
          response.headers.get("x-request-id") ?? "client",
        );
      }
      return undefined;
    }
    const text = await response.text();
    const value = parseJson(text);
    if (!response.ok) {
      const envelope = decodeErrorEnvelope(value);
      if (envelope === null) {
        throw new ApiError(
          response.status,
          "invalid_error_response",
          "the local API returned an invalid error response",
          null,
          response.headers.get("x-request-id") ?? "client",
        );
      }
      throw ApiError.fromEnvelope(response.status, envelope);
    }
    if (options.decode === undefined) {
      throw new ApiError(
        response.status,
        "missing_response_decoder",
        "the API response requires a typed decoder",
        null,
        response.headers.get("x-request-id") ?? "client",
      );
    }
    try {
      return options.decode(value);
    } catch (error) {
      if (error instanceof ApiError) {
        throw error;
      }
      throw new ApiError(
        response.status,
        "invalid_response",
        "the local API response did not match its generated type",
        null,
        response.headers.get("x-request-id") ?? "client",
      );
    }
  } catch (error) {
    throw safeFailure(error);
  }
}

type CreateMatchOperation = OperationAt<"/api/v1/matches", "post">;
type CreateMatchBody = MultipartBodyAt<CreateMatchOperation>;
export type MatchUploadMetadata = Omit<CreateMatchBody, "video">;

export interface MatchUploadOptions {
  metadata?: MatchUploadMetadata;
  signal?: AbortSignal;
  onProgress?: (uploadedBytes: number, totalBytes: number | null) => void;
  decode: Decoder<MatchDetail>;
}

export function uploadMatch(
  video: File,
  options: MatchUploadOptions,
): Promise<MatchDetail> {
  const { promise, resolve, reject } = Promise.withResolvers<MatchDetail>();
    const request = new XMLHttpRequest();
    let settled = false;
    const finish = (callback: () => void): void => {
      if (settled) {
        return;
      }
      settled = true;
      options.signal?.removeEventListener("abort", abort);
      callback();
    };
    const abort = (): void => request.abort();
    const rejectSafely = (error: unknown): void => {
      finish(() => reject(safeFailure(error)));
    };

    request.open("POST", "/api/v1/matches");
    request.setRequestHeader("Accept", "application/json");
    request.upload.addEventListener("progress", (event) => {
      options.onProgress?.(event.loaded, event.lengthComputable ? event.total : null);
    });
    request.addEventListener("abort", () => {
      rejectSafely(
        new ApiError(
          0,
          "request_aborted",
          "the match upload was cancelled",
          null,
          "client",
        ),
      );
    });
    request.addEventListener("error", () => rejectSafely(new Error("network")));
    request.addEventListener("load", () => {
      try {
        const value = parseJson(request.responseText);
        if (request.status < 200 || request.status >= 300) {
          const envelope = decodeErrorEnvelope(value);
          if (envelope === null) {
            throw new ApiError(
              request.status,
              "invalid_error_response",
              "the local API returned an invalid upload error response",
              null,
              request.getResponseHeader("x-request-id") ?? "client",
            );
          }
          throw ApiError.fromEnvelope(request.status, envelope);
        }
        let match: MatchDetail;
        try {
          match = options.decode(value);
        } catch {
          throw new ApiError(
            request.status,
            "invalid_response",
            "the upload response did not match its generated type",
            null,
            request.getResponseHeader("x-request-id") ?? "client",
          );
        }
        finish(() => resolve(match));
      } catch (error) {
        rejectSafely(error);
      }
    });

    const form = new FormData();
    form.set("video", video, video.name);
    if (options.metadata !== undefined) {
      for (const [name, value] of Object.entries(options.metadata)) {
        if (value !== undefined && value !== null) {
          form.set(name, String(value));
        }
      }
    }
    if (options.signal?.aborted) {
      rejectSafely(
        new ApiError(
          0,
          "request_aborted",
          "the match upload was cancelled",
          null,
          "client",
        ),
      );
      return promise;
    }
    options.signal?.addEventListener("abort", abort, { once: true });
    request.send(form);
  return promise;
}

export interface JobEventStreamOptions {
  decode: Decoder<JobEvent>;
  onSnapshot: (event: JobEvent) => void;
  onError: (error: ApiError) => void;
}

export function streamJobEvents(
  jobId: string,
  options: JobEventStreamOptions,
): () => void {
  const source = new EventSource(
    `/api/v1/jobs/${encodeURIComponent(jobId)}/events`,
  );
  let closed = false;
  const receive = (event: Event): void => {
    if (closed || !(event instanceof MessageEvent) || typeof event.data !== "string") {
      return;
    }
    try {
      options.onSnapshot(options.decode(parseJson(event.data)));
    } catch {
      options.onError(
        new ApiError(
          0,
          "invalid_event",
          "the local API returned an invalid job event",
          null,
          "client",
        ),
      );
    }
  };
  const fail = (): void => {
    if (!closed) {
      options.onError(
        new ApiError(
          0,
          "event_stream_error",
          "the local job event stream was interrupted and will reconnect",
          null,
          "client",
        ),
      );
    }
  };
  source.addEventListener("job.snapshot", receive);
  source.addEventListener("error", fail);
  return (): void => {
    if (closed) {
      return;
    }
    closed = true;
    source.removeEventListener("job.snapshot", receive);
    source.removeEventListener("error", fail);
    source.close();
  };
}
