import { Check, Clock, TriangleAlert, User, type LucideIcon } from "lucide-react";
import { Icon } from "@/components/Icon";
import { cn } from "@/lib/utils";
import {
  RUN_STEPS,
  runKind,
  runStepIndex,
  type RunDisplay,
  type RunKind,
} from "@/features/shell/run";
import { strings } from "@/i18n/it";

const CHIP: Record<RunKind, string> = {
  run: "border-action bg-state-fill-running",
  warn: "border-warning bg-state-fill-waiting",
  done: "border-data-real bg-state-fill-done",
  error: "border-danger bg-state-fill-error",
};
/** Il colore dell'icona del chip e quello del puntino pulsante (lo stesso del bordo). */
const GLYPH: Record<RunKind, string> = {
  run: "text-action",
  warn: "text-warning",
  done: "text-data-real",
  error: "text-danger",
};
const DOT: Record<RunKind, string> = {
  run: "bg-action",
  warn: "bg-warning",
  done: "bg-data-real",
  error: "bg-danger",
};
const ICONS: Partial<Record<RunDisplay, LucideIcon>> = {
  AWAIT: Clock,
  DONE: Check,
  ERROR: TriangleAlert,
  DECISION_REQUIRED: User,
};

interface RunStatusProps {
  state: RunDisplay;
  /** La tappa a cui si è arrivati, per gli stati che non sono nella sequenza (errore, decisione). */
  step?: number;
}

/** Lo stato del run: un chip con il nome e la barra di avanzamento a nove tappe. */
export function RunStatus({ state, step }: RunStatusProps) {
  const kind = runKind(state);
  const current = runStepIndex(state, step);
  const glyph = ICONS[state];
  const finished = state === "DONE";
  return (
    <div className="flex flex-col gap-space-8">
      <span
        title={state}
        className={cn(
          "inline-flex h-size-chip-height w-fit items-center gap-space-8 whitespace-nowrap rounded-control border-hairline px-space-12 text-xs font-semibold text-text-primary",
          CHIP[kind],
        )}
      >
        {glyph ? (
          <Icon icon={glyph} size="inline" className={GLYPH[kind]} />
        ) : (
          <span
            aria-hidden
            className={cn("size-2 flex-none rounded-full motion-safe:animate-pulse", DOT[kind])}
          />
        )}
        {strings.shell.runStates[state]}
      </span>
      <div
        role="progressbar"
        aria-label={strings.shell.progressLabel}
        aria-valuemin={1}
        aria-valuemax={RUN_STEPS.length}
        aria-valuenow={finished ? RUN_STEPS.length : current + 1}
        aria-valuetext={strings.shell.runStates[state]}
        className="flex gap-space-4"
      >
        {RUN_STEPS.map((name, index) => {
          const done = index < current || finished;
          const active = index === current && !finished;
          return (
            <i
              key={name}
              data-step={done ? "done" : active ? "current" : "todo"}
              className={cn(
                "h-1 flex-1 rounded-sm bg-surface-3",
                done && (finished ? "bg-data-real" : "bg-action"),
                active && kind === "run" && "bg-action motion-safe:animate-pulse",
                active && kind === "warn" && "bg-warning",
                active && kind === "error" && "bg-danger",
              )}
            />
          );
        })}
      </div>
    </div>
  );
}
