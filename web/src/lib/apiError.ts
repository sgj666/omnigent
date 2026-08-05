export interface ApiErrorFields {
  status: number;
  failure_code?: string;
  provision_error?: string;
  request_id?: string;
  details?: unknown;
}

/** Error raised by typed API clients while retaining server diagnostics. */
export class ApiError extends Error implements ApiErrorFields {
  readonly status: number;
  readonly failure_code?: string;
  readonly provision_error?: string;
  readonly request_id?: string;
  readonly details?: unknown;

  constructor(message: string, fields: ApiErrorFields) {
    super(message);
    this.name = "ApiError";
    this.status = fields.status;
    this.failure_code = fields.failure_code;
    this.provision_error = fields.provision_error;
    this.request_id = fields.request_id;
    this.details = fields.details;
  }
}

/**
 * One entry of a FastAPI/Pydantic 422 `detail` array.
 *
 * Deliberately omits `input`: it echoes the value the user submitted and must
 * never reach a rendered error message. `ctx`/`type` are omitted for the same
 * reason we do not surface them — they add no actionable information.
 */
interface ValidationErrorItem {
  loc?: unknown;
  msg?: unknown;
}

/** Render `loc: ["body", "agent", 0]` as `body.agent[0]`, skipping unusable parts. */
function formatValidationLocation(loc: unknown): string | undefined {
  if (!Array.isArray(loc)) return undefined;
  let path = "";
  for (const part of loc) {
    if (typeof part === "number") {
      path += `[${part}]`;
    } else if (typeof part === "string" && part.length > 0) {
      path += path.length > 0 ? `.${part}` : part;
    }
  }
  return path.length > 0 ? path : undefined;
}

/**
 * Summarise a Pydantic 422 `detail` array into an actionable message.
 *
 * Returns undefined when no entry carries a usable `msg`, so the caller can
 * fall through to the remaining fallbacks rather than showing an empty string.
 */
function formatValidationDetail(items: readonly unknown[]): string | undefined {
  const parts: string[] = [];
  for (const item of items) {
    if (typeof item === "string") {
      if (item.length > 0) parts.push(item);
      continue;
    }
    if (!item || typeof item !== "object") continue;
    const { loc, msg } = item as ValidationErrorItem;
    if (typeof msg !== "string" || msg.length === 0) continue;
    const location = formatValidationLocation(loc);
    parts.push(location ? `${location}: ${msg}` : msg);
  }
  return parts.length > 0 ? parts.join("; ") : undefined;
}

interface ErrorBody {
  error?: {
    code?: string;
    message?: string;
    failure_code?: string;
    provision_error?: string;
    request_id?: string;
  };
  message?: string;
  detail?: string | { code?: string; message?: string } | ValidationErrorItem[];
  failure_code?: string;
  provision_error?: string;
  request_id?: string;
  [key: string]: unknown;
}

export async function throwApiError(response: Response): Promise<never> {
  let body: ErrorBody = {};
  try {
    body = (await response.json()) as ErrorBody;
  } catch {
    // Keep the status line when the server did not return JSON.
  }
  const nested = body.error ?? {};
  const detail = body.detail;
  // Array must be tested before the object branch: typeof [] === "object".
  const detailMessage =
    typeof detail === "string"
      ? detail
      : Array.isArray(detail)
        ? formatValidationDetail(detail)
        : detail && typeof detail.message === "string"
          ? detail.message
          : undefined;
  const detailCode =
    detail &&
    typeof detail !== "string" &&
    !Array.isArray(detail) &&
    typeof detail.code === "string"
      ? detail.code
      : undefined;
  const requestId = response.headers.get("X-Request-Id") ?? body.request_id ?? nested.request_id;
  const failureCode = body.failure_code ?? nested.failure_code ?? nested.code ?? detailCode;
  const provisionError = body.provision_error ?? nested.provision_error;
  const message =
    nested.message ??
    body.message ??
    detailMessage ??
    provisionError ??
    `${response.status} ${response.statusText}`;
  throw new ApiError(message, {
    status: response.status,
    failure_code: failureCode,
    provision_error: provisionError,
    request_id: requestId ?? undefined,
    details: body,
  });
}
