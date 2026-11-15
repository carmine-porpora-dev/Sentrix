import type { LucideIcon } from "lucide-react";
import type { ButtonHTMLAttributes } from "react";
import { Icon } from "@/components/Icon";
import { cn } from "@/lib/utils";

/** Su che sfondo sta: il passaggio del mouse si vede un gradino più in là (design: `surface-1` →
 * `surface-2`, `surface-2` → `surface-3`). */
const HOVER = { "surface-1": "hover:bg-surface-2", "surface-2": "hover:bg-surface-3" } as const;

interface IconButtonProps extends Omit<
  ButtonHTMLAttributes<HTMLButtonElement>,
  "className" | "children" | "aria-label"
> {
  icon: LucideIcon;
  /** Il nome del pulsante (assistivo e suggerimento): senza testo visibile, serve sempre. */
  label: string;
  on?: keyof typeof HOVER;
  /** Mostra `label` anche come suggerimento del mouse. */
  tooltip?: boolean;
}

/** Il pulsante di sola icona (chip 32 px, senza bordo): comprimere un pannello, togliere una riga,
 * mostrare sulla mappa. */
export function IconButton({
  icon,
  label,
  on = "surface-2",
  tooltip = false,
  type = "button",
  ...rest
}: IconButtonProps) {
  return (
    <button
      type={type}
      aria-label={label}
      title={tooltip ? label : undefined}
      className={cn(
        "grid size-size-chip-height flex-none place-items-center rounded-control text-text-secondary transition-base hover:text-text-primary",
        HOVER[on],
      )}
      {...rest}
    >
      <Icon icon={icon} />
    </button>
  );
}
