import { ArrowRight } from "lucide-react";
import type { ReactNode } from "react";
import type { Measured } from "@/api/types";
import { Badge, type BadgeKind } from "@/components/Badge";
import { Icon } from "@/components/Icon";
import { MeasuredValue } from "@/components/MeasuredValue";
import { Provenance } from "@/components/Provenance";
import { isShortUnit, type Better } from "@/lib/format";
import { cn } from "@/lib/utils";
import { strings } from "@/i18n/it";

export type MetricCardState = "ready" | "loading" | "empty" | "unavailable";

interface MetricCardProps {
  /** Che cosa si misura («Ore-veicolo»). */
  label: string;
  state?: MetricCardState;
  /** Il valore (dell'iterazione mostrata). */
  value?: Measured;
  /** Lo stesso valore senza misure (iterazione 0): «prima → dopo». */
  before?: Measured;
  /** Un secondo numero accanto al valore (gli archi critici hanno anche i km). */
  secondary?: Measured;
  secondaryLabel?: string;
  /** La differenza rispetto alla situazione senza misure, calcolata dal backend. */
  delta?: Measured;
  better?: Better;
  /** Una precisazione accanto all'etichetta («Linea 6»). */
  hint?: string;
  /** Il testo sotto un valore che non c'è. */
  note?: ReactNode;
}

function Frame({ children, busy }: { children: ReactNode; busy?: boolean }) {
  return (
    <div
      aria-busy={busy || undefined}
      data-tooltip-anchor
      className="relative flex h-full min-w-0 flex-col gap-space-8 overflow-hidden rounded-card border-hairline border-border-card bg-surface-1 p-5"
    >
      {children}
    </div>
  );
}

const VALUE_LINE =
  "flex min-w-0 flex-wrap items-baseline gap-x-1.5 font-mono text-xl tabular-nums compact:text-kpi-sm";

/** La scheda di una metrica (07 7): etichetta, valore con la sua unità, «prima → dopo», variazione
 * e badge REALE/STIMA/SIMULATO. Ogni numero passa da `MeasuredValue`. */
export function MetricCard({
  label,
  state = "ready",
  value,
  before,
  secondary,
  secondaryLabel,
  delta,
  better = "lower",
  hint,
  note,
}: MetricCardProps) {
  const heading = (
    <div
      className="truncate text-xs text-text-secondary"
      title={hint ? `${label} · ${hint}` : label}
    >
      {label}
      {hint && <span> · {hint}</span>}
    </div>
  );

  if (state === "loading") {
    return (
      <Frame busy>
        <span
          aria-hidden
          className="absolute left-0 top-0 h-0.5 w-1/3 bg-action motion-safe:animate-pulse"
        />
        {heading}
        <div aria-hidden className="h-10 w-40 rounded-sm bg-surface-3 motion-safe:animate-pulse" />
        <div className="mt-auto flex min-h-7 items-center justify-between gap-space-8">
          <span className="text-xs text-text-secondary">{strings.metrics.loading}</span>
          <div aria-hidden className="h-7 w-20 rounded-sm bg-surface-3 motion-safe:animate-pulse" />
        </div>
      </Frame>
    );
  }

  if (state !== "ready" || !value) {
    const empty = state === "empty";
    return (
      <Frame>
        {heading}
        <div
          className={cn(VALUE_LINE, "text-text-secondary")}
          aria-label={strings.metrics.unavailable}
        >
          —
        </div>
        <div className="mt-auto flex min-h-7 items-center justify-between gap-space-8">
          <span className="text-xs text-text-secondary">
            {note ?? (empty ? strings.metrics.noRun : "")}
          </span>
          {!empty && <Badge kind="unavailable" />}
        </div>
      </Frame>
    );
  }

  return (
    <Frame>
      {heading}
      <div className={VALUE_LINE}>
        {before && (
          <>
            {/* sotto i 1440 px non c'è posto per «prima → dopo»: resta la variazione */}
            <MeasuredValue
              measured={before}
              label={`${label} (${strings.metrics.against.baseline})`}
              showUnit={false}
              className="hidden text-xl font-normal text-text-secondary compact:inline"
            />
            <Icon
              icon={ArrowRight}
              className="hidden size-5 self-center text-text-secondary compact:block"
            />
          </>
        )}
        <MeasuredValue measured={value} label={label} />
        {secondary && (
          <>
            <span aria-hidden className="text-text-secondary">
              ·
            </span>
            <MeasuredValue
              measured={secondary}
              label={secondaryLabel ?? label}
              className="font-ui text-xs font-normal text-text-secondary"
              unitClassName="ml-1 text-xs"
            />
          </>
        )}
      </div>
      <div className="mt-auto flex min-h-7 items-center justify-between gap-space-8">
        {delta ? (
          <MeasuredValue
            measured={delta}
            label={strings.metrics.against.delta(label)}
            variant="delta"
            better={better}
            showUnit={isShortUnit(delta.unit)}
          />
        ) : (
          <span />
        )}
        <Provenance measured={value} label={label} className="inline-flex">
          <Badge kind={value.kind as BadgeKind} />
        </Provenance>
      </div>
    </Frame>
  );
}
