import type { ButtonHTMLAttributes } from "react";

/** Un pulsante di testo con il contorno: scelte rapide e «Riprova». */
export function GhostButton(props: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      {...props}
      className="min-h-10 cursor-pointer rounded-control border border-border-strong bg-transparent px-3 text-md text-text transition-colors hover:bg-surface-2 disabled:cursor-not-allowed disabled:text-text-muted disabled:hover:bg-transparent"
    />
  );
}
