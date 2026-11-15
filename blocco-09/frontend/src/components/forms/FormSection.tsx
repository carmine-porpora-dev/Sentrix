import { ChevronDown } from "lucide-react";
import { useId, useState, type ReactNode } from "react";
import { Icon } from "@/components/Icon";
import { cn } from "@/lib/utils";

/** Una sezione del form con titolo e, a destra, un badge o un conteggio. Comprimibile: a chiuso
 * mostra solo il titolo, ma non perde nulla di ciò che c'è dentro (i campi restano nella pagina). */
export function FormSection({
  title,
  aside,
  defaultOpen = true,
  children,
}: {
  title: string;
  aside?: ReactNode;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const bodyId = useId();
  return (
    <section aria-label={title} className="border-b-hairline border-border">
      <h3 className="flex items-center gap-space-8 px-space-16">
        <button
          type="button"
          aria-expanded={open}
          aria-controls={bodyId}
          onClick={() => setOpen(!open)}
          className="flex h-11 flex-1 items-center gap-space-8 text-left text-sm font-semibold text-text-primary"
        >
          <Icon
            icon={ChevronDown}
            className={cn("text-text-secondary transition-transform", !open && "-rotate-90")}
          />
          {title}
        </button>
        {aside}
      </h3>
      <div
        id={bodyId}
        hidden={!open}
        className="flex flex-col gap-space-12 px-space-16 pb-space-16"
      >
        {children}
      </div>
    </section>
  );
}
