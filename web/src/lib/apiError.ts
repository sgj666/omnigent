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

interface ErrorBody {
  error?: {
    code?: string;
    message?: string;
    failure_code?: string;
    provision_error?: string;
    request_id?: string;
  };
  message?: string;
  detail?: string | { code?: string; message?: string };
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
  const detailMessage =
    typeof detail === "string"
      ? detail
      : detail && typeof detail.message === "string"
        ? detail.message
        : undefined;
  const detailCode =
    detail && typeof detail !== "string" && typeof detail.code === "string"
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
