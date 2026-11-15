import { useDepartmentName } from "@/api/queries";
import type { Measured } from "@/api/types";
import { MeasuredValue } from "@/components/MeasuredValue";
import { StateChip } from "@/components/StateChip";
import { loadClass } from "@/features/map/layers";
import { requestStateLabel } from "@/lib/departments";
import { strings } from "@/i18n/it";

const copy = strings.map.popup;
const sensorCopy = strings.live.sensors;

export interface PopupTarget {
  /** Il livello dell'API da cui viene la feature. */
  layer: string;
  properties: Record<string, unknown>;
}

const text = (value: unknown): string => (typeof value === "string" ? value : "");

/** Il nome di una classe di linea (lo stesso della card del carico TPL); sconosciuta: il codice. */
const routeName = (routeClass: string): string =>
  (strings.metrics.transitClasses as Record<string, string>)[routeClass] ?? routeClass;

/** Un testo lungo con il suo titolo sopra (cosa misurerà un sensore, quale stima sostituirà). */
function Stacked({ name, children }: { name: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-text-secondary">{name}</span>
      <span>{children}</span>
    </div>
  );
}

function Row({ name, children }: { name: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[6.5rem_minmax(0,1fr)] gap-space-8">
      <span className="text-text-secondary">{name}</span>
      <span>{children}</span>
    </div>
  );
}

/** Che cosa dice un popup sulla mappa: il nome e lo stato della feature, **senza numeri propri**.
 * I singoli valori dei livelli (v/c di un arco, carico di una fermata) non hanno una provenienza
 * nell'API, quindi non si mostrano; dove c'è una metrica collegata (`evidence_id` degli incroci
 * critici) il numero è quello della metrica, con il suo tooltip. */
export function FeaturePopup({
  target,
  measured,
  lookup,
}: {
  target: PopupTarget;
  /** La metrica indicata da `evidence_id`, se l'interfaccia ce l'ha. */
  measured?: Measured;
  /** Una misura per id (i tratti LIVE hanno tre numeri: velocità, flusso libero e rapporto). */
  lookup?: (id: string) => Measured | undefined;
}) {
  const p = target.properties;
  const departmentName = useDepartmentName();
  switch (target.layer) {
    case "edges_vc": {
      const congestion = strings.map.congestion[Number(p.vc_class)] ?? "";
      if (p.live === true) {
        // un tratto LIVE: i numeri sono le velocità di TomTom, ognuna con la sua provenienza
        const title = text(p.name);
        const rows: [string, Measured | undefined][] = [
          [copy.currentSpeed, lookup?.(text(p.speed_id))],
          [copy.freeFlow, lookup?.(text(p.free_flow_id))],
          [copy.ratio, lookup?.(text(p.ratio_id))],
        ];
        return (
          <Body title={title}>
            <Row name={copy.congestion}>{congestion}</Row>
            {rows.map(
              ([name, value]) =>
                value && (
                  <Row key={name} name={name}>
                    <MeasuredValue measured={value} label={`${title}: ${name.toLowerCase()}`} />
                  </Row>
                ),
            )}
          </Body>
        );
      }
      return (
        <Body title={text(p.name) || text(p.edge_key)}>
          <Row name={copy.congestion}>{congestion}</Row>
          {p.detour === true && <Row name={copy.detour}>✓</Row>}
          {p.closed === true && <Row name={copy.closure}>✓</Row>}
        </Body>
      );
    }
    case "closures":
      return (
        <Body title={text(p.label)}>
          <Row name={copy.closure}>{text(p.mode)}</Row>
        </Body>
      );
    case "critical_intersections":
      return (
        <Body title={text(p.label)}>
          <Row name={copy.criticalIntersection(Number(p.rank))}> </Row>
          {measured && (
            <Row name={copy.saturation}>
              <MeasuredValue measured={measured} label={text(p.label)} />
            </Row>
          )}
        </Body>
      );
    case "stops": {
      const closed = p.closed === true;
      return (
        <Body title={text(p.name)}>
          {closed ? (
            <Row name={copy.closedStop}>✓</Row>
          ) : (
            // senza un rapporto (nessuna corsa nella fascia, o gli orari programmati di LIVE) non si
            // dice «carico basso»: non si sa
            typeof p.load_ratio === "number" && (
              <Row name={copy.load}>{strings.map.loadClasses[loadClass(p.load_ratio)]}</Row>
            )
          )}
        </Body>
      );
    }
    case "sections":
      return (
        <Body title={text(p.label)}>
          <Row name={copy.route}>{routeName(text(p.route_class))}</Row>
          {typeof p.load_ratio === "number" && (
            <Row name={copy.load}>{strings.map.loadClasses[loadClass(p.load_ratio)]}</Row>
          )}
        </Body>
      );
    case "requests": {
      return (
        <Body title={text(p.target_label)}>
          <Row name={copy.department}>{departmentName(text(p.department))}</Row>
          <Row name={copy.state}>{requestStateLabel(text(p.state))}</Row>
        </Body>
      );
    }
    case "sensors":
      // un sensore previsto (spech 11.5): nessun numero, solo che cosa sarà
      return (
        <Body title={text(p.name)}>
          <StateChip tone="neutral" label={sensorCopy.planned} />
          <Stacked name={sensorCopy.measures}>{text(p.measures)}</Stacked>
          <Stacked name={sensorCopy.replaces}>{text(p.replaces)}</Stacked>
        </Body>
      );
    case "event_area":
      return <Body title={text(p.label) || copy.eventArea} />;
    default:
      return <Body title={text(p.name) || text(p.label)} />;
  }
}

function Body({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <div className="flex min-w-48 max-w-72 flex-col gap-1.5 text-xs">
      <div className="text-md font-semibold">{title}</div>
      {children}
    </div>
  );
}
