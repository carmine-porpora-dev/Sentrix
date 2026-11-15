import { FlaskConical } from "lucide-react";
import { Icon } from "@/components/Icon";
import { cn } from "@/lib/utils";
import { strings } from "@/i18n/it";

/** Il banner persistente «SIMULAZIONE» (07 2): in SCENARIO è sempre visibile. */
export function SimulationBanner({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex h-10 items-center gap-space-8 rounded-control bg-scenario-frame px-space-16 text-badge text-bg",
        className,
      )}
    >
      <Icon icon={FlaskConical} className="stroke-2" />
      {strings.shell.simulationBanner}
    </span>
  );
}
