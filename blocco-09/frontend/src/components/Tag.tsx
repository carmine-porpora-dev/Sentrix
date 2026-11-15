import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

interface TagProps {
  children: ReactNode;
  /** Il testo intero, se quello mostrato è accorciato. */
  title?: string;
  /** Un elemento di elenco (`li`) o inline (`span`). */
  as?: "li" | "span";
  /** Caratteri a larghezza fissa: identificativi, nomi di strumenti. */
  mono?: boolean;
  /** Il testo troppo lungo si accorcia con i puntini invece di andare a capo. */
  truncate?: boolean;
  className?: string;
}

/** L'etichetta piccola su fondo `surface-3` (nomi di strumenti, riferimenti del registro, evidenze). */
export function Tag({
  children,
  title,
  as: Element = "span",
  mono = true,
  truncate = false,
  className,
}: TagProps) {
  return (
    <Element
      title={title}
      className={cn(
        "max-w-full rounded-tag bg-surface-3 px-2 py-0.5 text-xs text-text-secondary",
        mono && "font-mono",
        truncate && "truncate",
        className,
      )}
    >
      {children}
    </Element>
  );
}
