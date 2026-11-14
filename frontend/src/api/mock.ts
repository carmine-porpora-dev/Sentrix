import type { ApiClient } from "@/api/client";
import { TILES_URL } from "@/api/constants";
import { ApiError } from "@/api/errors";
import type {
  ErrorBody,
  Event,
  EventSummary,
  ManualResponse,
  Notification,
  Run,
  RunView,
} from "@/api/types";

const jsonFixtures = import.meta.glob("./fixtures/**/*.json", { import: "default" }) as Record<
  string,
  () => Promise<unknown>
>;
const csvFixtures = import.meta.glob("./fixtures/**/*.csv", {
  query: "?raw",
  import: "default",
}) as Record<string, () => Promise<string>>;

interface Frame {
  step: number;
  t_seconds: number;
  state: string;
  run_view: string;
  decisions: string;
  iterations_available: number[];
}
interface Manifest {
  run_sequence: Frame[];
  errors: Record<string, string>;
}

export type MockLiveMode = "fresh" | "cached" | "snapshot" | "unavailable";
export type MockRunVariant = "degraded" | "error" | "human_decision";

export interface MockOptions {
  /** Sessione già aperta (default: no, serve il login). */
  authenticated?: boolean;
  /** Accesso libero (`PUBLIC_ACCESS` sul server): nessuna password, nessuna uscita (default: no). */
  publicAccess?: boolean;
  /** `degraded` = grafo stradale assente: banner di modalità degradata. */
  health?: "ok" | "degraded";
  /** Quale risposta dà `liveFlow` (default `fresh`). */
  liveMode?: MockLiveMode;
  /** Un solo fotogramma fisso per `getRun` invece della sequenza (stati di errore e decisione umana). */
  runVariant?: MockRunVariant;
}

async function json<T>(name: string): Promise<T> {
  const load = jsonFixtures[`./fixtures/${name}`];
  if (!load)
    throw new Error(`Fixture mancante: ${name} (rigenerarle con scripts.export_api_fixtures)`);
  return (await load()) as T;
}

async function csv(name: string): Promise<string> {
  const load = csvFixtures[`./fixtures/${name}`];
  if (!load) throw new Error(`Fixture mancante: ${name}`);
  return load();
}

const LIVE_FILES: Record<MockLiveMode, string> = {
  fresh: "live_flow_fresh.json",
  cached: "live_flow_cached.json",
  snapshot: "live_flow_snapshot.json",
  unavailable: "live_flow_unavailable.json",
};

export function createMockClient(options: MockOptions = {}): ApiClient {
  let session = (options.authenticated ?? false) || (options.publicAccess ?? false);
  let polled = 0; // quanti `getRun` ha servito il run corrente
  let manualRun = false; // il run corrente è partito con la risposta manuale
  const answers = new Map<string, ManualResponse>(); // le risposte date alle richieste, per action_id
  const acknowledged = new Set<number>(); // i bollettini confermati («Conferma ricezione»)
  let createdEventId: string | undefined;

  const manifestPromise = json<Manifest>("manifest.json");

  async function fail(status: number, message?: string): Promise<never> {
    const manifest = await manifestPromise;
    const file = manifest.errors[String(status)];
    if (!file) throw new Error(`Nessuna fixture d'errore per ${status}`);
    const body = await json<{ error: ErrorBody }>(file);
    throw new ApiError(status, { ...body.error, message: message ?? body.error.message });
  }

  async function authed<T>(answer: () => Promise<T>): Promise<T> {
    if (!session) await fail(401);
    return answer();
  }

  /** Il fotogramma del run che l'ultimo `getRun` ha mostrato (il primo, se non ne ha ancora serviti). */
  async function currentFrame(): Promise<Frame> {
    const { run_sequence: sequence } = await manifestPromise;
    return sequence[Math.min(Math.max(polled - 1, 0), sequence.length - 1)] as Frame;
  }

  /** Il fotogramma mostrato ha richieste che aspettano ancora una risposta: un run manuale non va avanti. */
  async function awaitingAnswers(): Promise<boolean> {
    if (!manualRun) return false;
    const view = await json<RunView>((await currentFrame()).run_view);
    return view.requests.some(
      (item) => item.request.state === "RECEIVED" && !answers.has(item.request.action_id),
    );
  }

  /** Le richieste `RECEIVED` che hanno avuto risposta mostrano l'esito scelto (accetta o rifiuta, con
   * codice e motivo), come sul server dove lo stato cambia subito. */
  function withAnswers(view: RunView): RunView {
    if (answers.size === 0) return view;
    return {
      ...view,
      requests: view.requests.map((item) => {
        const answer = answers.get(item.request.action_id);
        if (!answer || item.request.state !== "RECEIVED") return item;
        const accepted = answer.decision === "accept";
        return {
          ...item,
          request: {
            ...item.request,
            state: accepted ? "ACCEPTED" : "REJECTED",
            reject_code: accepted ? null : (answer.reject_code ?? null),
            reject_reason: accepted ? null : (answer.reject_reason ?? null),
          },
        };
      }),
    };
  }

  async function knownRun(runId: string): Promise<void> {
    const runs = await json<Run[]>("runs_list.json");
    if (!runs.some((run) => run.id === runId)) await fail(404, "Run non trovato");
  }

  async function knownEvent(eventId: string): Promise<void> {
    const events = await json<EventSummary[]>("events_list.json");
    if (eventId !== createdEventId && !events.some((event) => event.id === eventId)) {
      await fail(404, "Evento non trovato");
    }
  }

  /** Un'iterazione esiste quando il run l'ha prodotta: prima è un 404, come sul server. */
  async function requireIteration(iteration: number): Promise<void> {
    const frame = await currentFrame();
    if (!frame.iterations_available.includes(iteration)) {
      await fail(404, `Iterazione ${iteration} non ancora disponibile`);
    }
  }

  return {
    mode: "mock",
    tilesUrl: TILES_URL,

    health: () => json(options.health === "degraded" ? "health_degraded.json" : "health.json"),
    login: async (password) => {
      if (options.publicAccess) return json("auth_state_public.json");
      if (password === "") return fail(400, "La password è obbligatoria");
      session = true;
      return json("auth_state_authenticated.json");
    },
    logout: async () => {
      if (options.publicAccess) return json("auth_state_public.json"); // non si esce da nulla
      session = false;
      return json("auth_state_anonymous.json");
    },
    me: () =>
      json(
        options.publicAccess
          ? "auth_state_public.json"
          : session
            ? "auth_state_authenticated.json"
            : "auth_state_anonymous.json",
      ),

    listEvents: () => authed(() => json("events_list.json")),
    createEvent: () =>
      authed(async () => {
        const created = await json<Event>("event_created.json");
        createdEventId = created.id;
        return created;
      }),
    getEvent: (eventId) =>
      authed(async () => {
        await knownEvent(eventId);
        return json(eventId === createdEventId ? "event_created.json" : `event_${eventId}.json`);
      }),
    updateEvent: (eventId) =>
      authed(async () => {
        await knownEvent(eventId);
        return json("event_updated.json");
      }),
    resetEvent: (eventId) =>
      authed(async () => {
        await knownEvent(eventId);
        return json("event_reset.json");
      }),
    resolveEvent: (eventId) =>
      authed(async () => {
        await knownEvent(eventId);
        return json("event_resolve_preview.json");
      }),

    networkEdges: () => authed(() => json("network_edges.json")),
    transitStops: () => authed(() => json("transit_stops.json")),
    transitLines: () => authed(() => json("transit_lines.json")),

    createRun: (body) =>
      authed(async () => {
        polled = 0;
        manualRun = body.manual_response;
        answers.clear();
        return json("run_created.json");
      }),
    listRuns: (eventId) =>
      authed(async () => {
        const runs = await json<Run[]>("runs_list.json");
        return eventId === undefined ? runs : runs.filter((run) => run.event_id === eventId);
      }),
    getRun: (runId) =>
      authed(async () => {
        await knownRun(runId);
        if (options.runVariant) return json(`run_view_variant_${options.runVariant}.json`);
        // La sequenza si ferma sull'ultimo fotogramma (`currentFrame`) e, in un run manuale, su quello
        // che aspetta risposte.
        if (!(await awaitingAnswers())) polled += 1;
        return withAnswers(await json<RunView>((await currentFrame()).run_view));
      }),
    runMetrics: (runId, iteration) =>
      authed(async () => {
        await knownRun(runId);
        await requireIteration(iteration);
        return json(`run_metrics/iteration_${iteration}.json`);
      }),
    runLayer: (runId, layer, iteration) =>
      authed(async () => {
        await knownRun(runId);
        await requireIteration(iteration);
        return json(`run_layers/${layer}_it${iteration}.json`);
      }),
    runDecisions: (runId) =>
      authed(async () => {
        await knownRun(runId);
        return json((await currentFrame()).decisions);
      }),
    runNotifications: (runId, channel) =>
      authed(async () => {
        await knownRun(runId);
        // WhatsApp parte dopo `DONE`: prima dell'ultimo fotogramma non c'è ancora nulla
        if ((await currentFrame()).state !== "DONE") return [];
        const rows = (await json<Notification[]>("run_notifications.json")).map((row) =>
          acknowledged.has(row.id) ? { ...row, state: "ACKNOWLEDGED" as const } : row,
        );
        return channel ? rows.filter((row) => row.channel === channel) : rows;
      }),
    ackNotification: (notificationId) =>
      authed(async () => {
        const rows = await json<Notification[]>("run_notifications.json");
        const row = rows.find((candidate) => candidate.id === notificationId);
        if (!row) return fail(404, "Notifica non trovata");
        // come il server: WhatsApp non ha un ciclo di vita, e un bollettino si conferma una volta sola
        const state = acknowledged.has(row.id) ? "ACKNOWLEDGED" : row.state;
        if (row.channel !== "emergency_bulletin" || state === "ACKNOWLEDGED") {
          throw new ApiError(409, {
            code: "NOT_ACKNOWLEDGEABLE",
            message: "Questa notifica non si può confermare",
            details: { state },
          });
        }
        acknowledged.add(row.id);
        return json<Notification>("notification_acknowledged.json").then((done) => ({
          ...row,
          state: done.state,
        }));
      }),
    exportRun: (runId) =>
      authed(async () => {
        await knownRun(runId);
        return json("run_export.json");
      }),
    exportRunCsv: (runId, what) =>
      authed(async () => {
        await knownRun(runId);
        return csv(`run_export_${what}.csv`);
      }),

    vdeptRegistry: () => authed(() => json("vdept_registry.json")),
    createVdeptRequest: () => authed(() => json("vdept_request_created.json")),
    getVdeptRequest: () => authed(() => json("vdept_request.json")),
    manualResponse: (_deptId, actionId, body) =>
      authed(async () => {
        answers.set(actionId, body);
        return json("vdept_manual_response.json");
      }),

    liveFlow: () => authed(() => json(LIVE_FILES[options.liveMode ?? "fresh"])),

    listSensors: () => authed(() => json("sensors.json")),
  };
}
