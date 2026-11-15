import type { LucideIcon } from "lucide-react";
import { Icon } from "@/components/Icon";
import { cn } from "@/lib/utils";

export type ChipTone = "pending" | "accepted" | "rejected" | "neutral";

const TONES: Record<ChipTone, string> = {
  pending: "border-status-pending bg-state-fill-waiting text-status-pending",
  accepted: "border-status-accepted bg-state-fill-done text-status-accepted",
  rejected: "border-status-rejected bg-state-fill-error text-status-rejected",
  neutral: "border-border-strong bg-surface-3 text-text-secondary",
};

/** L'etichetta di uno stato (di una richiesta, di una misura del piano): icona e testo nel colore del
 * suo tipo. Il testo c'è sempre: il colore da solo non basta. */
export function StateChip({
  tone,
  icon,
  label,
  className,
}: {
  tone: ChipTone;
  icon?: LucideIcon;
  label: string;
  className?: string;
}) {
  return (
    <span
      data-tone={tone}
      className={cn(
        "inline-flex h-size-chip-height w-fit flex-none items-center gap-space-8 whitespace-nowrap rounded-control border-hairline px-space-12 text-xs font-semibold",
        TONES[tone],
        className,
      )}
    >
      {icon && <Icon icon={icon} size="inline" />}
      {label}
    </span>
  );
}
