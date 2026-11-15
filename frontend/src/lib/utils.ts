import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";
import { tokenTheme } from "@/styles/tailwind-theme.generated";

// tailwind-merge non conosce i nomi dei token del designer: senza questo `text-kpi` sarebbe preso per
// un colore (e butterebbe via `text-text-primary`) e `border-hairline` per un colore del bordo.
// I nomi vengono dal tema generato (`npm run tokens`), così restano allineati.
const twMerge = extendTailwindMerge({
  extend: {
    classGroups: {
      "font-size": [{ text: Object.keys(tokenTheme.fontSize) }],
      "border-w": [{ border: Object.keys(tokenTheme.borderWidth) }],
      rounded: [{ rounded: Object.keys(tokenTheme.borderRadius) }],
    },
  },
});

/** Unisce le classi (clsx) e risolve i conflitti Tailwind: vince l'ultima. */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
