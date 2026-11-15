import type { LucideIcon } from "lucide-react";
import { Icon } from "@/components/Icon";
import { cn } from "@/lib/utils";
import { strings } from "@/i18n/it";

export interface SidebarItem<Id extends string = string> {
  id: Id;
  icon: LucideIcon;
  label: string;
}

interface SidebarProps<Id extends string> {
  items: readonly SidebarItem<Id>[];
  active: Id;
  onSelect: (id: Id) => void;
}

function SidebarButton({
  icon,
  label,
  active,
  onClick,
}: Pick<SidebarItem, "icon" | "label"> & { active: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      aria-current={active ? "page" : undefined}
      onClick={onClick}
      className={cn(
        "grid size-size-sidebar-button place-items-center rounded-control border-control border-transparent text-text-secondary transition-base",
        "hover:bg-surface-2 hover:text-text-primary",
        active && "border-action bg-surface-2 text-action hover:text-action",
      )}
    >
      <Icon icon={icon} size="sidebar" />
    </button>
  );
}

/** La barra laterale (72 px): il marchio e le tre sezioni. */
export function Sidebar<Id extends string>({ items, active, onSelect }: SidebarProps<Id>) {
  return (
    <nav
      aria-label={strings.shell.navLabel}
      className="flex h-full w-size-sidebar-width flex-none flex-col items-center gap-space-8 border-r-hairline border-border bg-surface-1 py-space-16"
    >
      <div
        title={strings.appName}
        className="mb-space-8 grid size-size-control-height place-items-center rounded-control bg-action text-xs font-bold text-bg"
      >
        {strings.shell.brand}
      </div>
      <div className="flex flex-col items-center gap-space-8">
        {items.map((item) => (
          <SidebarButton
            key={item.id}
            icon={item.icon}
            label={item.label}
            active={item.id === active}
            onClick={() => onSelect(item.id)}
          />
        ))}
      </div>
    </nav>
  );
}
