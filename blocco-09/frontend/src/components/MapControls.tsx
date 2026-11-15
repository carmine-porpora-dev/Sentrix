import {
  Ban,
  Car,
  Check,
  ChevronLeft,
  ChevronRight,
  Layers,
  Navigation,
  Ticket,
  Users,
  X,
  type LucideIcon,
} from "lucide-react";
import type { PlannedSensor } from "@/api/types";
import { Icon } from "@/components/Icon";
import { DEPARTMENTS, type MarkerState } from "@/lib/departments";
import { cn } from "@/lib/utils";
import { strings } from "@/i18n/it";

const copy = strings.map;

/** Il pulsante che apre il pannello dei livelli. */
export function LayerToggleButton({
  open,
  onToggle,
  className,
}: {
  open: boolean;
  onToggle: () => void;
  className?: string;
}) {
  return (
    <button
      type="button"
      aria-expanded={open}
      aria-label={copy.layersButton}
      onClick={onToggle}
      className={cn(
        "grid size-size-control-height place-items-center rounded-control border-control border-border-strong bg-surface-1 text-text-primary transition-base hover:bg-surface-2",
        open && "border-action text-action",
        className,
      )}
    >
      <Icon icon={Layers} />
    </button>
  );
}

export interface LayerItem {
  id: string;
  name: string;
  on: boolean;
  /** Il colore del campione (una variabile CSS del design: `var(--color-map-…)`). */
  color: string;
  dashed?: boolean;
}

/** Un'opzione della vista, senza campione di colore (la vista presentazione). */
export interface OptionItem {
  id: string;
  name: string;
  on: boolean;
}

/** La casella di spunta del pannello dei livelli e dell'interruttore in legenda: una sola. */
function CheckBox({ on }: { on: boolean }) {
  return (
    <span
      className={cn(
        "grid size-[18px] flex-none place-items-center rounded-sm border-control border-text-muted text-bg",
        on && "border-action bg-action",
      )}
    >
      {on && <Icon icon={Check} className="size-3 stroke-[3]" />}
    </span>
  );
}

/** Una riga del pannello: la casella, il campione se c'è, il nome. */
function CheckRow({
  name,
  on,
  onClick,
  swatch,
}: {
  name: string;
  on: boolean;
  onClick: () => void;
  swatch?: Pick<LayerItem, "color" | "dashed">;
}) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={on}
      onClick={onClick}
      className={cn(
        "flex h-size-layer-row-height w-full items-center gap-2.5 rounded-control px-space-8 text-left text-xs font-medium text-text-primary transition-base hover:bg-surface-2",
        !on && "text-text-secondary",
      )}
    >
      <CheckBox on={on} />
      {swatch && (
        <span
          data-dashed={swatch.dashed ? "true" : undefined}
          style={{ "--swatch": swatch.color } as React.CSSProperties}
          className={cn(
            "h-1 w-[22px] flex-none rounded-sm bg-[var(--swatch)]",
            swatch.dashed &&
              "bg-[repeating-linear-gradient(90deg,var(--swatch)_0_6px,transparent_6px_10px)]",
            !on && "opacity-40",
          )}
        />
      )}
      <span>{name}</span>
    </button>
  );
}

/** Il pannello dei livelli: una casella per ognuno, con il suo campione di colore, e sotto le
 * opzioni della vista (senza campione). */
export function LayerPanel({
  layers,
  onToggle,
  options = [],
  onOption,
}: {
  layers: readonly LayerItem[];
  onToggle: (id: string) => void;
  options?: readonly OptionItem[];
  onOption?: (id: string) => void;
}) {
  return (
    <div
      role="group"
      aria-label={copy.layersTitle}
      className="w-size-layer-panel-width rounded-card border-hairline border-border-strong bg-surface-1 p-space-8"
    >
      <div className="px-space-8 pb-1.5 pt-1 text-xs font-semibold text-text-secondary">
        {copy.layersTitle}
      </div>
      {layers.map((layer) => (
        <CheckRow
          key={layer.id}
          name={layer.name}
          on={layer.on}
          swatch={layer}
          onClick={() => onToggle(layer.id)}
        />
      ))}
      {options.length > 0 && (
        <div className="mt-1 border-t-hairline border-border pt-1">
          {options.map((option) => (
            <CheckRow
              key={option.id}
              name={option.name}
              on={option.on}
              onClick={() => onOption?.(option.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

interface MapToggleProps {
  after: boolean;
  onAfterChange: (after: boolean) => void;
  /** L'iterazione mostrata con «Dopo» (da 1) e quante ce ne sono. */
  iteration: number;
  onIterationChange: (iteration: number) => void;
  iterations: number;
  /** Come si chiama quell'iterazione a schermo (il numero lo decide chi chiama: deve essere lo
   * stesso della barra in alto). */
  label: string;
}

/** Prima / Dopo (iterazione 0 contro quella scelta) e il selettore dell'iterazione. */
export function MapToggle({
  after,
  onAfterChange,
  iteration,
  onIterationChange,
  iterations,
  label: iterationLabel,
}: MapToggleProps) {
  const step = (by: number) =>
    onIterationChange(((iteration - 1 + by + iterations) % iterations) + 1);
  const label = (active: boolean) =>
    cn("border-0 bg-transparent p-0 text-text-secondary", active && "text-text-primary");
  return (
    <div className="inline-flex flex-wrap items-center gap-space-8">
      <div className="flex h-size-control-height items-center gap-2.5 rounded-control border-hairline border-border-strong bg-surface-1 px-space-12 text-xs font-semibold">
        <button type="button" className={label(!after)} onClick={() => onAfterChange(false)}>
          {copy.before}
        </button>
        <button
          type="button"
          role="switch"
          aria-checked={after}
          aria-label={copy.beforeAfter}
          onClick={() => onAfterChange(!after)}
          className="border-0 bg-transparent p-0"
        >
          <span
            className={cn(
              "relative block h-6 w-11 rounded-xl border-control border-border-strong bg-surface-3 transition-base",
              "after:absolute after:left-0.5 after:top-0.5 after:size-4 after:rounded-full after:bg-text-secondary after:transition-transform",
              after && "after:translate-x-5 after:bg-action",
            )}
          />
        </button>
        <button type="button" className={label(after)} onClick={() => onAfterChange(true)}>
          {copy.after}
        </button>
      </div>
      <div
        className={cn(
          "flex h-size-control-height items-center gap-2.5 rounded-control border-hairline border-border-strong bg-surface-1 px-[5px] text-xs font-semibold",
          !after && "opacity-50",
        )}
      >
        <button
          type="button"
          aria-label={copy.previousIteration}
          disabled={!after}
          onClick={() => step(-1)}
          className="grid size-[34px] place-items-center rounded-control text-text-primary transition-base hover:bg-surface-2 disabled:hover:bg-transparent"
        >
          <Icon icon={ChevronLeft} />
        </button>
        <span aria-live="polite" className="min-w-[110px] text-center">
          {iterationLabel}
        </span>
        <button
          type="button"
          aria-label={copy.nextIteration}
          disabled={!after}
          onClick={() => step(1)}
          className="grid size-[34px] place-items-center rounded-control text-text-primary transition-base hover:bg-surface-2 disabled:hover:bg-transparent"
        >
          <Icon icon={ChevronRight} />
        </button>
      </div>
    </div>
  );
}

const CONGESTION_SWATCH = [
  "bg-map-congestion-1",
  "bg-map-congestion-2",
  "bg-map-congestion-3",
  "bg-map-congestion-4",
] as const;

const SENSOR_ICONS: Record<PlannedSensor["type"], LucideIcon> = {
  gps_probe: Navigation,
  turnstile: Ticket,
  people_counter: Users,
  ramp_counter: Car,
};

/** Il simbolo di un sensore **previsto** (spech 11.5): grigio, con il **contorno tratteggiato**, per
 * non confonderlo con un dato attivo (i dati veri hanno colore e linea piena). Con `type` ha l'icona
 * del tipo; senza, è il solo campione della legenda. Colori solo dai token. */
export function SensorSymbol({ type }: { type?: PlannedSensor["type"] }) {
  return (
    <span
      aria-hidden
      data-sensor={type ?? "legend"}
      className={cn(
        "grid flex-none place-items-center rounded-full border-control border-dashed border-text-secondary bg-surface-1 text-text-secondary",
        type ? "size-6" : "size-space-16",
      )}
    >
      {type && <Icon icon={SENSOR_ICONS[type]} size="badge" />}
    </span>
  );
}

/** L'interruttore del livello «Sensori previsti», nella legenda (spento di default, 11.5). */
export interface SensorsToggle {
  on: boolean;
  onToggle: () => void;
}

/** La legenda: le quattro classi della congestione (se la mappa le mostra: scorrevole, rallentata,
 * intensa, satura) e, in LIVE, l'interruttore del livello «Sensori previsti». Se la mappa è stretta (a
 * 1366 px, con il run in corso e l'Event Manager compresso) le voci vanno a capo: non si tagliano. */
export function MapLegend({
  congestion = true,
  sensors,
}: {
  congestion?: boolean;
  sensors?: SensorsToggle;
}) {
  return (
    <div
      role="group"
      aria-label={congestion ? copy.legendLabel : strings.live.sensors.legendLabel}
      className="inline-flex max-w-full flex-wrap items-center gap-x-space-16 gap-y-space-8 rounded-card border-hairline border-border-card bg-surface-1 px-space-16 py-space-12"
    >
      {congestion &&
        copy.congestion.map((name, index) => (
          <span key={name} className="flex items-center gap-space-8 text-xs font-medium">
            <span className={cn("h-1.5 w-6 rounded-full", CONGESTION_SWATCH[index])} />
            {name}
          </span>
        ))}
      {sensors && (
        <button
          type="button"
          role="checkbox"
          aria-checked={sensors.on}
          onClick={sensors.onToggle}
          className={cn(
            "flex items-center gap-space-8 rounded-control text-xs font-medium text-text-primary",
            !sensors.on && "text-text-secondary",
          )}
        >
          <CheckBox on={sensors.on} />
          <SensorSymbol />
          {strings.live.sensors.layer}
        </button>
      )}
    </div>
  );
}

/** L'attribuzione, sempre visibile (ODbL): OpenStreetMap e Protomaps. */
export function MapAttribution() {
  return (
    <span className="inline-block rounded-control border-hairline border-border-tooltip bg-surface-1 px-2.5 py-1 text-xs font-medium text-text-secondary">
      <a
        href="https://www.openstreetmap.org/copyright"
        target="_blank"
        rel="noreferrer"
        className="hover:text-text-primary hover:underline"
      >
        {copy.attribution.osm}
      </a>
      {" · "}
      <a
        href="https://protomaps.com"
        target="_blank"
        rel="noreferrer"
        className="hover:text-text-primary hover:underline"
      >
        {copy.attribution.protomaps}
      </a>
    </span>
  );
}

const MARKER_BORDER: Record<MarkerState, string> = {
  normal: "border-action",
  accepted: "border-status-accepted",
  rejected: "border-status-rejected",
};
const MARKER_TAIL: Record<MarkerState, string> = {
  normal: "border-t-action",
  accepted: "border-t-status-accepted",
  rejected: "border-t-status-rejected",
};
const MARKER_BADGE: Record<MarkerState, string> = {
  normal: "",
  accepted: "bg-status-accepted",
  rejected: "bg-status-rejected",
};

/** Il marker di una richiesta: l'icona del dipartimento e, se accettata o rifiutata, il suo segno. */
export function MapMarker({ department, state }: { department: string; state: MarkerState }) {
  const info = DEPARTMENTS[department];
  return (
    <span className="relative inline-block h-[52px] w-size-marker" data-state={state}>
      <span
        className={cn(
          "absolute left-0 top-0 grid size-size-marker place-items-center rounded-full border-control bg-surface-1 text-text-primary",
          MARKER_BORDER[state],
        )}
      >
        {info && <Icon icon={info.icon} size="marker" />}
      </span>
      <span
        aria-hidden
        className={cn(
          "absolute left-[15px] top-[43px] h-0 w-0 border-x-[7px] border-t-8 border-x-transparent",
          MARKER_TAIL[state],
        )}
      />
      {state !== "normal" && (
        <span
          className={cn(
            "absolute -right-1.5 -top-1.5 grid size-size-marker-badge place-items-center rounded-full text-bg [box-shadow:0_0_0_2px_var(--color-bg)]",
            MARKER_BADGE[state],
          )}
        >
          <Icon icon={state === "accepted" ? Check : X} className="size-3 stroke-[3]" />
        </span>
      )}
    </span>
  );
}

/** Il disco del divieto al centro di una chiusura (map-style 2.2): 24 px, fondo `bg`, bordo 2 px e icona
 * `ban` di 16 px (tratto 2) nel colore delle chiusure. */
export function ClosureSymbol() {
  return (
    <span
      aria-hidden
      className="grid size-6 place-items-center rounded-full border-control border-map-closure bg-bg text-map-closure"
    >
      <Icon icon={Ban} size="inline" className="stroke-2" />
    </span>
  );
}

/** L'anello che segna un punto che l'interfaccia ha chiesto di mostrare (un'evidenza, una richiesta).
 * Pulsa, ma solo se il sistema non chiede di ridurre i movimenti. */
export function FocusMarker({ label }: { label?: string | null }) {
  return (
    <span
      role="img"
      aria-label={label ? `${copy.focusLabel}: ${label}` : copy.focusLabel}
      className="relative grid size-size-marker place-items-center"
    >
      <span
        aria-hidden
        className="absolute size-full rounded-full border-control border-action motion-safe:animate-ping"
      />
      <span aria-hidden className="size-4 rounded-full border-control border-bg bg-action" />
    </span>
  );
}
