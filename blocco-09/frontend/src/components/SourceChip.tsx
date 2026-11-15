import { ChevronDown, TriangleAlert } from "lucide-react";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { Icon } from "@/components/Icon";
import { cn } from "@/lib/utils";

/** Il chip «Fonte non disponibile: TomTom» (design 02): giallo, con il popover che dice cosa succede.
 * Si apre al clic e si chiude con un secondo clic, con Esc o cliccando fuori; l'icona e il testo dicono
 * lo stato (non solo il colore). */
export function SourceChip({
  label,
  title,
  children,
}: {
  /** «Fonte non disponibile: TomTom». */
  label: string;
  /** Il nome della fonte, in grassetto nel popover. */
  title: string;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const popoverId = useId();

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    const onPointer = (event: PointerEvent) => {
      if (root.current && !root.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointer);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointer);
    };
  }, [open]);

  return (
    <div ref={root} className="relative">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={open ? popoverId : undefined}
        onClick={() => setOpen(!open)}
        className="inline-flex h-size-chip-height items-center gap-space-8 whitespace-nowrap rounded-control border-hairline border-status-pending bg-state-fill-waiting px-space-12 text-xs font-semibold text-status-pending transition-base hover:bg-surface-2"
      >
        <Icon icon={TriangleAlert} size="inline" />
        {label}
        <Icon icon={ChevronDown} size="inline" className={cn(open && "rotate-180")} />
      </button>
      {open && (
        <div
          id={popoverId}
          role="dialog"
          aria-label={label}
          className="absolute left-0 top-full z-50 mt-space-8 flex w-[300px] flex-col gap-1.5 rounded-control border-hairline border-border-tooltip bg-surface-1 p-space-12 text-sm text-text-secondary"
        >
          <p className="font-semibold text-text-primary">{title}</p>
          {children}
        </div>
      )}
    </div>
  );
}
