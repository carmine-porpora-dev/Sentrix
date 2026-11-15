import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createElement } from "react";
import { describe, expect, it, vi } from "vitest";
import type { ApiClient } from "@/api/client";
import { ApiError } from "@/api/errors";
import { createMockClient } from "@/api/mock";
import { ApiProvider } from "@/api/provider";
import type { FeatureCollection, LayerName, MetricsResponse, RunView } from "@/api/types";
import { MapPanel } from "@/features/map/MapPanel";
import { AppShell } from "@/features/shell/AppShell";
import { ShellProvider, useShell, type EventWindow } from "@/features/shell/ShellProvider";
import { strings } from "@/i18n/it";
import { fixture } from "@/test/fixtures";

// Qui la mappa finta ha in più un pulsante per far arrivare un errore, come la base map che non si carica.
vi.mock("@/features/map/MapCanvas", () => ({
  MapCanvas: (props: {
    data: Record<string, unknown>;
    visible: ReadonlySet<string>;
    presentation: boolean;
    window: string;
    fitKey: string | undefined;
    tilesUrl: string;
    measuredFor: (id: string) => { value: unknown } | undefined;
    sensors?: readonly { key: string; sensor: { type: string } }[];
    onError?: (message: string) => void;
  }) =>
    createElement(
      "div",
      {
        "data-testid": "map-canvas",
        "data-layers": Object.keys(props.data).sort().join(","),
        "data-visible": [...props.visible].sort().join(","),
        "data-presentation": String(props.presentation),
        "data-window": props.window,
        "data-fit-key": props.fitKey ?? "",
        "data-tiles": props.tilesUrl,
        "data-sensors": String(props.sensors?.length ?? 0),
        "data-sensor-types": [...new Set((props.sensors ?? []).map((m) => m.sensor.type))]
          .sort()
          .join(","),
        "data-edges": String(
          (props.data.edges_vc as FeatureCollection | undefined)?.features.length ?? 0,
        ),
        "data-measure": String(
          props.measuredFor("m.run_mock_match_2027.it2.road.departure.critical_intersection.1.vc")
            ?.value ?? "",
        ),
      },
      createElement("button", { onClick: () => props.onError?.("base map rotta") }, "errore"),
    ),
}));

const RUN = "run_mock_match_2027";
const done = fixture<RunView>("run_view/step_13_done.json");
const copy = strings.map;

interface Options {
  iteration?: number;
  /** Le iterazioni di cui ci sono metriche e livelli. */
  available?: number[];
  state?: RunView["run"]["state"];
}

function mapClient({ iteration = 2, available = [0, 1, 2], state = "DONE" }: Options = {}) {
  const view: RunView = { ...done, run: { ...done.run, iteration, state } };
  const runLayer = vi.fn((_run: string, layer: LayerName, n: number) =>
    available.includes(n)
      ? Promise.resolve(fixture<FeatureCollection>(`run_layers/${layer}_it${n}.json`))
      : Promise.reject(new ApiError(404, { code: "NOT_FOUND", message: "non ancora" })),
  );
  const client: ApiClient = {
    ...createMockClient({ authenticated: true }),
    getRun: () => Promise.resolve(view),
    runMetrics: (_id: string, n: number) =>
      available.includes(n)
        ? Promise.resolve(fixture<MetricsResponse>(`run_metrics/iteration_${n}.json`))
        : Promise.reject(new ApiError(404, { code: "NOT_FOUND", message: "non ancora" })),
    runLayer,
  };
  return { client, runLayer };
}

function renderMap(
  client: ApiClient,
  initial: { runId?: string; window?: EventWindow; mode?: "scenario" | "live" } = { runId: RUN },
) {
  return render(
    <ApiProvider client={client}>
      <ShellProvider initial={initial}>
        <MapPanel />
      </ShellProvider>
    </ApiProvider>,
  );
}

const canvas = () => screen.findByTestId("map-canvas");
const layersOf = async () => (await canvas()).dataset.layers?.split(",").filter(Boolean) ?? [];

async function loaded() {
  await waitFor(async () => expect(await layersOf()).toHaveLength(7));
}

describe("MapPanel: senza run", () => {
  it("c'è la mappa di base con il selettore della finestra e l'attribuzione, nessun dato", async () => {
    renderMap(mapClient().client, {});
    const map = await canvas();
    expect(map.dataset.layers).toBe("");
    expect(map.dataset.window).toBe("departure");
    expect(map.dataset.fitKey).toBe("");
    expect(
      screen.getByRole("radiogroup", { name: strings.metrics.windowLabel }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: copy.attribution.osm })).toBeInTheDocument();
    // niente legenda (non c'è congestione da leggere) né Prima/Dopo
    expect(screen.queryByRole("group", { name: copy.legendLabel })).not.toBeInTheDocument();
    expect(screen.queryByRole("switch", { name: copy.beforeAfter })).not.toBeInTheDocument();
  });

  it("dà alla mappa il file delle tessere del client", async () => {
    const { client } = mapClient();
    renderMap(client, {});
    expect((await canvas()).dataset.tiles).toBe(client.tilesUrl);
    expect(client.tilesUrl).toMatch(/napoli\.pmtiles$/);
  });
});

describe("MapPanel: con un run finito (iterazione 2)", () => {
  it("legge i sette livelli dell'iterazione più recente e li mostra tutti, accesi", async () => {
    const { client, runLayer } = mapClient();
    renderMap(client);
    await loaded();
    expect(await layersOf()).toEqual([
      "closures",
      "critical_intersections",
      "edges_vc",
      "event_area",
      "requests",
      "sections",
      "stops",
    ]);
    expect((await canvas()).dataset.visible).toBe(
      "closures,congestion,detours,event_area,intersections,requests,sections,stops",
    );
    for (const call of runLayer.mock.calls) expect(call[2]).toBe(2);
    expect(runLayer).toHaveBeenCalledTimes(7);
  });

  it("porta la mappa sull'area dell'evento, una volta per run", async () => {
    renderMap(mapClient().client);
    await waitFor(async () => expect((await canvas()).dataset.fitKey).toBe(RUN));
  });

  it("la legenda della congestione c'è, e se ne va con il livello spento", async () => {
    renderMap(mapClient().client);
    await loaded();
    expect(screen.getByRole("group", { name: copy.legendLabel })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: copy.layersButton }));
    const panel = screen.getByRole("group", { name: copy.layersTitle });
    fireEvent.click(within(panel).getByRole("checkbox", { name: copy.layers.congestion }));
    expect(screen.queryByRole("group", { name: copy.legendLabel })).not.toBeInTheDocument();
    expect((await canvas()).dataset.visible).not.toContain("congestion");
    expect((await canvas()).dataset.visible).toContain("detours");

    fireEvent.click(within(panel).getByRole("checkbox", { name: copy.layers.congestion }));
    expect(screen.getByRole("group", { name: copy.legendLabel })).toBeInTheDocument();
  });

  it("il pannello dei livelli ha gli otto livelli, tutti accesi, e si chiude", async () => {
    renderMap(mapClient().client);
    await loaded();
    const button = screen.getByRole("button", { name: copy.layersButton });
    expect(screen.queryByRole("group", { name: copy.layersTitle })).not.toBeInTheDocument();
    fireEvent.click(button);
    const panel = screen.getByRole("group", { name: copy.layersTitle });
    const boxes = within(panel).getAllByRole("checkbox");
    expect(boxes.map((b) => b.textContent)).toEqual([
      ...Object.values(copy.layers),
      copy.presentation,
    ]);
    for (const box of boxes.slice(0, 8)) expect(box).toHaveAttribute("aria-checked", "true");
    expect(boxes[8]).toHaveAttribute("aria-checked", "false");
    fireEvent.click(button);
    expect(screen.queryByRole("group", { name: copy.layersTitle })).not.toBeInTheDocument();
  });

  it("ogni livello si accende e si spegne da solo", async () => {
    renderMap(mapClient().client);
    await loaded();
    fireEvent.click(screen.getByRole("button", { name: copy.layersButton }));
    const panel = screen.getByRole("group", { name: copy.layersTitle });
    for (const [id, name] of Object.entries(copy.layers)) {
      fireEvent.click(within(panel).getByRole("checkbox", { name }));
      const visible = (await canvas()).dataset.visible?.split(",") ?? [];
      expect(visible, id).not.toContain(id);
      expect(visible, id).toHaveLength(7);
      fireEvent.click(within(panel).getByRole("checkbox", { name }));
      expect((await canvas()).dataset.visible?.split(","), id).toContain(id);
    }
  });

  it("la vista presentazione inclina la mappa", async () => {
    renderMap(mapClient().client);
    await loaded();
    expect((await canvas()).dataset.presentation).toBe("false");
    fireEvent.click(screen.getByRole("button", { name: copy.layersButton }));
    const box = screen.getByRole("checkbox", { name: copy.presentation });
    fireEvent.click(box);
    expect(box).toHaveAttribute("aria-checked", "true");
    expect((await canvas()).dataset.presentation).toBe("true");
    fireEvent.click(box);
    expect((await canvas()).dataset.presentation).toBe("false");
  });

  it("Arrivo | Deflusso passa la finestra alla mappa (che filtra gli archi)", async () => {
    renderMap(mapClient().client);
    await loaded();
    expect((await canvas()).dataset.window).toBe("departure");
    fireEvent.click(screen.getByRole("radio", { name: "Arrivo" }));
    expect((await canvas()).dataset.window).toBe("arrival");
  });

  it("gli archi non cambiano cambiando finestra (il filtro è nello stile, non nei dati)", async () => {
    const { client, runLayer } = mapClient();
    renderMap(client);
    await loaded();
    const before = (await canvas()).dataset.edges;
    expect(before).toBe("12");
    fireEvent.click(screen.getByRole("radio", { name: "Arrivo" }));
    expect((await canvas()).dataset.edges).toBe(before);
    expect(runLayer).toHaveBeenCalledTimes(7);
  });

  it("il numero di un incrocio critico, se la mappa lo chiede, viene dalle metriche del run", async () => {
    renderMap(mapClient().client);
    await loaded();
    await waitFor(async () => expect((await canvas()).dataset.measure).not.toBe(""));
    expect((await canvas()).dataset.measure).toBe(
      String(
        fixture<MetricsResponse>("run_metrics/iteration_2.json").metrics.find((m) =>
          m.id.endsWith("road.departure.critical_intersection.1.vc"),
        )?.value,
      ),
    );
  });
});

describe("MapPanel: le fasce dei controlli", () => {
  it("non catturano i clic sulla mappa: solo i controlli lo fanno", async () => {
    renderMap(mapClient().client);
    await loaded();
    for (const control of [
      screen.getByRole("radiogroup", { name: strings.metrics.windowLabel }),
      screen.getByRole("button", { name: copy.layersButton }),
      screen.getByRole("group", { name: copy.legendLabel }),
      screen.getByRole("link", { name: copy.attribution.osm }),
    ]) {
      expect(
        control.closest(".pointer-events-auto"),
        control.outerHTML.slice(0, 60),
      ).not.toBeNull();
      expect(control.closest(".pointer-events-none")).not.toBeNull();
    }
  });
});

describe("MapPanel: Prima / Dopo", () => {
  it("«Dopo» è l'iterazione 2 e «Prima» la 0: cambiano i livelli letti", async () => {
    const { client, runLayer } = mapClient();
    renderMap(client);
    await loaded();
    expect(screen.getByText(copy.iteration(3))).toBeInTheDocument(); // l'indice 2 è la terza passata
    expect(screen.getByRole("switch", { name: copy.beforeAfter })).toHaveAttribute(
      "aria-checked",
      "true",
    );

    fireEvent.click(screen.getByRole("button", { name: copy.before }));
    await waitFor(() => expect(runLayer).toHaveBeenCalledWith(RUN, "edges_vc", 0));
    await loaded();
    expect(screen.getByRole("switch", { name: copy.beforeAfter })).toHaveAttribute(
      "aria-checked",
      "false",
    );
    expect(screen.getByRole("button", { name: copy.nextIteration })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: copy.after }));
    expect(screen.getByRole("switch", { name: copy.beforeAfter })).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });

  it("le frecce scelgono l'iterazione «dopo» e leggono i suoi livelli", async () => {
    const { client, runLayer } = mapClient();
    renderMap(client);
    await loaded();
    fireEvent.click(screen.getByRole("button", { name: copy.previousIteration }));
    expect(screen.getByText(copy.iteration(2))).toBeInTheDocument(); // indice 1 = seconda passata
    await waitFor(() => expect(runLayer).toHaveBeenCalledWith(RUN, "stops", 1));
    fireEvent.click(screen.getByRole("button", { name: copy.nextIteration }));
    expect(screen.getByText(copy.iteration(3))).toBeInTheDocument();
  });

  it("con la sola iterazione 0 non c'è Prima/Dopo: c'è solo la 0", async () => {
    const { client, runLayer } = mapClient({ iteration: 0, available: [0], state: "RECONCILE" });
    renderMap(client);
    await loaded();
    expect(screen.queryByRole("switch", { name: copy.beforeAfter })).not.toBeInTheDocument();
    for (const call of runLayer.mock.calls) expect(call[2]).toBe(0);
  });

  it("con l'iterazione 1 non ancora prodotta mostra la 0 e non il vuoto", async () => {
    const { client } = mapClient({ iteration: 1, available: [0], state: "REPLAN" });
    renderMap(client);
    await loaded();
    expect(screen.queryByRole("switch", { name: copy.beforeAfter })).not.toBeInTheDocument();
  });
});

describe("MapPanel: la numerazione delle iterazioni", () => {
  it("la barra in alto e il selettore della mappa dicono lo stesso numero per la stessa iterazione", async () => {
    const { client } = mapClient();
    render(
      <ApiProvider client={client}>
        <ShellProvider initial={{ runId: RUN }}>
          <AppShell />
        </ShellProvider>
      </ApiProvider>,
    );
    await screen.findByText(copy.iteration(3));
    expect(screen.getByText(/Iterazione 3 di 3/)).toBeInTheDocument();
    // un solo numero per la terza passata (indice 2 dell'API): mai «Iterazione 2» accanto a «3 di 3»
    expect(screen.queryByText(copy.iteration(2))).not.toBeInTheDocument();
  });
});

describe("MapPanel: LIVE", () => {
  it("mostra i tratti TomTom, le linee e le fermate: non i livelli, i selettori dell'analisi", async () => {
    const { client, runLayer } = mapClient();
    const runMetrics = vi.spyOn(client, "runMetrics");
    renderMap(client, { runId: RUN, mode: "live" });
    // il run e le sue metriche arrivano comunque: è dopo che la mappa leggerebbe i livelli
    await waitFor(() => expect(runMetrics).toHaveBeenCalledTimes(3));
    const map = await canvas();
    // i tratti (livello di congestione), le linee e le fermate del TPL; nessun livello del run
    await waitFor(() => expect(map.dataset.layers).toBe("edges_vc,sections,stops"));
    expect(runLayer).not.toHaveBeenCalled();
    expect(
      screen.queryByRole("radiogroup", { name: strings.metrics.windowLabel }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: copy.layersButton })).not.toBeInTheDocument();
    // la legenda è quella delle quattro classi, la stessa dello scenario
    expect(screen.getByRole("group", { name: copy.legendLabel })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: copy.attribution.protomaps })).toBeInTheDocument();
  });
});

// «Sensori previsti» (spech 11.5): in LIVE, un livello della legenda, spento di default.
describe("MapPanel: sensori previsti in LIVE", () => {
  const sensorsLabel = { name: strings.live.sensors.layer };
  // 6 contapersone + 4 sensori di rampa + i tornelli sulle stazioni delle due linee del mock (2 + 2)
  const ALL_SYMBOLS = 14;

  function SwitchMode() {
    const shell = useShell();
    return (
      <button onClick={() => shell.setMode(shell.mode === "live" ? "scenario" : "live")}>
        cambia modalità
      </button>
    );
  }

  function liveMap(client: ApiClient, mode: "live" | "scenario" = "live") {
    return render(
      <ApiProvider client={client}>
        <ShellProvider initial={{ mode }}>
          <SwitchMode />
          <MapPanel />
        </ShellProvider>
      </ApiProvider>,
    );
  }

  const sensorsClient = (live: "fresh" | "unavailable" = "fresh") =>
    createMockClient({ authenticated: true, liveMode: live });
  const toggle = () => screen.findByRole("checkbox", sensorsLabel);

  it("la legenda ha l'interruttore «Sensori previsti», spento di default: nessun simbolo", async () => {
    liveMap(sensorsClient());
    const box = await toggle();
    expect(box).toHaveAttribute("aria-checked", "false");
    // sta nella legenda, accanto alle quattro classi della congestione
    const legend = screen.getByRole("group", { name: copy.legendLabel });
    expect(within(legend).getByRole("checkbox", sensorsLabel)).toBe(box);
    expect(within(legend).getByText("Scorrevole")).toBeInTheDocument();
    expect((await canvas()).dataset.sensors).toBe("0");
  });

  it("acceso, la mappa riceve i simboli: contapersone, rampe e tornelli (sulle stazioni delle linee)", async () => {
    liveMap(sensorsClient());
    fireEvent.click(await toggle());
    await waitFor(async () => expect((await canvas()).dataset.sensors).toBe(String(ALL_SYMBOLS)));
    expect(screen.getByRole("checkbox", sensorsLabel)).toHaveAttribute("aria-checked", "true");
    // le sonde GPS non hanno un posto: non si disegnano
    expect((await canvas()).dataset.sensorTypes).toBe("people_counter,ramp_counter,turnstile");
  });

  it("si spegne con un secondo clic", async () => {
    liveMap(sensorsClient());
    fireEvent.click(await toggle());
    await waitFor(async () => expect((await canvas()).dataset.sensors).not.toBe("0"));
    fireEvent.click(screen.getByRole("checkbox", sensorsLabel));
    await waitFor(async () => expect((await canvas()).dataset.sensors).toBe("0"));
  });

  it("uscendo da LIVE si spegne: la visita dopo riparte spenta", async () => {
    liveMap(sensorsClient());
    fireEvent.click(await toggle());
    await waitFor(async () => expect((await canvas()).dataset.sensors).not.toBe("0"));
    fireEvent.click(screen.getByRole("button", { name: "cambia modalità" })); // → SCENARIO
    expect(screen.queryByRole("checkbox", sensorsLabel)).not.toBeInTheDocument();
    expect((await canvas()).dataset.sensors).toBe("0");
    fireEvent.click(screen.getByRole("button", { name: "cambia modalità" })); // → LIVE
    expect(await toggle()).toHaveAttribute("aria-checked", "false");
    expect((await canvas()).dataset.sensors).toBe("0");
  });

  it("senza dati TomTom la legenda ha solo l'interruttore (e si chiama come la mappa, non come la congestione)", async () => {
    liveMap(sensorsClient("unavailable"));
    const box = await toggle();
    expect(screen.queryByRole("group", { name: copy.legendLabel })).not.toBeInTheDocument();
    const legend = screen.getByRole("group", { name: strings.live.sensors.legendLabel });
    expect(within(legend).getByRole("checkbox", sensorsLabel)).toBe(box);
    expect(within(legend).queryByText("Scorrevole")).not.toBeInTheDocument();
  });

  it("in SCENARIO non c'è l'interruttore e non si chiede l'elenco dei sensori", async () => {
    const client = sensorsClient();
    const listSensors = vi.spyOn(client, "listSensors");
    liveMap(client, "scenario");
    await canvas();
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(screen.queryByRole("checkbox", sensorsLabel)).not.toBeInTheDocument();
    expect(listSensors).not.toHaveBeenCalled();
  });

  it("se l'elenco non si legge (503) non c'è l'interruttore e LIVE resta com'era", async () => {
    const client = sensorsClient();
    client.listSensors = () =>
      Promise.reject(new ApiError(503, { code: "DATA_UNAVAILABLE", message: "non disponibile" }));
    liveMap(client);
    const map = await canvas();
    await waitFor(() => expect(map.dataset.layers).toBe("edges_vc,sections,stops"));
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(screen.queryByRole("checkbox", sensorsLabel)).not.toBeInTheDocument();
    expect(screen.getByRole("group", { name: copy.legendLabel })).toBeInTheDocument(); // la congestione c'è
    expect(map.dataset.sensors).toBe("0");
  });

  it("l'interruttore non toglie nulla ai livelli di LIVE (tratti, linee, fermate)", async () => {
    liveMap(sensorsClient());
    fireEvent.click(await toggle());
    const map = await canvas();
    await waitFor(() => expect(map.dataset.layers).toBe("edges_vc,sections,stops"));
  });
});

describe("MapPanel: guasti", () => {
  it("se la base map non si carica, i controlli dell'analisi spariscono e l'attribuzione resta", async () => {
    renderMap(mapClient().client);
    await loaded();
    expect(screen.getByRole("button", { name: copy.layersButton })).toBeInTheDocument();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "errore" }));
    });
    expect(screen.queryByRole("button", { name: copy.layersButton })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("radiogroup", { name: strings.metrics.windowLabel }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("group", { name: copy.legendLabel })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: copy.attribution.osm })).toBeInTheDocument();
  });

  it("un livello che il server non ha ancora (404) manca e gli altri si vedono", async () => {
    const { client } = mapClient();
    const failing: ApiClient = {
      ...client,
      runLayer: (id, layer, n) =>
        layer === "sections"
          ? Promise.reject(new ApiError(404, { code: "NOT_FOUND", message: "non ancora" }))
          : client.runLayer(id, layer, n),
    };
    renderMap(failing);
    await waitFor(async () => expect(await layersOf()).toHaveLength(6));
    expect(await layersOf()).not.toContain("sections");
  });
});
