import type { ApiClient } from "@/api/client";
import { TILES_URL } from "@/api/constants";
import { ApiError, networkError } from "@/api/errors";
import { strings } from "@/i18n/it";
import type { ErrorBody } from "@/api/types";

const API = "/api";

type Query = Record<string, string | number | undefined>;

interface RequestOptions {
  query?: Query;
  body?: unknown;
  headers?: Record<string, string>;
  /** `text` per i CSV, `json` per tutto il resto. */
  as?: "json" | "text";
}

function withQuery(path: string, query: Query | undefined): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined) params.set(key, String(value));
  }
  const text = params.toString();
  return text ? `${path}?${text}` : path;
}

const segment = encodeURIComponent;

/** L'`ErrorResponse` del server; se la risposta non lo è (un proxy, una pagina HTML) un errore
 * generico con lo stato HTTP, mai un'eccezione a mezz'aria. */
async function readError(response: Response): Promise<ApiError> {
  try {
    const parsed = (await response.json()) as { error?: ErrorBody };
    if (parsed.error?.code && parsed.error.message)
      return new ApiError(response.status, parsed.error);
  } catch {
    // il corpo non è JSON: sotto
  }
  return new ApiError(response.status, {
    code: "HTTP_ERROR",
    message: `${response.status} ${response.statusText}`.trim(),
  });
}

/** Il client `http`: `fetch` verso `/api` dello stesso sito (in sviluppo il proxy di Vite), con il
 * cookie di sessione. `fetchImpl` si può sostituire nei test. */
export function createHttpClient(fetchImpl: typeof fetch = (...args) => fetch(...args)): ApiClient {
  async function request<T>(
    method: string,
    path: string,
    options: RequestOptions = {},
  ): Promise<T> {
    const headers: Record<string, string> = { ...options.headers };
    const init: RequestInit = { method, headers, credentials: "same-origin" };
    if (options.body !== undefined) {
      headers["content-type"] = "application/json";
      init.body = JSON.stringify(options.body);
    }
    let response: Response;
    try {
      response = await fetchImpl(withQuery(path, options.query), init);
    } catch {
      throw networkError(strings.serverDown);
    }
    if (!response.ok) throw await readError(response);
    return (options.as === "text" ? response.text() : response.json()) as Promise<T>;
  }

  const get = <T>(path: string, query?: Query) => request<T>("GET", path, { query });
  const post = <T>(path: string, body?: unknown) => request<T>("POST", path, { body });

  return {
    mode: "http",
    tilesUrl: TILES_URL,

    health: () => get(`${API}/health`),
    login: (password) => post(`${API}/auth/login`, { password }),
    logout: () => post(`${API}/auth/logout`),
    me: () => get(`${API}/auth/me`),

    listEvents: () => get(`${API}/events`),
    createEvent: (body) => post(`${API}/events`, body),
    getEvent: (eventId) => get(`${API}/events/${segment(eventId)}`),
    updateEvent: (eventId, body) => request("PUT", `${API}/events/${segment(eventId)}`, { body }),
    resetEvent: (eventId) => post(`${API}/events/${segment(eventId)}/reset`),
    resolveEvent: (eventId) => post(`${API}/events/${segment(eventId)}/resolve`),

    networkEdges: (bbox) => get(`${API}/network/edges`, { bbox }),
    transitStops: (bbox) => get(`${API}/transit/stops`, { bbox }),
    transitLines: () => get(`${API}/transit/lines`),

    createRun: (body) => post(`${API}/runs`, body),
    listRuns: (eventId) => get(`${API}/runs`, { event_id: eventId }),
    getRun: (runId) => get(`${API}/runs/${segment(runId)}`),
    runMetrics: (runId, iteration) => get(`${API}/runs/${segment(runId)}/metrics`, { iteration }),
    runLayer: (runId, layer, iteration) =>
      get(`${API}/runs/${segment(runId)}/layers/${segment(layer)}`, { iteration }),
    runDecisions: (runId) => get(`${API}/runs/${segment(runId)}/decisions`),
    runNotifications: (runId, channel) =>
      get(`${API}/runs/${segment(runId)}/notifications`, { channel }),
    ackNotification: (notificationId) => post(`${API}/notifications/${notificationId}/ack`),
    exportRun: (runId) => get(`${API}/runs/${segment(runId)}/export`, { format: "json" }),
    exportRunCsv: (runId, what) =>
      request("GET", `${API}/runs/${segment(runId)}/export`, {
        query: { format: "csv", what },
        as: "text",
      }),

    vdeptRegistry: (runId) => get(`${API}/vdept`, { run_id: runId }),
    createVdeptRequest: (deptId, body) => post(`${API}/vdept/${segment(deptId)}/requests`, body),
    getVdeptRequest: (deptId, actionId) =>
      get(`${API}/vdept/${segment(deptId)}/requests/${segment(actionId)}`),
    manualResponse: (deptId, actionId, body) =>
      post(`${API}/vdept/${segment(deptId)}/requests/${segment(actionId)}/manual-response`, body),

    liveFlow: () => request("GET", `${API}/live/flow`, { headers: { "x-view": "live" } }),

    listSensors: () => get(`${API}/sensors`),
  };
}
