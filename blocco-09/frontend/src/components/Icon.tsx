import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

// Le dimensioni sono quelle dei token (`size-icon*`); `inline` è il 16 px delle icone dentro un chip
// (`space-16`) e `badge` il 14 px di quelle dei badge. Lo spessore del tratto è `size-icon-stroke`.
const SIZES = {
  badge: "size-3.5",
  inline: "size-space-16",
  icon: "size-size-icon",
  sidebar: "size-size-icon-sidebar",
  marker: "size-size-icon-marker",
} as const;

export type IconSize = keyof typeof SIZES;

interface IconProps {
  icon: LucideIcon;
  size?: IconSize;
  className?: string;
}

/** Un'icona Lucide decorativa (nascosta alle tecnologie assistive: il testo sta nel pulsante). */
export function Icon({ icon: Glyph, size = "icon", className }: IconProps) {
  return (
    <Glyph
      aria-hidden
      className={cn("flex-none stroke-size-icon-stroke", SIZES[size], className)}
    />
  );
}
