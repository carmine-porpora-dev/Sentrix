import { describe, expect, it } from "vitest";
import { ApiError, NETWORK_ERROR_CODE, networkError } from "@/api/errors";

describe("ApiError", () => {
  it("porta stato, codice, messaggio e dettagli dell'ErrorResponse", () => {
    const error = new ApiError(400, {
      code: "VALIDATION_ERROR",
      message: "La richiesta non è valida",
      details: { fields: [{ path: "arrival.peak" }] },
    });
    expect(error).toBeInstanceOf(Error);
    expect(error.name).toBe("ApiError");
    expect(error.status).toBe(400);
    expect(error.code).toBe("VALIDATION_ERROR");
    expect(error.message).toBe("La richiesta non è valida");
    expect(error.details).toEqual({ fields: [{ path: "arrival.peak" }] });
  });

  it("il 401 è non autenticato, gli altri no", () => {
    expect(new ApiError(401, { code: "UNAUTHENTICATED", message: "x" }).isUnauthorized).toBe(true);
    expect(new ApiError(403, { code: "X", message: "x" }).isUnauthorized).toBe(false);
  });

  it("i secondi d'attesa di un 429 vengono dai dettagli, se numerici", () => {
    const limited = new ApiError(429, {
      code: "RATE_LIMITED",
      message: "x",
      details: { retry_after_s: 42 },
    });
    expect(limited.retryAfterSeconds).toBe(42);
    expect(
      new ApiError(429, { code: "RATE_LIMITED", message: "x" }).retryAfterSeconds,
    ).toBeUndefined();
    const odd = new ApiError(429, {
      code: "RATE_LIMITED",
      message: "x",
      details: { retry_after_s: "presto" },
    });
    expect(odd.retryAfterSeconds).toBeUndefined();
  });

  it("un server che non risponde è un errore di stato 0", () => {
    const error = networkError("Il server non risponde");
    expect(error.status).toBe(0);
    expect(error.code).toBe(NETWORK_ERROR_CODE);
    expect(NETWORK_ERROR_CODE).toBe("NETWORK_ERROR");
    expect(error.isUnauthorized).toBe(false);
  });
});
