import { CalendarClock, ChevronDown, ChevronUp } from "lucide-react";
import type { ReactNode } from "react";
import { Icon } from "@/components/Icon";
import { IconButton } from "@/components/IconButton";
import { strings } from "@/i18n/it";

/** Il chip «In corso» (run in esecuzione) dell'intestazione e del binario. */
export function RunningChip() {
  return (
    <span className="inline-flex h-8 w-fit items-center gap-space-8 whitespace-nowrap rounded-control border-hairline border-action bg-state-fill-running px-space-12 text-xs font-semibold text-text-primary">
      <span
        aria-hidden
        className="size-2 flex-none rounded-full bg-action motion-safe:animate-pulse"
      />
      {strings.shell.eventManager.running}
    </span>
  );
}

interface PanelProps {
  open: boolean;
  onToggle: () => void;
  running?: boolean;
  /** Senza un run da seguire l'intestazione non ha la freccia (design 01–03): il pannello è l'unico contenuto. */
  collapsible?: boolean;
  children?: ReactNode;
}

/** La colonna dell'Event Manager: aperta è una scheda con intestazione (e il form, F4-06);
 * compressa è un binario stretto con l'icona e lo stato (design: EventManagerHeader/Rail). */
export function EventManagerPanel({
  open,
  onToggle,
  running = false,
  collapsible = true,
  children,
}: PanelProps) {
  const copy = strings.shell.eventManager;
  if (!open) {
    return (
      <button
        type="button"
        aria-expanded={false}
        aria-label={copy.title}
        onClick={onToggle}
        className="flex w-full flex-col items-center gap-space-12 self-start rounded-card border-hairline border-border-card bg-surface-1 px-space-8 py-space-12 text-text-primary transition-base hover:bg-surface-2"
      >
        <span className="flex items-center gap-space-8">
          <Icon icon={CalendarClock} className="text-action" />
          <Icon icon={ChevronDown} className="text-text-secondary" />
        </span>
        {running && <RunningChip />}
      </button>
    );
  }
  return (
    <section
      aria-label={copy.title}
      className="flex min-h-0 flex-col overflow-hidden rounded-card border-hairline border-border-card bg-surface-1"
    >
      <header className="flex h-14 flex-none items-center gap-space-12 border-b-hairline border-border px-space-16">
        <Icon icon={CalendarClock} className="text-action" />
        <h2 className="text-lg">{copy.title}</h2>
        {running && <RunningChip />}
        <span className="flex-1" />
        {collapsible && (
          <IconButton
            icon={ChevronUp}
            label={copy.collapse}
            on="surface-1"
            aria-expanded
            onClick={onToggle}
          />
        )}
      </header>
      <div className="flex min-h-0 flex-1 flex-col">{children}</div>
    </section>
  );
}
