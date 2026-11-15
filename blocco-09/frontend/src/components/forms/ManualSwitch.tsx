import { cn } from "@/lib/utils";

/** L'interruttore «risposta manuale» del design (`nuo-switch`): un pulsante che è anche un
 * `switch`, con lo stato (On/Off) scritto e un suggerimento che dice che cosa cambia. */
export function ManualSwitch({
  checked,
  onChange,
  label,
  stateLabels,
  hint,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  stateLabels: { on: string; off: string };
  hint: string;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className="flex h-12 w-full items-center gap-space-12 rounded-control border-hairline border-border-strong bg-surface-2 px-3.5 text-left text-sm font-semibold text-text-primary"
      >
        <span
          aria-hidden
          className={cn(
            "relative block h-6 w-11 flex-none rounded-xl border-control border-border-strong bg-surface-3 transition-base",
            "after:absolute after:left-0.5 after:top-0.5 after:size-4 after:rounded-full after:bg-text-secondary after:transition-transform",
            checked && "after:translate-x-5 after:bg-action",
          )}
        />
        {label}
        <span
          className={cn(
            "ml-auto font-mono text-xs font-bold",
            checked ? "text-action-hover" : "text-text-secondary",
          )}
        >
          {checked ? stateLabels.on : stateLabels.off}
        </span>
      </button>
      <p className="text-xs text-text-secondary">{hint}</p>
    </div>
  );
}
