import { cn } from "@/lib/utils";
import { strings } from "@/i18n/it";

/** «Iterazione n di 3» con una tacca per iterazione. */
export function IterationIndicator({ current, total }: { current: number; total: number }) {
  return (
    <div className="inline-flex items-center gap-space-12">
      <span className="whitespace-nowrap text-xs font-semibold text-text-primary">
        {strings.shell.iteration(current, total)}
      </span>
      <span aria-hidden className="flex gap-space-4">
        {Array.from({ length: total }, (_, index) => (
          <i
            key={index}
            data-on={index < current}
            className={cn(
              "h-size-progress-bar w-7 rounded-full bg-surface-3",
              index < current && "bg-action",
            )}
          />
        ))}
      </span>
    </div>
  );
}
