import type { Config } from "tailwindcss";
import animate from "tailwindcss-animate";
import plugin from "tailwindcss/plugin.js";
import { tokenTheme, tokenUtilities } from "./src/styles/tailwind-theme.generated.ts";

// Il tema viene dai token del designer (design/design-system/tokens.json) attraverso
// scripts/tokens-to-tailwind.ts (`npm run tokens`): colori, font, corpi del testo, misure, angoli.
// Qui non si scrive nessun valore (07 1). Le classi puntano alle variabili CSS di
// src/styles/tokens.generated.css.
export default {
  darkMode: ["class"],
  // i test non sono sorgenti di classi: le stringhe di prova non devono finire nel CSS
  content: ["./index.html", "./src/**/*.{ts,tsx}", "!./src/**/*.test.{ts,tsx}"],
  theme: {
    // `colors` sostituisce la palette di Tailwind (non la estende): `bg-white`, `text-red-500` e simili
    // non esistono, restano solo i token (F4-REF). Il reset di base (preflight) e i valori
    // predefiniti che Tailwind scrive sempre (bordo, segnaposto, anello) li puntiamo ai token, così
    // nel CSS compilato non resta nessun colore di Tailwind (lo verifica src/styles/build.test.ts).
    colors: {
      transparent: "transparent",
      current: "currentColor",
      inherit: "inherit",
      ...tokenTheme.colors,
      // il segnaposto del preflight legge `colors.gray.400`: nel design è il testo secondario
      gray: { 400: "var(--color-text-secondary)" },
    },
    extend: {
      borderColor: { DEFAULT: "var(--color-border)" },
      // Tailwind scrive sempre in `*` anello e scostamento dell'anello, anche se `ring` non si usa.
      // Una stringa `var()` non la sa leggere (per aggiungerle la trasparenza) e ripiega sul suo blu;
      // una funzione sì. I tipi di Tailwind non la ammettono qui, a runtime sì (colori con `<alpha-value>`).
      ringColor: { DEFAULT: (() => "var(--focus-ring)") as unknown as string },
      ringOffsetColor: { DEFAULT: "var(--color-bg)" },
      fontFamily: tokenTheme.fontFamily,
      fontSize: tokenTheme.fontSize,
      spacing: tokenTheme.spacing,
      strokeWidth: tokenTheme.strokeWidth,
      borderRadius: tokenTheme.borderRadius,
      borderWidth: tokenTheme.borderWidth,
      opacity: tokenTheme.opacity,
      transitionDuration: tokenTheme.transitionDuration,
      transitionTimingFunction: tokenTheme.transitionTimingFunction,
      screens: tokenTheme.screens,
    },
  },
  plugins: [animate, plugin(({ addUtilities }) => addUtilities(tokenUtilities))],
} satisfies Config;
