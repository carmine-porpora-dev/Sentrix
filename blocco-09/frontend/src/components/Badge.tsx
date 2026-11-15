import { Activity, Clock, FlaskConical, Minus, Waves, type LucideIcon } from "lucide-react";
import { Icon } from "@/components/Icon";
import { cn } from "@/lib/utils";
import { strings } from "@/i18n/it";

export type BadgeKind = "real" | "estimate" | "simulated" | "unavailable" | "pending";

const STYLE: Record<BadgeKind, { icon: LucideIcon; classes: string }> = {
  real: { icon: Activity, classes: "border-data-real bg-badge-fill-real text-data-real" },
  estimate: {
    icon: Waves,
    classes: "border-data-estimate bg-badge-fill-estimate text-data-estimate",
  },
  simulated: {
    icon: FlaskConical,
    classes: "border-data-simulated bg-badge-fill-simulated text-data-simulated",
  },
  unavailable: {
    icon: Minus,
    classes:
      "border-dashed border-data-unavailable bg-badge-fill-unavailable text-data-unavailable normal-case",
  },
  pending: { icon: Clock, classes: "border-warning bg-badge-fill-pending text-warning" },
};

/** Il badge della natura di un dato: REALE (misurato), STIMA (modello), SIMULATO (ipotesi o simulazione). */
export function Badge({ kind, className }: { kind: BadgeKind; className?: string }) {
  const { icon, classes } = STYLE[kind];
  return (
    <span
      data-kind={kind}
      className={cn(
        "inline-flex h-size-badge-height items-center gap-1.5 whitespace-nowrap rounded-tag border-hairline px-2.5 text-badge uppercase",
        classes,
        className,
      )}
    >
      <Icon icon={icon} size="badge" />
      {strings.metrics.badges[kind]}
    </span>
  );
}
