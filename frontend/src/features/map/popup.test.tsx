import { render as renderPlain, screen } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { describe, expect, it } from "vitest";
import { createMockClient } from "@/api/mock";
import { ApiProvider } from "@/api/provider";
import type { FeatureCollection, LiveFlowResponse, PlannedSensor } from "@/api/types";
import { liveEdges, liveMeasures } from "@/features/live/layers";
import { FeaturePopup } from "@/features/map/popup";
import { strings } from "@/i18n/it";
import { fixture } from "@/test/fixtures";
import { measured } from "@/test/measured";

const copy = strings.map.popup;

// il popup di una richiesta legge il nome del dipartimento dal registro dell'API
const client = createMockClient({ authenticated: true });
const Wrapper = ({ children }: { children: ReactNode }) => (
  <ApiProvider client={client}>{children}</ApiProvider>
);
const render = (ui: ReactElement) => renderPlain(ui, { wrapper: Wrapper });
const props = (file: string, index = 0) =>
  (fixture<FeatureCollection>(`run_layers/${file}`).features[index]?.properties ?? {}) as Record<
    string,
    unknown
  >;

/** Un popup mostra nomi e classi: nessun numero che non sia una metrica con la sua provenienza. */
describe("FeaturePopup", () => {
  it("arco: nome e classe di congestione, deviazione se lo è; il v/c non c'è", () => {
    const edge = props("edges_vc_it2.json");
    const { container } = render(<FeaturePopup target={{ layer: "edges_vc", properties: edge }} />);
    expect(screen.getByText("Riviera di Chiaia")).toBeInTheDocument();
    expect(screen.getByText(copy.congestion)).toBeInTheDocument();
    expect(screen.getByText("Intensa")).toBeInTheDocument(); // vc_class 2
    expect(screen.getByText(copy.detour)).toBeInTheDocument();
    expect(screen.queryByText(copy.closure)).not.toBeInTheDocument();
    expect(container.textContent).not.toMatch(/0[.,]93/);
    expect(container.textContent).not.toMatch(/440/);
  });

  it("arco senza nome: la chiave dell'arco", () => {
    render(
      <FeaturePopup
        target={{ layer: "edges_vc", properties: { edge_key: "1-2-0", vc_class: 0, closed: true } }}
      />,
    );
    expect(screen.getByText("1-2-0")).toBeInTheDocument();
    expect(screen.getByText("Scorrevole")).toBeInTheDocument();
    expect(screen.getByText(copy.closure)).toBeInTheDocument();
    expect(screen.queryByText(copy.detour)).not.toBeInTheDocument();
  });

  it("chiusura: etichetta e modo", () => {
    render(<FeaturePopup target={{ layer: "closures", properties: props("closures_it2.json") }} />);
    expect(screen.getByText("Viale Anton Dohrn")).toBeInTheDocument();
    expect(screen.getByText("closed")).toBeInTheDocument();
  });

  it("incrocio critico: il rango e, se la metrica c'è, il suo valore con la provenienza", () => {
    const point = props("critical_intersections_it2.json");
    const { rerender } = render(
      <FeaturePopup target={{ layer: "critical_intersections", properties: point }} />,
    );
    expect(screen.getByText("Piazza Vittoria")).toBeInTheDocument();
    expect(screen.getByText(copy.criticalIntersection(1))).toBeInTheDocument();
    // senza metrica collegata, nessun numero
    expect(screen.queryByText(copy.saturation)).not.toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/1[.,]01/);

    rerender(
      <FeaturePopup
        target={{ layer: "critical_intersections", properties: point }}
        measured={measured({ value: 1.01, unit: "rapporto", kind: "simulated" })}
      />,
    );
    expect(screen.getByText(copy.saturation)).toBeInTheDocument();
    // un rapporto si mostra in percentuale (formato di F4-04), con il tooltip di provenienza
    expect(screen.getByText("101")).toBeInTheDocument();
    expect(screen.getByText("%")).toBeInTheDocument();
    expect(screen.getByText("101").closest("[tabindex]")).not.toBeNull();
  });

  it("un tratto LIVE: nome, classe e le tre velocità di TomTom, ognuna con la sua provenienza", () => {
    const flow = fixture<LiveFlowResponse>("live_flow_fresh.json");
    const segment = flow.segments[0];
    const found = liveMeasures(flow);
    const feature = liveEdges(flow)?.features[0];
    const { container } = render(
      <FeaturePopup
        target={{ layer: "edges_vc", properties: feature?.properties as Record<string, unknown> }}
        lookup={(id) => found.get(id)}
      />,
    );
    expect(screen.getByText(segment?.label ?? "")).toBeInTheDocument();
    expect(screen.getByText("Intensa")).toBeInTheDocument(); // classe 2, dall'API
    for (const name of [copy.currentSpeed, copy.freeFlow, copy.ratio]) {
      expect(screen.getByText(name)).toBeInTheDocument();
    }
    // velocità attuale e a flusso libero REALI, rapporto STIMA; ogni numero col suo tooltip
    const kinds = [...container.querySelectorAll("[data-measured]")].map((e) =>
      e.getAttribute("data-measured"),
    );
    expect(kinds).toEqual(["real", "real", "estimate"]);
    expect(container.textContent).toMatch(/15,0/);
  });

  it("un tratto LIVE senza una misura (non ancora arrivata) non scrive una riga vuota", () => {
    render(
      <FeaturePopup
        target={{
          layer: "edges_vc",
          properties: { live: true, name: "Via X", vc_class: 0, speed_id: "m.nessuna" },
        }}
        lookup={() => undefined}
      />,
    );
    expect(screen.getByText("Via X")).toBeInTheDocument();
    expect(screen.queryByText(copy.currentSpeed)).not.toBeInTheDocument();
  });

  it("senza un rapporto (nessuna corsa, o gli orari di LIVE) la fermata non dice «carico basso»", () => {
    render(
      <FeaturePopup
        target={{ layer: "stops", properties: { name: "Senza servizio", load_ratio: null } }}
      />,
    );
    expect(screen.getByText("Senza servizio")).toBeInTheDocument();
    expect(screen.queryByText(copy.load)).not.toBeInTheDocument();
    render(
      <FeaturePopup
        target={{
          layer: "sections",
          properties: { label: "Linea X", route_class: "metro_line_1" },
        }}
      />,
    );
    expect(screen.queryAllByText(copy.load)).toHaveLength(0);
  });

  it("fermata: nome e classe di carico a parole; quella chiusa lo dice", () => {
    const { rerender, container } = render(
      <FeaturePopup target={{ layer: "stops", properties: props("stops_it2.json") }} />,
    );
    expect(screen.getByText("Fermata di esempio 1")).toBeInTheDocument();
    expect(screen.getByText(strings.map.loadClasses.over)).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/5250|5000|1[.,]05/);

    rerender(
      <FeaturePopup
        target={{ layer: "stops", properties: { name: "Chiusa", closed: true, load_ratio: 0 } }}
      />,
    );
    expect(screen.getByText(copy.closedStop)).toBeInTheDocument();
    expect(screen.queryByText(copy.load)).not.toBeInTheDocument();
  });

  it("tratta TPL: etichetta, classe di linea e carico a parole", () => {
    const { container } = render(
      <FeaturePopup target={{ layer: "sections", properties: props("sections_it2.json") }} />,
    );
    expect(screen.getByText("Linea 1 (tratta di esempio)")).toBeInTheDocument();
    expect(screen.getByText("Linea 1")).toBeInTheDocument();
    expect(screen.getByText(strings.map.loadClasses.over)).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/5600|1[.,]12/);
  });

  it("tratta di una classe di linea nuova: il codice, non un vuoto", () => {
    render(
      <FeaturePopup
        target={{
          layer: "sections",
          properties: { label: "x", route_class: "tram_9", load_ratio: 0 },
        }}
      />,
    );
    expect(screen.getByText("tram_9")).toBeInTheDocument();
  });

  it("richiesta: il bersaglio è `target_label`, come lo scrive il backend (non `label`)", () => {
    render(
      <FeaturePopup
        target={{
          layer: "requests",
          properties: { label: "non è questo", target_label: "Via Depretis", state: "ACCEPTED" },
        }}
      />,
    );
    expect(screen.getByText("Via Depretis")).toBeInTheDocument();
    expect(screen.queryByText("non è questo")).not.toBeInTheDocument();
  });

  it("richiesta: etichetta, dipartimento (dal registro) e stato con i nomi per esteso", async () => {
    render(<FeaturePopup target={{ layer: "requests", properties: props("requests_it2.json") }} />);
    expect(screen.getByText("Incrocio Piazza Vittoria")).toBeInTheDocument();
    expect(await screen.findByText("Polizia Municipale (virtuale)")).toBeInTheDocument();
    expect(screen.getByText("In corso")).toBeInTheDocument();
  });

  it("richiesta con dipartimento o stato sconosciuti: il codice, non un vuoto", () => {
    render(
      <FeaturePopup
        target={{
          layer: "requests",
          properties: { target_label: "x", department: "nuovo", state: "BOH" },
        }}
      />,
    );
    expect(screen.getByText("nuovo")).toBeInTheDocument();
    expect(screen.getByText("BOH")).toBeInTheDocument();
  });

  it("area evento: l'etichetta, o il testo fisso", () => {
    const { rerender } = render(
      <FeaturePopup target={{ layer: "event_area", properties: { label: "Rotonda Diaz" } }} />,
    );
    expect(screen.getByText("Rotonda Diaz")).toBeInTheDocument();
    rerender(<FeaturePopup target={{ layer: "event_area", properties: {} }} />);
    expect(screen.getByText(copy.eventArea)).toBeInTheDocument();
  });

  it("un livello che non conosce: solo il nome, senza rompersi", () => {
    render(<FeaturePopup target={{ layer: "altro", properties: { name: "Qualcosa" } }} />);
    expect(screen.getByText("Qualcosa")).toBeInTheDocument();
  });
});

describe("FeaturePopup: sensore previsto (spech 11.5)", () => {
  const sensors = fixture<PlannedSensor[]>("sensors.json");
  const sensor = sensors.find((s) => s.type === "ramp_counter") as PlannedSensor;
  const target = { layer: "sensors", properties: { ...sensor } };

  it("nome, «Previsto — non attivo», cosa misurerà e quale stima sostituirà", () => {
    render(<FeaturePopup target={target} />);
    expect(screen.getByText(sensor.name)).toBeInTheDocument();
    expect(screen.getByText(strings.live.sensors.planned)).toBeInTheDocument();
    expect(screen.getByText(strings.live.sensors.measures)).toBeInTheDocument();
    expect(screen.getByText(sensor.measures)).toBeInTheDocument();
    expect(screen.getByText(strings.live.sensors.replaces)).toBeInTheDocument();
    expect(screen.getByText(sensor.replaces)).toBeInTheDocument();
  });

  it("nessun numero, nessun badge di provenienza: un sensore che non c'è non ha dati", () => {
    const { container } = render(<FeaturePopup target={target} />);
    expect(container.querySelector("[data-measured]")).toBeNull();
    expect(container.querySelector("[data-kind]")).toBeNull(); // né REALE, né STIMA, né SIMULATO
    expect(container.textContent).not.toMatch(/\d/);
  });

  it("lo stato è un'etichetta neutra, non il verde di una richiesta accettata", () => {
    const { container } = render(<FeaturePopup target={target} />);
    expect(container.querySelector("[data-tone='neutral']")).not.toBeNull();
    expect(container.querySelector("[data-tone='accepted']")).toBeNull();
  });

  it("ogni sensore del file ha un popup completo", () => {
    for (const each of sensors) {
      const { container, unmount } = render(
        <FeaturePopup target={{ layer: "sensors", properties: { ...each } }} />,
      );
      expect(container.textContent).toContain(each.name);
      expect(container.textContent).toContain(each.measures);
      expect(container.textContent).toContain(each.replaces);
      unmount();
    }
  });
});
