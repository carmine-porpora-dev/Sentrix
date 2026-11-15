import { cn } from "@/lib/utils";
import { strings } from "@/i18n/it";

export type Mode = "live" | "scenario";

const MODES: readonly Mode[] = ["live", "scenario"];

/** Il selettore LIVE / SCENARIO: due opzioni esclusive (radiogroup). */
export function ModeSelector({ value, onChange }: { value: Mode; onChange: (mode: Mode) => void }) {
  return (
    <div role="radiogroup" aria-label={strings.shell.modeLabel} className="inline-flex gap-space-8">
      {MODES.map((mode) => {
        const active = mode === value;
        return (
          <button
            key={mode}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(mode)}
            className={cn(
              "flex h-size-mode-button-height flex-col compact:min-w-48 items-start justify-center rounded-control border-control border-transparent bg-surface-2 px-space-16 text-left transition-base hover:bg-surface-3",
              active &&
                mode === "live" &&
                "border-data-real bg-mode-fill-live hover:bg-mode-fill-live",
              active &&
                mode === "scenario" &&
                "border-scenario-frame bg-mode-fill-scenario hover:bg-mode-fill-scenario",
            )}
          >
            <span
              className={cn(
                "text-badge uppercase leading-4 text-text-secondary",
                active && "text-text-primary",
              )}
            >
              {strings.shell.modes[mode].name}
            </span>
            <span className="text-xs leading-4 text-text-secondary">
              {strings.shell.modes[mode].description}
            </span>
          </button>
        );
      })}
    </div>
  );
}
