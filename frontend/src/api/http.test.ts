import { describe, expect, it, vi } from "vitest";
import type { ApiClient } from "@/api/client";
import { ApiError, NETWORK_ERROR_CODE } from "@/api/errors";
import { createHttpClient } from "@/api/http";
import { openApi } from "@/test/fixtures";

interface Call {
  url: string;
  init: RequestInit;
}

/** Un `fetch` finto che registra la chiamata e risponde con `body` (JSON) e `status`. */
function fakeFetch(body: unknown = {}, status = 200, headers: Record<string, string> = {}) {
  const calls: Call[] = [];
  const impl = vi.fn((url: string | URL | Request, init?: RequestInit) => {
    calls.push({ url: String(url), init: init ?? {} });
    const text = typeof body === "string" ? body : JSON.stringify(body);
    return Promise.resolve(new Response(text, { status, headers }));
  }) as unknown as typeof fetch;
  return { impl, calls };
}

// Una chiamata per ogni metodo del client: l'operationId che deve raggiungere, il metodo HTTP, l'URL
// atteso e (se c'è) il corpo. Il test confronta tutto questo con docs/spec/openapi.json.
interface Case {
  name: keyof ApiClient;
  operationId: string;
  call: (client: ApiClient) => Promise<unknown>;
  method: string;
  url: string;
  body?: unknown;
  headers?: Record<string, string>;
}

const EVENT = { name: "x" } as never;
const CASES: Case[] = [
  { name: "health", operationId: "health", call: (c) => c.health(), method: "GET", url: "/api/health" },
  { name: "login", operationId: "login", call: (c) => c.login("segreta"), method: "POST", url: "/api/auth/login", body: { password: "segreta" } },
  { name: "logout", operationId: "logout", call: (c) => c.logout(), method: "POST", url: "/api/auth/logout" },
  { name: "me", operationId: "me", call: (c) => c.me(), method: "GET", url: "/api/auth/me" },
  { name: "listEvents", operationId: "list_events", call: (c) => c.listEvents(), method: "GET", url: "/api/events" },
  { name: "createEvent", operationId: "create_event", call: (c) => c.createEvent(EVENT), method: "POST", url: "/api/events", body: EVENT },
  { name: "getEvent", operationId: "get_event", call: (c) => c.getEvent("match_2027"), method: "GET", url: "/api/events/match_2027" },
  { name: "updateEvent", operationId: "update_event", call: (c) => c.updateEvent("match_2027", EVENT), method: "PUT", url: "/api/events/match_2027", body: EVENT },
  { name: "resetEvent", operationId: "reset_event", call: (c) => c.resetEvent("match_2027"), method: "POST", url: "/api/events/match_2027/reset" },
  { name: "resolveEvent", operationId: "resolve_event", call: (c) => c.resolveEvent("match_2027"), method: "POST", url: "/api/events/match_2027/resolve" },
  { name: "networkEdges", operationId: "network_edges", call: (c) => c.networkEdges("14.2,40.8,14.3,40.9"), method: "GET", url: "/api/network/edges?bbox=14.2%2C40.8%2C14.3%2C40.9" },
  { name: "transitStops", operationId: "transit_stops", call: (c) => c.transitStops("14.2,40.8,14.3,40.9"), method: "GET", url: "/api/transit/stops?bbox=14.2%2C40.8%2C14.3%2C40.9" },
  { name: "transitLines", operationId: "transit_lines", call: (c) => c.transitLines(), method: "GET", url: "/api/transit/lines" },
  { name: "createRun", operationId: "create_run", call: (c) => c.createRun({ event_id: "match_2027", attendance_level: "mid", manual_response: false }), method: "POST", url: "/api/runs", body: { event_id: "match_2027", attendance_level: "mid", manual_response: false } },
  { name: "listRuns", operationId: "list_runs", call: (c) => c.listRuns("match_2027"), method: "GET", url: "/api/runs?event_id=match_2027" },
  { name: "getRun", operationId: "get_run", call: (c) => c.getRun("run_1"), method: "GET", url: "/api/runs/run_1" },
  { name: "runMetrics", operationId: "run_metrics", call: (c) => c.runMetrics("run_1", 2), method: "GET", url: "/api/runs/run_1/metrics?iteration=2" },
  { name: "runLayer", operationId: "run_layer", call: (c) => c.runLayer("run_1", "edges_vc", 0), method: "GET", url: "/api/runs/run_1/layers/edges_vc?iteration=0" },
  { name: "runDecisions", operationId: "run_decisions", call: (c) => c.runDecisions("run_1"), method: "GET", url: "/api/runs/run_1/decisions" },
  { name: "runNotifications", operationId: "run_notifications", call: (c) => c.runNotifications("run_1", "whatsapp"), method: "GET", url: "/api/runs/run_1/notifications?channel=whatsapp" },
  { name: "ackNotification", operationId: "ack_notification", call: (c) => c.ackNotification(7), method: "POST", url: "/api/notifications/7/ack" },
  { name: "exportRun", operationId: "export_run", call: (c) => c.exportRun("run_1"), method: "GET", url: "/api/runs/run_1/export?format=json" },
  { name: "exportRunCsv", operationId: "export_run", call: (c) => c.exportRunCsv("run_1", "metrics"), method: "GET", url: "/api/runs/run_1/export?format=csv&what=metrics" },
  { name: "vdeptRegistry", operationId: "vdept_registry", call: (c) => c.vdeptRegistry("run_1"), method: "GET", url: "/api/vdept?run_id=run_1" },
  { name: "createVdeptRequest", operationId: "create_vdept_request", call: (c) => c.createVdeptRequest("municipal_police", EVENT), method: "POST", url: "/api/vdept/municipal_police/requests", body: EVENT },
  { name: "getVdeptRequest", operationId: "get_vdept_request", call: (c) => c.getVdeptRequest("municipal_police", "act_1"), method: "GET", url: "/api/vdept/municipal_police/requests/act_1" },
  { name: "manualResponse", operationId: "manual_response", call: (c) => c.manualResponse("municipal_police", "act_1", { decision: "accept" }), method: "POST", url: "/api/vdept/municipal_police/requests/act_1/manual-response", body: { decision: "accept" } },
  { name: "liveFlow", operationId: "live_flow", call: (c) => c.liveFlow(), method: "GET", url: "/api/live/flow", headers: { "x-view": "live" } },
  { name: "listSensors", operationId: "list_sensors", call: (c) => c.listSensors(), method: "GET", url: "/api/sensors" },
]; // prettier-ignore

describe("client http: contratto con docs/spec/openapi.json", () => {
  const operations = new Map<
    string,
    {
      method: string;
      path: string;
      params: { name: string; in: string; required?: boolean }[];
      hasBody: boolean;
    }
  >();
  for (const [path, item] of Object.entries(openApi().paths)) {
    for (const [method, operation] of Object.entries(item)) {
      operations.set(operation.operationId, {
        method: method.toUpperCase(),
        path,
        params: operation.parameters ?? [],
        hasBody: operation.requestBody !== undefined,
      });
    }
  }

  it("ogni operazione dell'API ha il suo metodo (tranne la base map, un file)", () => {
    const covered = new Set(CASES.map((c) => c.operationId));
    const expected = [...operations.keys()].filter((id) => id !== "pmtiles");
    expect([...covered].sort()).toEqual(expected.sort());
    // e il client non ha metodi in più dei casi provati
    const methods = Object.keys(createHttpClient()).filter(
      (k) => typeof createHttpClient()[k as keyof ApiClient] === "function",
    );
    expect(methods.sort()).toEqual(CASES.map((c) => c.name).sort());
  });

  it.each(CASES)(
    "$name → $method $url",
    async ({ call, operationId, method, url, body, headers }) => {
      const { impl, calls } = fakeFetch({});
      await call(createHttpClient(impl));
      expect(calls).toHaveLength(1);
      const sent = calls[0] as Call;
      expect(sent.url).toBe(url);
      expect(sent.init.method).toBe(method);

      // metodo, percorso e parametri sono quelli dell'OpenAPI
      const operation = operations.get(operationId);
      expect(operation).toBeDefined();
      expect(operation?.method).toBe(method);
      const [pathname = "", search = ""] = url.split("?");
      const template = new RegExp(`^${(operation?.path ?? "").replace(/\{[^}]+\}/g, "[^/]+")}$`);
      expect(pathname).toMatch(template);
      const query = new URLSearchParams(search);
      const declared = (operation?.params ?? []).filter((p) => p.in === "query");
      for (const key of query.keys()) expect(declared.map((p) => p.name)).toContain(key);
      for (const param of declared.filter((p) => p.required))
        expect(query.has(param.name)).toBe(true);

      // corpo e intestazioni
      expect(operation?.hasBody).toBe(body !== undefined);
      expect(sent.init.body).toBe(body === undefined ? undefined : JSON.stringify(body));
      const sentHeaders = (sent.init.headers ?? {}) as Record<string, string>;
      expect(sentHeaders["content-type"]).toBe(body === undefined ? undefined : "application/json");
      for (const [name, value] of Object.entries(headers ?? {}))
        expect(sentHeaders[name]).toBe(value);
      expect(sent.init.credentials).toBe("same-origin");
    },
  );
});

describe("client http: URL", () => {
  it("codifica gli identificativi nel percorso", async () => {
    const { impl, calls } = fakeFetch({});
    await createHttpClient(impl).getEvent("a/b c?d");
    expect(calls[0]?.url).toBe("/api/events/a%2Fb%20c%3Fd");
  });

  it("omette i parametri non indicati", async () => {
    const { impl, calls } = fakeFetch([]);
    const client = createHttpClient(impl);
    await client.listRuns();
    await client.vdeptRegistry();
    expect(calls.map((c) => c.url)).toEqual(["/api/runs", "/api/vdept"]);
  });

  it("l'iterazione 0 si manda (non è «assente»)", async () => {
    const { impl, calls } = fakeFetch({});
    await createHttpClient(impl).runMetrics("run_1", 0);
    expect(calls[0]?.url).toBe("/api/runs/run_1/metrics?iteration=0");
  });
});

describe("client http: risposte", () => {
  it("restituisce il JSON della risposta", async () => {
    const { impl } = fakeFetch({ authenticated: true });
    await expect(createHttpClient(impl).me()).resolves.toEqual({ authenticated: true });
  });

  it("il CSV arriva come testo", async () => {
    const { impl } = fakeFetch("id,valore\nm.a,1\n");
    await expect(createHttpClient(impl).exportRunCsv("run_1", "critical_edges")).resolves.toBe(
      "id,valore\nm.a,1\n",
    );
  });
});

describe("client http: errori", () => {
  const error = (code: string, message: string, details?: Record<string, unknown>) => ({
    error: { code, message, details },
  });

  it("un ErrorResponse diventa un ApiError con stato, codice e dettagli", async () => {
    const body = error("VALIDATION_ERROR", "La richiesta non è valida", {
      fields: [{ path: "arrival.peak" }],
    });
    const { impl } = fakeFetch(body, 400);
    const failure = await createHttpClient(impl)
      .createEvent(EVENT)
      .catch((e: unknown) => e);
    expect(failure).toBeInstanceOf(ApiError);
    expect(failure).toMatchObject({
      status: 400,
      code: "VALIDATION_ERROR",
      message: "La richiesta non è valida",
    });
    expect((failure as ApiError).details).toEqual({ fields: [{ path: "arrival.peak" }] });
  });

  it("il 401 è un ApiError non autenticato", async () => {
    const { impl } = fakeFetch(error("UNAUTHENTICATED", "Accesso richiesto"), 401);
    const failure = await createHttpClient(impl)
      .listEvents()
      .catch((e: unknown) => e);
    expect((failure as ApiError).isUnauthorized).toBe(true);
  });

  it("il 429 porta i secondi d'attesa", async () => {
    const { impl } = fakeFetch(
      error("RATE_LIMITED", "Troppe richieste", { retry_after_s: 42 }),
      429,
    );
    const failure = await createHttpClient(impl)
      .login("x")
      .catch((e: unknown) => e);
    expect((failure as ApiError).retryAfterSeconds).toBe(42);
  });

  it("una risposta d'errore che non è un ErrorResponse (proxy, HTML) è comunque un ApiError", async () => {
    const { impl } = fakeFetch("<html>Bad gateway</html>", 502);
    const failure = await createHttpClient(impl)
      .health()
      .catch((e: unknown) => e);
    expect(failure).toBeInstanceOf(ApiError);
    expect(failure).toMatchObject({ status: 502, code: "HTTP_ERROR" });
  });

  it.each([
    ["senza la chiave error", { detail: "boh" }],
    ["error vuoto", { error: {} }],
    ["error senza messaggio", { error: { code: "X" } }],
    ["error senza codice", { error: { message: "x" } }],
  ])("un JSON d'errore %s non è un ErrorResponse", async (_name, body) => {
    const { impl } = fakeFetch(body, 500);
    const failure = await createHttpClient(impl)
      .health()
      .catch((e: unknown) => e);
    expect(failure).toMatchObject({ status: 500, code: "HTTP_ERROR" });
  });

  it("il server che non risponde è un ApiError di stato 0", async () => {
    const impl = vi.fn(() =>
      Promise.reject(new TypeError("Failed to fetch")),
    ) as unknown as typeof fetch;
    const failure = await createHttpClient(impl)
      .health()
      .catch((e: unknown) => e);
    expect(failure).toBeInstanceOf(ApiError);
    expect(failure).toMatchObject({ status: 0, code: NETWORK_ERROR_CODE });
  });
});
