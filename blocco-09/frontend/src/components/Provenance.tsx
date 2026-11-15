import {
  forwardRef,
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type HTMLAttributes,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import type { Measured } from "@/api/types";
import { Badge, type BadgeKind } from "@/components/Badge";
import { displayUnit, formatAsOf } from "@/lib/format";
import { cn } from "@/lib/utils";
import { strings } from "@/i18n/it";

const copy = strings.metrics.provenance;
const MARGIN = 8; // distanza minima dai bordi della finestra, in px
const GAP = 6; // distanza dall'elemento
/** Quanto resta aperto dopo che il mouse è uscito: il tempo di passare dal numero al tooltip (che
 * può coprirlo, o avere un varco di `GAP` px) senza che si chiuda. */
const CLOSE_DELAY_MS = 150;

const NUMBER = /(\d[\d.,:/–-]*\d|\d)/;

/** Cifre, orari e date in monospazio (come nel prototipo), a capo solo tra una e l'altra. */
function Digits({ children }: { children: ReactNode }) {
  return <span className="whitespace-nowrap font-mono tabular-nums">{children}</span>;
}

/** Un testo nel carattere dell'interfaccia con i numeri in monospazio (design, schermata 12): si
 * separano solo le sequenze di cifre, il testo resta quello. */
function MixedText({ text }: { text: string }) {
  return (
    <>
      {text
        .split(NUMBER)
        .map((part, index) => (index % 2 === 1 ? <Digits key={index}>{part}</Digits> : part))}
    </>
  );
}

/** Il contenuto del tooltip di provenienza (07 7): fonte, metodo, input, unità, ora del dato e
 * assunzioni di un `Measured`. Non mostra numeri: i numeri passano da `MeasuredValue`. */
export const ProvenanceTooltip = forwardRef<
  HTMLDivElement,
  {
    measured: Measured;
    title: string;
    id: string;
    style?: React.CSSProperties;
    onMouseEnter?: () => void;
    onMouseLeave?: () => void;
  }
>(function ProvenanceTooltip({ measured, title, id, style, onMouseEnter, onMouseLeave }, ref) {
  const unit = displayUnit(measured.unit);
  const unitText =
    measured.unit === "testo"
      ? measured.unit
      : unit && unit !== measured.unit
        ? copy.shownAs(measured.unit, unit)
        : measured.unit;
  const rows: [string, string[]][] = [
    [copy.source, [measured.source]],
    [copy.method, [measured.method]],
    [copy.inputs, measured.inputs],
    [copy.unit, [unitText]],
    [copy.asOf, [formatAsOf(measured.as_of)]],
  ];
  if (measured.assumptions && measured.assumptions.length > 0) {
    rows.push([copy.assumptions, measured.assumptions]);
  }
  return (
    <div
      ref={ref}
      id={id}
      role="tooltip"
      style={style}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
      // più alto dello schermo (le metriche del TPL hanno una ventina di assunzioni): si scorre
      className="fixed z-50 flex max-h-[calc(100vh-1rem)] w-[340px] flex-col gap-1.5 overflow-y-auto overscroll-contain rounded-tooltip border-hairline border-border-tooltip bg-surface-2 px-2.5 py-2 text-xs text-text-primary"
    >
      <div className="flex items-center justify-between gap-space-8">
        <span className="text-md font-semibold">{title}</span>
        <Badge kind={measured.kind as BadgeKind} />
      </div>
      {rows.map(([name, lines]) => (
        <div key={name} className="grid grid-cols-[5.5rem_minmax(0,1fr)] gap-space-8">
          <span className="text-text-secondary">{name}</span>
          <span className="flex flex-col">
            {lines.map((line, index) => (
              <span key={index}>
                {name === copy.asOf ? <Digits>{line}</Digits> : <MixedText text={line} />}
              </span>
            ))}
          </span>
        </div>
      ))}
    </div>
  );
});

interface ProvenanceProps extends Omit<HTMLAttributes<HTMLSpanElement>, "children"> {
  measured: Measured;
  /** Il titolo del tooltip: che cosa si misura («Ore-veicolo»). */
  label: string;
  children: ReactNode;
}

/** Rende focalizzabile ciò che mostra un numero e, al passaggio del mouse o con il fuoco, apre sotto
 * di esso il tooltip di provenienza. Il tooltip sta in un portale a posizione fissa: non lo taglia
 * nessuna scheda e non esce dallo schermo (se è più alto, si scorre con la rotella). Resta aperto
 * finché il mouse sta sul numero o sul tooltip; Esc lo chiude. */
export function Provenance({ measured, label, children, className, ...rest }: ProvenanceProps) {
  const id = useId();
  const anchor = useRef<HTMLSpanElement>(null);
  const bubble = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null);

  const place = useCallback(() => {
    // dentro una card il tooltip sta sotto la card, allineato a sinistra (design, schermata 12)
    const host = anchor.current?.closest("[data-tooltip-anchor]");
    const target = (host ?? anchor.current)?.getBoundingClientRect();
    if (!target) return;
    const width = bubble.current?.offsetWidth ?? 0;
    const height = bubble.current?.offsetHeight ?? 0;
    const left = Math.min(Math.max(target.left, MARGIN), window.innerWidth - width - MARGIN);
    // sotto l'elemento; se non ci sta, sopra
    const below = target.bottom + GAP;
    const top =
      below + height > window.innerHeight - MARGIN
        ? Math.max(target.top - GAP - height, MARGIN)
        : below;
    setPosition({ top, left });
  }, []);

  useLayoutEffect(() => {
    if (open) place();
  }, [open, place]);

  const closeTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const cancelClose = () => clearTimeout(closeTimer.current);
  const show = () => {
    cancelClose();
    setOpen(true);
  };
  const hide = () => {
    setOpen(false);
    setPosition(null);
  };
  // il mouse esce dal numero o dal tooltip: si chiude dopo un attimo, se non è entrato nell'altro
  const hideSoon = () => {
    cancelClose();
    closeTimer.current = setTimeout(hide, CLOSE_DELAY_MS);
  };
  useEffect(() => () => clearTimeout(closeTimer.current), []);

  return (
    <>
      <span
        ref={anchor}
        tabIndex={0}
        data-measured={measured.kind}
        aria-describedby={open ? id : undefined}
        onMouseEnter={show}
        onMouseLeave={hideSoon}
        onFocus={show}
        onBlur={hide}
        onKeyDown={(event) => {
          if (event.key === "Escape") hide();
        }}
        className={cn("rounded-tooltip", className)}
        {...rest}
      >
        {children}
      </span>
      {open &&
        createPortal(
          <ProvenanceTooltip
            ref={bubble}
            measured={measured}
            title={label}
            id={id}
            style={position ?? { top: 0, left: 0, visibility: "hidden" }}
            onMouseEnter={show}
            onMouseLeave={hideSoon}
          />,
          document.body,
        )}
    </>
  );
}
