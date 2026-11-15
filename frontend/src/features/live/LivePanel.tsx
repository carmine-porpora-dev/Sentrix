import { CircleCheck, TriangleAlert, type LucideIcon } from "lucide-react";
import type { LiveFlowResponse } from "@/api/types";
import { Icon } from "@/components/Icon";
import { MeasuredValue } from "@/components/MeasuredValue";
import { StateChip } from "@/components/StateChip";
import { useLiveFlow } from "@/features/live/queries";
import { liveStatus } from "@/features/live/status";
import { cn } from "@/lib/utils";
import { strings } from "@/i18n/it";

const copy = strings.live.panel;

/** Cosa dice il pannello: la situazione è ordinaria, ci sono tratti rallentati, i dati sono parziali
 * (lo snapshot è più vecchio di 5 minuti) o non ce ne sono. Non si inventa nulla (08 1): senza un dato
 * aggiornato non si dice «nessuna criticità», si dice «dati parziali». */
function Message({
  icon,
  tone,
  title,
  hint,
}: {
  icon: LucideIcon;
  tone: "ok" | "warning";
  title: string;
  hint: string;
}) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-space-12 p-space-24 text-center">
      <Icon
        icon={icon}
        className={cn("size-12", tone === "ok" ? "text-success" : "text-warning")}
      />
      <p className="text-lg font-semibold text-text-primary">{title}</p>
      <p className="max-w-xs text-sm text-text-secondary">{hint}</p>
    </div>
  );
}

const slowedSegments = (flow: LiveFlowResponse) =>
  flow.segments
    .filter((s) => s.congestion_class >= 1)
    .sort(
      (a, b) => b.congestion_class - a.congestion_class || a.label.localeCompare(b.label, "it"),
    );

/** La scheda Operations in LIVE (design 01–02): lo stato dei tratti in parole. */
export function LivePanel() {
  const query = useLiveFlow(true);
  const flow = query.data;
  const status = liveStatus(query);
  if (status === "loading") {
    return <p className="p-space-16 text-sm text-text-secondary">{copy.loading}</p>;
  }
  if (!flow || status === "none") {
    return (
      <Message icon={TriangleAlert} tone="warning" title={copy.noneTitle} hint={copy.noneHint} />
    );
  }
  if (status === "partial") {
    return (
      <Message
        icon={TriangleAlert}
        tone="warning"
        title={copy.partialTitle}
        hint={copy.partialHint}
      />
    );
  }
  const slowed = slowedSegments(flow);
  if (slowed.length === 0) {
    return (
      <Message icon={CircleCheck} tone="ok" title={copy.ordinaryTitle} hint={copy.ordinaryHint} />
    );
  }
  return (
    <div className="flex flex-col gap-space-12 p-space-16">
      <h2 className="text-lg">{copy.slowedTitle}</h2>
      <p className="text-sm text-text-secondary">{copy.slowedHint}</p>
      <ul className="flex flex-col gap-space-8">
        {slowed.map((segment) => (
          <li
            key={segment.id}
            className="flex items-center justify-between gap-space-12 rounded-card bg-surface-2 p-space-12"
          >
            <div className="flex min-w-0 flex-col gap-1">
              <span className="truncate text-sm font-semibold text-text-primary">
                {segment.label}
              </span>
              <span className="flex flex-wrap items-center gap-x-space-8 font-mono text-xs text-text-secondary">
                <MeasuredValue measured={segment.current_speed} label={segment.label} />
                <span aria-hidden>/</span>
                <MeasuredValue
                  measured={segment.free_flow_speed}
                  label={`${segment.label}: ${strings.map.popup.freeFlow.toLowerCase()}`}
                />
              </span>
            </div>
            <StateChip
              tone={segment.congestion_class >= 2 ? "rejected" : "pending"}
              label={strings.map.congestion[segment.congestion_class] ?? ""}
            />
          </li>
        ))}
      </ul>
    </div>
  );
}
