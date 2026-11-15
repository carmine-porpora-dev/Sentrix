import { cn } from "@/lib/utils";
import { strings } from "@/i18n/it";

export type WindowChoice = "arrival" | "departure";
const WINDOWS: readonly WindowChoice[] = ["arrival", "departure"];

/** Arrivo | Deflusso: la finestra dell'Evento a cui si riferiscono metriche e mappa. */
export function WindowToggle({
  value,
  onChange,
  className,
}: {
  value: WindowChoice;
  onChange: (window: WindowChoice) => void;
  className?: string;
}) {
  return (
    <div
      role="radiogroup"
      aria-label={strings.metrics.windowLabel}
      className={cn(
        "inline-flex gap-space-4 rounded-control border-hairline border-border bg-surface-1 p-1",
        className,
      )}
    >
      {WINDOWS.map((choice) => {
        const active = choice === value;
        return (
          <button
            key={choice}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(choice)}
            className={cn(
              "h-8 rounded-tag px-space-12 text-xs font-semibold text-text-secondary transition-base hover:text-text-primary",
              active && "bg-surface-3 text-text-primary",
            )}
          >
            {strings.metrics.windows[choice]}
          </button>
        );
      })}
    </div>
  );
}
