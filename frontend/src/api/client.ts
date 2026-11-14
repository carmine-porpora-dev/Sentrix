import { createHttpClient } from "@/api/http";
import { createMockClient, type MockOptions } from "@/api/mock";
import type {
  AuthState,
  CreateRunRequest,
  CreateRunResponse,
  CsvKind,
  Decision,
  Event,
  EventInput,
  EventSummary,
  FeatureCollection,
  HealthResponse,
  LayerName,
  LiveFlowResponse,
  ManualResponse,
  MetricsResponse,
  Notification,
  NotificationChannel,
  OperationRequestDraft,
  PlannedSensor,
  RequestView,
  Run,
  RunExport,
  RunView,
  VdeptRegistry,
} from "@/api/types";

export type ApiMode = "http" | "mock";

/** Un metodo per operazione di `docs/spec/openapi.json`, con il nome dell'`operationId`. */
export interface ApiClient {
  readonly mode: ApiMode;
  /** Dove si serve la base map (`GET /tiles/napoli.pmtiles`): un file, non una chiamata JSON. */
  readonly tilesUrl: string;

  health(): Promise<HealthResponse>;
  login(password: string): Promise<AuthState>;
  logout(): Promise<AuthState>;
  me(): Promise<AuthState>;

  listEvents(): Promise<EventSummary[]>;
  createEvent(body: EventInput): Promise<Event>;
  getEvent(eventId: string): Promise<Event>;
  updateEvent(eventId: string, body: EventInput): Promise<Event>;
  resetEvent(eventId: string): Promise<Event>;
  resolveEvent(eventId: string): Promise<FeatureCollection>;

  /** `bbox` = "ovest,sud,est,nord" in gradi decimali. */
  networkEdges(bbox: string): Promise<FeatureCollection>;
  transitStops(bbox: string): Promise<FeatureCollection>;
  transitLines(): Promise<FeatureCollection>;

  createRun(body: CreateRunRequest): Promise<CreateRunResponse>;
  listRuns(eventId?: string): Promise<Run[]>;
  getRun(runId: string): Promise<RunView>;
  runMetrics(runId: string, iteration: number): Promise<MetricsResponse>;
  runLayer(runId: string, layer: LayerName, iteration: number): Promise<FeatureCollection>;
  runDecisions(runId: string): Promise<Decision[]>;
  /** Le notifiche in uscita del run (spech 12.4), con il numero sempre mascherato. */
  runNotifications(runId: string, channel?: NotificationChannel): Promise<Notification[]>;
  /** «Conferma ricezione» di un bollettino ai servizi di emergenza (spech 12.3): 409 se è già confermato. */
  ackNotification(notificationId: number): Promise<Notification>;
  exportRun(runId: string): Promise<RunExport>;
  exportRunCsv(runId: string, what: NonNullable<CsvKind>): Promise<string>;

  vdeptRegistry(runId?: string): Promise<VdeptRegistry>;
  createVdeptRequest(deptId: string, body: OperationRequestDraft): Promise<RequestView>;
  getVdeptRequest(deptId: string, actionId: string): Promise<RequestView>;
  manualResponse(deptId: string, actionId: string, body: ManualResponse): Promise<RequestView>;

  /** Solo dalla vista LIVE: è l'unico caso in cui il server può chiamare TomTom (`x-view: live`). */
  liveFlow(): Promise<LiveFlowResponse>;

  /** I sensori previsti (spech 11.5): tipo, stato `planned`, posto, cosa misureranno. Nessun numero. */
  listSensors(): Promise<PlannedSensor[]>;
}

/** `VITE_API_MODE` → modalità. Vuoto o assente = `http` (mai il mock per sbaglio in produzione);
 * qualunque altro valore è un errore di configurazione, non un ripiego silenzioso. */
export function resolveApiMode(value: string | undefined): ApiMode {
  const mode = (value ?? "").trim();
  if (mode === "" || mode === "http") return "http";
  if (mode === "mock") return "mock";
  throw new Error(`VITE_API_MODE non valido: «${mode}» (valori ammessi: http, mock)`);
}

export interface CreateApiClientOptions {
  mode?: ApiMode;
  /** Solo in modalità `mock`. */
  mock?: MockOptions;
}

export function createApiClient(options: CreateApiClientOptions = {}): ApiClient {
  const mode = options.mode ?? resolveApiMode(import.meta.env.VITE_API_MODE);
  return mode === "mock" ? createMockClient(options.mock) : createHttpClient();
}
