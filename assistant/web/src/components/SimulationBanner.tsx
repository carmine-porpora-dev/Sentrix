import { FlaskConical } from "lucide-react";
import { strings } from "@/strings";

/** Lo scenario è una simulazione: la riga fissa con il badge SIMULAZIONE (10 §6), sempre visibile. */
export function SimulationBanner() {
  return (
    <div className="relative z-[2] flex flex-none flex-wrap items-center gap-x-3 gap-y-1 px-4 pb-2 pt-1">
      <span className="inline-flex h-6 items-center gap-1.5 rounded-control bg-scenario-frame px-2 text-badge uppercase text-bg">
        <FlaskConical aria-hidden="true" size={14} strokeWidth={2} />
        {strings.simulation.badge}
      </span>
      <span className="text-xs text-text-secondary">{strings.simulation.scenario}</span>
    </div>
  );
}
