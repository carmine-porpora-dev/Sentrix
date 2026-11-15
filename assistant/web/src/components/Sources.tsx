import clsx from "clsx";
import { Activity, FlaskConical, Waves, type LucideIcon } from "lucide-react";
import type { Source, SourceKind } from "@/api/chat";
import { formatAsOf } from "@/lib/format";
import { strings } from "@/strings";

const STYLE: Record<SourceKind, { icon: LucideIcon; classes: string }> = {
  real: { icon: Activity, classes: "border-data-real bg-badge-fill-real text-data-real" },
  estimate: {
    icon: Waves,
    classes: "border-data-estimate bg-badge-fill-estimate text-data-estimate",
  },
  simulated: {
    icon: FlaskConical,
    classes: "border-data-simulated bg-badge-fill-simulated text-data-simulated",
  },
};

/** Il badge della natura di un dato: REALE (misurato), STIMA (modello), SIMULATO (simulazione). */
export function SourceBadge({ kind }: { kind: SourceKind }) {
  const { icon: Icon, classes } = STYLE[kind];
  return (
    <span
      data-kind={kind}
      className={clsx(
        "inline-flex h-6 flex-none items-center gap-1.5 whitespace-nowrap rounded-tag border px-2 text-badge uppercase",
        classes,
      )}
    >
      <Icon aria-hidden="true" size={14} strokeWidth={1.5} />
      {strings.sources.badges[kind]}
    </span>
  );
}

/** Il riquadro «Fonti» sotto una risposta (10 §6): di che natura è ogni dato e a quando risale. La
 * provenienza è sempre scritta, non nascosta in un tooltip: sul telefono non c'è il passaggio del mouse. */
export function Sources({ sources }: { sources: Source[] }) {
  if (sources.length === 0) return null;
  return (
    <section aria-label={strings.sources.title} className="mt-3 border-t border-border pt-3">
      <h2 className="m-0 mb-2 font-mono text-xs uppercase tracking-[0.04em] text-text-secondary">
        {strings.sources.title}
      </h2>
      <ul className="m-0 flex list-none flex-col gap-2 p-0">
        {sources.map((source, index) => (
          <li key={index} className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <SourceBadge kind={source.kind} />
            <span className="text-xs text-text">{source.label}</span>
            {source.value !== undefined && source.value !== null && (
              <span className="font-mono text-xs font-semibold tabular-nums text-text">
                {source.value}
              </span>
            )}
            {source.as_of && (
              <span className="text-xs text-text-secondary">
                {strings.sources.asOf(formatAsOf(source.as_of))}
              </span>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
