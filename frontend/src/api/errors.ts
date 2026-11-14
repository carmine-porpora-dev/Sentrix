import type { ErrorBody } from "@/api/types";

/** Un errore dell'API (`ErrorResponse`, 06 1) o un server che non risponde (`status` 0). */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: ErrorBody["details"];

  constructor(status: number, body: Pick<ErrorBody, "code" | "message" | "details">) {
    super(body.message);
    this.name = "ApiError";
    this.status = status;
    this.code = body.code;
    this.details = body.details;
  }

  /** Secondi da aspettare dopo un 429 (`details.retry_after_s`), se il server li indica. */
  get retryAfterSeconds(): number | undefined {
    const seconds = this.details?.retry_after_s;
    return typeof seconds === "number" ? seconds : undefined;
  }

  get isUnauthorized(): boolean {
    return this.status === 401;
  }
}

/** Il server non risponde (rete assente, processo fermo): non c'è un `ErrorResponse`. */
export const NETWORK_ERROR_CODE = "NETWORK_ERROR";

export function networkError(message: string): ApiError {
  return new ApiError(0, { code: NETWORK_ERROR_CODE, message });
}
