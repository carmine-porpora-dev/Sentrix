import type { components, operations } from "@/api/schema";

type Schemas = components["schemas"];

export type AuthState = Schemas["AuthState"];
export type CreateRunRequest = Schemas["CreateRunRequest"];
export type CreateRunResponse = Schemas["CreateRunResponse"];
export type Decision = Schemas["Decision"];
export type ErrorBody = Schemas["ErrorBody"];
export type Event = Schemas["Event"];
export type EventInput = Schemas["EventInput"];
export type EventSummary = Schemas["EventSummary"];
export type Feature = Schemas["Feature"];
export type FeatureCollection = Schemas["FeatureCollection"];
export type HealthResponse = Schemas["HealthResponse"];
export type LiveFlowResponse = Schemas["LiveFlowResponse"];
export type ManualResponse = Schemas["ManualResponse"];
export type Measured = Schemas["Measured"];
export type MetricDelta = Schemas["MetricDelta"];
export type MetricsResponse = Schemas["MetricsResponse"];
export type Notification = Schemas["Notification"];
export type AgentSummary = Schemas["AgentSummary"];
export type Finding = Schemas["Finding"];
export type OperationRequestDraft = Schemas["OperationRequestDraft"];
export type PlanItem = Schemas["PlanItem"];
export type PlannedSensor = Schemas["PlannedSensor"];
export type RequestView = Schemas["RequestView"];
export type Run = Schemas["Run"];
export type RunExport = Schemas["RunExport"];
export type RunView = Schemas["RunView"];
export type VdeptRegistry = Schemas["VdeptRegistry"];
export type Zone = Schemas["Zone"];

export type RunState = Run["state"];
export type AttendanceLevel = Run["attendance_level"];
export type NotificationChannel = Schemas["Notification"]["channel"];
export type LayerName = operations["run_layer"]["parameters"]["path"]["layer"];
export type CsvKind = NonNullable<operations["export_run"]["parameters"]["query"]>["what"];
