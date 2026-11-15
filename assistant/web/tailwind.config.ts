import type { Config } from "tailwindcss";

const color = (name: string) => `var(--color-${name})`;

// I valori vivono in design/design-system/tokens.css e in src/styles/assistant-tokens.css:
// qui le classi puntano alle variabili, non si scrive nessun valore.
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}", "!./src/**/*.test.{ts,tsx}"],
  theme: {
    screens: { sm: "600px" },
    colors: {
      transparent: "transparent",
      current: "currentColor",
      inherit: "inherit",
      bg: color("bg"),
      "surface-1": color("surface-1"),
      "surface-2": color("surface-2"),
      "surface-3": color("surface-3"),
      border: color("border"),
      "border-strong": color("border-strong"),
      "border-card": color("border-card"),
      text: color("text"),
      "text-secondary": color("text-secondary"),
      "text-muted": color("text-muted"),
      accent: color("accent"),
      "accent-hover": color("accent-hover"),
      danger: color("danger"),
      "chat-user-fill": color("chat-user-fill"),
      "scenario-frame": color("scenario-frame"),
      "data-real": color("data-real"),
      "data-estimate": color("data-estimate"),
      "data-simulated": color("data-simulated"),
      "badge-fill-real": color("badge-fill-real"),
      "badge-fill-estimate": color("badge-fill-estimate"),
      "badge-fill-simulated": color("badge-fill-simulated"),
      // il segnaposto del reset di Tailwind legge `gray.400`: nel design è il testo secondario
      gray: { 400: color("text-secondary") },
    },
    extend: {
      borderColor: { DEFAULT: color("border") },
      // Tailwind scrive sempre anello e scostamento in `*`: puntati ai token, nessun blu di Tailwind
      ringColor: { DEFAULT: (() => "var(--focus-ring)") as unknown as string },
      ringOffsetColor: { DEFAULT: color("bg") },
      fontFamily: { ui: ["var(--font-ui)"], mono: ["var(--font-mono)"] },
      fontSize: {
        "2xl": [
          "var(--fs-2xl)",
          { lineHeight: "var(--lh-2xl)", letterSpacing: "var(--ls-2xl)", fontWeight: "700" },
        ],
        lg: ["var(--fs-lg)", { lineHeight: "var(--lh-lg)", fontWeight: "600" }],
        md: ["var(--fs-md)", { lineHeight: "var(--lh-md)" }],
        xs: ["var(--fs-xs)", { lineHeight: "var(--lh-xs)", fontWeight: "500" }],
        badge: [
          "var(--fs-badge)",
          { lineHeight: "var(--lh-badge)", letterSpacing: "var(--ls-badge)", fontWeight: "600" },
        ],
      },
      borderRadius: {
        card: "var(--radius-card)",
        control: "var(--radius-control)",
        field: "var(--radius-field)",
        tag: "var(--radius-tag)",
      },
      transitionDuration: { DEFAULT: "var(--motion-duration)" },
      transitionTimingFunction: { DEFAULT: "ease-out" },
      keyframes: {
        enter: {
          from: { opacity: "0", transform: "translateY(8px)" },
          to: { opacity: "1", transform: "none" },
        },
        typing: { "0%, 100%": { opacity: "0.3" }, "50%": { opacity: "1" } },
      },
      animation: {
        enter: "enter var(--motion-enter) ease-out both",
        typing: "typing var(--motion-typing) ease-in-out infinite",
      },
    },
  },
} satisfies Config;
