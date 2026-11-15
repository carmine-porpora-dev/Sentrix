import { Badge } from "@/components/Badge";
import { StateChip, type ChipTone } from "@/components/StateChip";
import { useLiveFlow, useSensors } from "@/features/live/queries";
import { sensorTypes } from "@/features/live/sensors";
import { liveStatus, type LiveStatus } from "@/features/live/status";
import { strings } from "@/i18n/it";

const copy = strings.live;

/** Come si dice lo stato di TomTom: «attivo» con i dati recenti, «ultimo dato disponibile» con lo
 * snapshot (08 4), «non disponibile» senza dati. Lo stesso `liveStatus` del chip della barra e del
 * pannello: la stessa parola in tutta l'interfaccia. */
const TOMTOM: Record<LiveStatus, { tone: ChipTone; label: string; real: boolean }> = {
  loading: { tone: "neutral", label: copy.sources.loading, real: false },
  ok: { tone: "accepted", label: copy.sources.tomtom.ok, real: true },
  partial: { tone: "pending", label: copy.sources.tomtom.partial, real: true },
  none: { tone: "rejected", label: copy.sources.tomtom.none, real: false },
};

/** Il riquadro «Fonti dati» della scheda Operations in LIVE (spech 11.5): da dove vengono i dati che si
 * vedono. TomTom è **attivo** (dato REALE); i sensori propri (sonde GPS, tornelli, contapersone,
 * sensori della Tangenziale) sono **previsti**: non producono dati, quindi non hanno badge né numeri.
 * Le righe dei sensori vengono dall'elenco dell'API: se non si legge, restano TomTom e una nota. */
export function DataSources() {
  const flow = useLiveFlow(true);
  const sensors = useSensors(true);
  const tomtom = TOMTOM[liveStatus(flow)];
  const types = sensorTypes(sensors.data);
  return (
    <section
      aria-labelledby="live-sources-title"
      className="m-space-16 flex flex-col gap-space-12 rounded-card bg-surface-2 p-space-12"
    >
      <h3 id="live-sources-title" className="text-md font-semibold text-text-primary">
        {copy.sources.title}
      </h3>
      <ul className="flex flex-col gap-space-8">
        <li
          data-source="tomtom"
          className="flex flex-wrap items-center justify-between gap-x-space-12 gap-y-space-8"
        >
          <span className="flex items-center gap-space-8 text-sm font-semibold text-text-primary">
            {copy.source}
            {tomtom.real && <Badge kind="real" />}
          </span>
          <StateChip tone={tomtom.tone} label={tomtom.label} />
        </li>
        {types.map((type) => (
          <li
            key={type}
            data-source={type}
            className="flex flex-wrap items-center justify-between gap-x-space-12 gap-y-space-8"
          >
            <span className="text-sm font-semibold text-text-primary">
              {copy.sensors.types[type]}
            </span>
            <StateChip tone="neutral" label={copy.sources.planned} />
          </li>
        ))}
      </ul>
      <p className="text-xs text-text-secondary">
        {sensors.isError ? copy.sources.sensorsUnavailable : copy.sources.hint}
      </p>
    </section>
  );
}
