import { Bus, MapPin, Route, TrainFront, type LucideIcon } from "lucide-react";
import type { ChipKind } from "@/lib/answer";

const ICONS: Record<ChipKind, LucideIcon> = {
  strada: Route,
  linea: TrainFront,
  fermata: Bus,
  luogo: MapPin,
};

/** Strada, linea, fermata o luogo citati nella risposta. Solo visivo: non è un pulsante. */
export function EntityChip({ kind, label }: { kind: ChipKind; label: string }) {
  const Icon = ICONS[kind];
  return (
    <span
      data-chip={kind}
      className="inline-flex h-6 max-w-full cursor-default items-center gap-1 rounded-control border border-border-strong bg-surface-3 px-2 align-middle font-mono text-xs text-text"
    >
      <Icon
        aria-hidden="true"
        size={14}
        strokeWidth={1.5}
        className="flex-none text-text-secondary"
      />
      <span className="truncate">{label}</span>
    </span>
  );
}
