import { useId, type KeyboardEvent, type ReactNode } from "react";
import { cn } from "@/lib/utils";

export interface TabItem<Id extends string = string> {
  id: Id;
  label: string;
}

interface TabsProps<Id extends string> {
  items: readonly TabItem<Id>[];
  active: Id;
  onChange: (id: Id) => void;
  /** Il nome della lista di schede per le tecnologie assistive. */
  label: string;
  /** Il contenuto della scheda attiva (il pannello). */
  children?: ReactNode;
  className?: string;
}

/** Le schede (Agenti · Operations · Decisioni): frecce e Home/Fine passano da una all'altra. */
export function Tabs<Id extends string>({
  items,
  active,
  onChange,
  label,
  children,
  className,
}: TabsProps<Id>) {
  const base = useId();
  const tabId = (id: string) => `${base}-tab-${id}`;
  const panelId = (id: string) => `${base}-panel-${id}`;

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const index = items.findIndex((item) => item.id === active);
    const last = items.length - 1;
    const target =
      event.key === "ArrowRight"
        ? (index + 1) % items.length
        : event.key === "ArrowLeft"
          ? (index - 1 + items.length) % items.length
          : event.key === "Home"
            ? 0
            : event.key === "End"
              ? last
              : undefined;
    if (target === undefined) return;
    event.preventDefault();
    const next = items[target];
    if (next) {
      onChange(next.id);
      document.getElementById(tabId(next.id))?.focus();
    }
  }

  return (
    <div className={cn("flex min-h-0 flex-col", className)}>
      <div
        role="tablist"
        aria-label={label}
        onKeyDown={onKeyDown}
        className="flex flex-none border-b-hairline border-border"
      >
        {items.map((item) => {
          const selected = item.id === active;
          return (
            <button
              key={item.id}
              id={tabId(item.id)}
              type="button"
              role="tab"
              aria-selected={selected}
              aria-controls={panelId(item.id)}
              tabIndex={selected ? 0 : -1}
              onClick={() => onChange(item.id)}
              className={cn(
                "-mb-px h-12 border-b-control border-transparent px-3.5 text-sm font-semibold text-text-secondary transition-base",
                "hover:text-text-primary",
                selected && "border-action text-text-primary",
              )}
            >
              {item.label}
            </button>
          );
        })}
      </div>
      <div
        role="tabpanel"
        id={panelId(active)}
        aria-labelledby={tabId(active)}
        className="min-h-0 flex-1 overflow-y-auto"
      >
        {children}
      </div>
    </div>
  );
}
