import { useRun } from "@/api/queries";
import type { Measured, Run } from "@/api/types";
import { MetricCard, type MetricCardState } from "@/components/MetricCard";
import { attendanceMeasured } from "@/features/metrics/attendance";
import {
  busiestClass,
  cardSpecs,
  indexDeltas,
  indexMetrics,
  type CardSpec,
} from "@/features/metrics/cards";
import { useEvent, useRunMetrics, type RunMetrics } from "@/features/metrics/queries";
import { useShell } from "@/features/shell/ShellProvider";
import { strings } from "@/i18n/it";

const copy = strings.metrics;

/** Che cosa mostra una card: lo stato e i numeri (già `Measured`, scelti e non calcolati). */
function cardFor(spec: CardSpec, metrics: RunMetrics, state: MetricCardState) {
  const current = indexMetrics(metrics.current);
  const baseline = indexMetrics(metrics.baseline);
  const value = spec.main ? current.get(spec.main) : undefined;
  if (state !== "ready") return { state };
  if (!value) return { state: "unavailable" as const };
  const withBaseline = metrics.iteration !== undefined && metrics.iteration > 0;
  const before = withBaseline ? baseline.get(spec.main) : undefined;
  const delta = withBaseline ? indexDeltas(metrics.current).get(spec.main)?.vs_baseline : undefined;
  const secondary = spec.secondary ? current.get(spec.secondary) : undefined;
  return {
    state: "ready" as const,
    value,
    before,
    delta: delta ?? undefined,
    secondary,
    better: spec.better,
  };
}

function stateOf(run: Run | undefined, metrics: RunMetrics): MetricCardState {
  if (!run) return "empty";
  if (metrics.status === "loading") return "loading";
  return metrics.status === "ready" ? "ready" : "unavailable";
}

/** La fascia delle cinque card (07 7): ore-veicolo, tempo O/D medio, archi critici (con i km), carico
 * TPL massimo e affluenza ipotizzata, per la finestra scelta e l'iterazione più recente, con la
 * variazione rispetto alla situazione senza misure. Fermate e tratte sovraccariche e deviazione
 * media sono nel dettaglio (export), non nella fascia. */
export function MetricStrip() {
  const { runId, window, view } = useShell();
  const run = useRun(runId).data?.run;
  const metrics = useRunMetrics(run, view);
  const event = useEvent(run?.event_id);
  const state = stateOf(run, metrics);

  const current = indexMetrics(metrics.current);
  const specs = cardSpecs(window, busiestClass(current, window));
  const attendance: Measured | undefined =
    run && event.data ? attendanceMeasured(event.data, run.attendance_level, run.id) : undefined;
  const attendanceState: MetricCardState = !run
    ? "empty"
    : attendance
      ? "ready"
      : event.isError
        ? "unavailable"
        : "loading";

  const vehicleHours = cardFor(specs.vehicleHours, metrics, state);
  const odTime = cardFor(specs.odTime, metrics, state);
  const criticalEdges = cardFor(specs.criticalEdges, metrics, state);
  const transitLoad = cardFor(specs.transitLoad, metrics, state);
  const transitClass = specs.transitLoad.transitClass;

  return (
    <>
      <MetricCard label={copy.cards.vehicleHours} {...vehicleHours} />
      <MetricCard label={copy.cards.odTime} {...odTime} />
      <MetricCard
        label={copy.cards.criticalEdges}
        secondaryLabel={`${copy.cards.criticalEdges} (km)`}
        {...criticalEdges}
      />
      <MetricCard
        label={copy.cards.transitLoad}
        hint={transitClass ? copy.transitClasses[transitClass] : undefined}
        {...transitLoad}
      />
      <MetricCard
        label={copy.cards.attendance}
        state={attendanceState}
        value={attendance}
        better="none"
      />
    </>
  );
}
