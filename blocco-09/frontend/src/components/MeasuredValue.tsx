import { ArrowDown, ArrowUp, Minus } from "lucide-react";
import type { Measured } from "@/api/types";
import { Icon } from "@/components/Icon";
import { Provenance } from "@/components/Provenance";
import { deltaTone, formatDelta, formatMeasured, type Better, type Tone } from "@/lib/format";
import { cn } from "@/lib/utils";

const TONE_CLASS: Record<Tone, string> = {
  better: "text-delta-better",
  worse: "text-delta-worse",
  neutral: "text-text-secondary",
};

interface MeasuredValueProps {
  measured: Measured;
  /** Che cosa si misura: il titolo del tooltip di provenienza. */
  label: string;
  /** `value` (default) è un numero con la sua unità; `delta` una differenza con segno, freccia e colore. */
  variant?: "value" | "delta";
  /** Per una differenza: se è meglio che scenda (tempi, ore-veicolo, carichi) o che salga. */
  better?: Better;
  showUnit?: boolean;
  className?: string;
  unitClassName?: string;
}

/** Il componente unico per **ogni** numero mostrato (07 7): valore in formato italiano, unità e
 * tooltip con fonte, metodo, input, assunzioni e ora del dato. Non si mostra un numero senza. */
export function MeasuredValue({
  measured,
  label,
  variant = "value",
  better = "none",
  showUnit = true,
  className,
  unitClassName,
}: MeasuredValueProps) {
  if (variant === "delta") {
    const shown = formatDelta(measured);
    const tone = deltaTone(shown.direction, better);
    const glyph =
      shown.direction === "up" ? ArrowUp : shown.direction === "down" ? ArrowDown : Minus;
    return (
      <Provenance
        measured={measured}
        label={label}
        data-tone={tone}
        className={cn(
          "inline-flex items-center gap-1 font-mono text-xs font-semibold tabular-nums",
          TONE_CLASS[tone],
          className,
        )}
      >
        <Icon icon={glyph} size="inline" />
        <span>{shown.text}</span>
        {showUnit && shown.unit && <span className="font-normal">{shown.unit}</span>}
      </Provenance>
    );
  }
  const shown = formatMeasured(measured);
  return (
    <Provenance measured={measured} label={label} className={cn("tabular-nums", className)}>
      <span>{shown.text}</span>
      {showUnit && shown.unit && (
        <span
          className={cn("ml-1.5 font-ui text-md font-normal text-text-secondary", unitClassName)}
        >
          {shown.unit}
        </span>
      )}
    </Provenance>
  );
}
