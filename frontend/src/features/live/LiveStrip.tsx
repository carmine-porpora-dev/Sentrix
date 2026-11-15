import { MetricCard, type MetricCardState } from "@/components/MetricCard";
import { segmentOfSpeed, summaryValue } from "@/features/live/layers";
import { useLiveFlow } from "@/features/live/queries";
import { liveStatus } from "@/features/live/status";
import { strings } from "@/i18n/it";

const copy = strings.live.cards;

/** La fascia delle cinque card in LIVE (08 1, scelta del proprietario 12/11): numeri che esistono
 * davvero, calcolati dal backend dai tratti TomTom e dichiarati con la loro provenienza (media,
 * conteggi: STIMA; il tratto più lento: REALE). Niente ore-veicolo né affluenza: LIVE non ha flussi
 * né Evento. Senza dati («Non disponibile») le card non inventano nulla. */
export function LiveStrip() {
  const query = useLiveFlow(true);
  const flow = query.data;
  const status = liveStatus(query);
  const state: MetricCardState =
    status === "loading" ? "loading" : status === "none" ? "unavailable" : "ready";
  const slowest = summaryValue(flow, "slowest_speed");
  const slowestSegment = segmentOfSpeed(flow, slowest?.inputs[0]);
  const card = (part: string) => ({
    state,
    value: summaryValue(flow, part),
    better: "none" as const,
  });
  return (
    <>
      <MetricCard label={copy.meanSpeed} {...card("mean_speed")} />
      <MetricCard label={copy.meanRatio} {...card("mean_ratio")} />
      <MetricCard label={copy.slowed} {...card("slowed_count")} />
      <MetricCard label={copy.slowest} hint={slowestSegment?.label} {...card("slowest_speed")} />
      <MetricCard label={copy.covered} {...card("covered_count")} />
    </>
  );
}
