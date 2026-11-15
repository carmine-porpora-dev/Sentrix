import { Info, TriangleAlert, User, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { Icon } from "@/components/Icon";
import { cn } from "@/lib/utils";

type Tone = "warning" | "error" | "info";

const TONES: Record<Tone, { box: string; icon: LucideIcon; glyph: string; role?: "alert" }> = {
  warning: { box: "border-warning bg-state-fill-waiting", icon: User, glyph: "text-warning" },
  error: {
    box: "border-danger bg-state-fill-error",
    icon: TriangleAlert,
    glyph: "text-danger",
    role: "alert",
  },
  info: { box: "border-border-strong bg-surface-2", icon: Info, glyph: "text-text-secondary" },
};

/** Un riquadro che richiama l'attenzione: una decisione che aspetta una persona (giallo), un errore
 * (rosso, annunciato subito alle tecnologie assistive), un'informazione (neutro). L'icona e il
 * titolo dicono il tipo: non solo il colore. */
export function Callout({
  tone,
  title,
  children,
  icon,
  className,
}: {
  tone: Tone;
  title: string;
  children?: ReactNode;
  icon?: LucideIcon;
  className?: string;
}) {
  const style = TONES[tone];
  return (
    <div
      role={style.role}
      className={cn(
        "flex items-start gap-space-12 rounded-card border-control p-space-16",
        style.box,
        className,
      )}
    >
      <Icon icon={icon ?? style.icon} className={cn("mt-0.5", style.glyph)} />
      <div className="flex min-w-0 flex-col gap-1.5">
        <p className="text-md font-semibold text-text-primary">{title}</p>
        {children && <div className="text-sm text-text-secondary">{children}</div>}
      </div>
    </div>
  );
}
