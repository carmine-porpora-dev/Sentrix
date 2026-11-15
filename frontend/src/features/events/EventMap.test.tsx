import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ApiClient } from "@/api/client";
import { createMockClient } from "@/api/mock";
import { ApiProvider } from "@/api/provider";
import type { Event, EventInput, EventSummary, FeatureCollection } from "@/api/types";
import { AppShell } from "@/features/shell/AppShell";
import { ShellProvider } from "@/features/shell/ShellProvider";
import { strings } from "@/i18n/it";
import { fixture } from "@/test/fixtures";

const copy = strings.events;
const match = fixture<Event>("event_match_2027.json");
const regate = fixture<Event>("event_regate_sep_2026.json");
const list = fixture<EventSummary[]>("events_list.json");
const preview = fixture<FeatureCollection>("event_resolve_preview.json");
const stopsFixture = fixture<FeatureCollection>("transit_stops.json");
const edgesFixture = fixture<FeatureCollection>("network_edges.json");

function makeClient(stops: FeatureCollection = stopsFixture) {
  const calls = {
    networkEdges: vi.fn((bbox: string) =>
      bbox ? Promise.resolve(edgesFixture) : Promise.reject(new Error("bbox")),
    ),
    transitStops: vi.fn((bbox: string) =>
      bbox ? Promise.resolve(stops) : Promise.reject(new Error("bbox")),
    ),
    resolveEvent: vi.fn((id: string) =>
      id ? Promise.resolve(preview) : Promise.reject(new Error("id")),
    ),
    updateEvent: vi.fn((_id: string, input: EventInput) =>
      Promise.resolve({
        ...input,
        revision: 2,
        created_at: match.created_at,
        updated_at: match.updated_at,
      } as Event),
    ),
  };
  const client: ApiClient = {
    ...createMockClient({ authenticated: true }),
    listEvents: () => Promise.resolve(list),
    getEvent: (id) => Promise.resolve(id === "regate_sep_2026" ? regate : match),
    ...calls,
  };
  return { client, ...calls };
}

/** Il guscio completo (Event Manager + mappa finta): si vede cosa riceve la mappa e si fanno i
 * clic che la mappa vera darebbe all'Event Manager. */
async function shell(
  initial: Parameters<typeof ShellProvider>[0]["initial"] = {},
  stops?: FeatureCollection,
) {
  const made = makeClient(stops);
  render(
    <ApiProvider client={made.client}>
      <ShellProvider initial={initial}>
        <AppShell />
      </ShellProvider>
    </ApiProvider>,
  );
  await waitFor(() =>
    expect(screen.getByRole("textbox", { name: copy.name })).toHaveValue(match.name),
  );
  return made;
}

const canvas = () => screen.getByTestId("map-canvas");
const field = (name: string | RegExp) => screen.getByRole("textbox", { name }) as HTMLInputElement;

describe("Event Manager e mappa: l'evento in modifica si vede sulla mappa", () => {
  it("senza un run la mappa mostra l'area, le chiusure e le fermate interrotte dell'evento", async () => {
    await shell();
    await waitFor(() => expect(canvas().dataset.layers).toBe("closures,event_area,stops"));
  });

  it("si porta sull'area dell'evento quando il form si riempie, e di nuovo cambiando evento", async () => {
    await shell();
    await waitFor(() => expect(canvas().dataset.fitKey).toMatch(/^edit:match_2027#/));
    const first = canvas().dataset.fitKey;
    const bounds = JSON.parse(canvas().dataset.fitTo as string) as [
      [number, number],
      [number, number],
    ];
    expect((bounds[0][0] + bounds[1][0]) / 2).toBeCloseTo(14.235, 3);

    // modificare il raggio non sposta la mappa (la chiave non cambia)
    fireEvent.change(field(copy.radius), { target: { value: "900" } });
    expect(canvas().dataset.fitKey).toBe(first);

    // (il raggio cambiato è una modifica non salvata: si scarta)
    vi.spyOn(window, "confirm").mockReturnValue(true);
    fireEvent.change(screen.getByRole("combobox", { name: copy.eventLabel }), {
      target: { value: "regate_sep_2026" },
    });
    await waitFor(() => expect(canvas().dataset.fitKey).toMatch(/^edit:regate_sep_2026#/));
  });

  it("l'area segue centro e raggio digitati, e sparisce se non si leggono", async () => {
    await shell();
    const before = canvas().dataset.fitTo;
    fireEvent.change(field(copy.radius), { target: { value: "900" } });
    expect(canvas().dataset.fitTo).not.toBe(before); // un cerchio più grande
    fireEvent.change(field(copy.lat), { target: { value: "nord" } });
    expect(canvas().dataset.layers).not.toContain("event_area");
    expect(canvas().dataset.fitKey).toBe(""); // senza area non c'è dove andare
    fireEvent.change(field(copy.lat), { target: { value: "40.832" } });
    expect(canvas().dataset.layers).toContain("event_area");
  });

  it("le chiusure disegnate sono quelle dell'evento; una strada scelta si aggiunge subito, prima di salvare", async () => {
    await shell();
    await waitFor(() => expect(canvas().dataset.closureLines).toBe("4")); // le 4 dell'anteprima
    fireEvent.click(screen.getByRole("button", { name: copy.pickStreets }));
    fireEvent.click(screen.getByRole("button", { name: "mock: clic su una strada" }));
    expect(canvas().dataset.closureLines).toBe("5");
    fireEvent.click(screen.getByRole("button", { name: "mock: clic su una strada" })); // la riapre
    expect(canvas().dataset.closureLines).toBe("4");
  });

  it("le fermate interrotte si disegnano come fermate chiuse, quando se ne conosce la posizione", async () => {
    const known: FeatureCollection = {
      type: "FeatureCollection",
      features: [6236, 6237, 1].map((id) => ({
        type: "Feature",
        geometry: { type: "Point", coordinates: [14.2, 40.8] },
        properties: { stop_id: String(id), name: `Fermata ${id}` },
      })),
    };
    await shell({}, known);
    await waitFor(() => expect(canvas().dataset.closedStops).toBe("2")); // 6236 e 6237, non la 1
    expect(canvas().dataset.disrupted).toBe("6236,6237");
  });

  it("in LIVE la mappa non ha l'Evento in modifica né le scelte", async () => {
    await shell({ mode: "live" });
    // solo i livelli di LIVE (tratti, linee, fermate): né quelli dell'Evento né le scelte
    await waitFor(() => expect(canvas().dataset.layers).toContain("edges_vc"));
    expect(canvas().dataset.layers).not.toMatch(/closures|event_area|requests/);
    expect(canvas().dataset.editorMode).toBe("");
  });

  it("con un run la mappa mostra i livelli del run, non l'evento in modifica", async () => {
    await shell({ runId: "run_mock_match_2027" });
    await waitFor(() => expect(canvas().dataset.editorMode).toBe("idle"));
    // i livelli del run (sette) o niente finché non arrivano: mai quelli dell'editor
    expect(canvas().dataset.fitKey).not.toMatch(/^edit:/);
  });
});

describe("Event Manager e mappa: scegliere sulla mappa", () => {
  it("la modalità del form arriva alla mappa", async () => {
    await shell();
    expect(canvas().dataset.editorMode).toBe("idle");
    fireEvent.click(screen.getByRole("button", { name: copy.pickStreets }));
    expect(canvas().dataset.editorMode).toBe("closures");
    fireEvent.click(screen.getByRole("button", { name: copy.pickingStreets }));
    expect(canvas().dataset.editorMode).toBe("idle");
    fireEvent.click(screen.getByRole("button", { name: copy.pickStops }));
    expect(canvas().dataset.editorMode).toBe("stops");
    fireEvent.click(screen.getByRole("button", { name: copy.pickCenter }));
    expect(canvas().dataset.editorMode).toBe("area");
  });

  it("un clic sul centro scrive le coordinate, svuota il luogo e spegne la modalità", async () => {
    await shell();
    fireEvent.click(screen.getByRole("button", { name: copy.pickCenter }));
    fireEvent.click(screen.getByRole("button", { name: "mock: clic sul centro" }));
    expect(field(copy.lat)).toHaveValue("40.80000");
    expect(field(copy.lon)).toHaveValue("14.20000");
    expect(field(copy.place)).toHaveValue("");
    expect(canvas().dataset.editorMode).toBe("idle");
    expect(screen.getByText(strings.events.unsaved)).toBeInTheDocument();
  });

  it("un clic su una strada aggiunge la chiusura, e sulla stessa la toglie", async () => {
    await shell();
    fireEvent.click(screen.getByRole("button", { name: copy.pickStreets }));
    expect(canvas().dataset.closed).toContain("18122092-8475097329-0");
    fireEvent.click(screen.getByRole("button", { name: "mock: clic su una strada" }));
    expect(screen.getByRole("textbox", { name: "Etichetta 3" })).toHaveValue("Via Nuova");
    expect(canvas().dataset.closed).toContain("1-2-0");
    expect(canvas().dataset.closed).toContain("2-1-0"); // la strada si chiude nei due sensi
    expect(canvas().dataset.layers).toContain("closures");
    // la stessa strada: si riapre in entrambi i sensi e la chiusura sparisce
    fireEvent.click(screen.getByRole("button", { name: "mock: clic su una strada" }));
    expect(screen.queryByRole("textbox", { name: "Etichetta 3" })).not.toBeInTheDocument();
    expect(canvas().dataset.closed).not.toContain("1-2-0");
    expect(canvas().dataset.closed).not.toContain("2-1-0");
    // la modalità resta accesa: si possono scegliere più strade
    expect(canvas().dataset.editorMode).toBe("closures");
  });

  it("un clic su una fermata aggiunge l'interruzione «<nome> chiusa» per entrambe le finestre", async () => {
    await shell();
    fireEvent.click(screen.getByRole("button", { name: copy.pickStops }));
    fireEvent.click(screen.getByRole("button", { name: "mock: clic su una fermata" }));
    expect(screen.getByRole("textbox", { name: "Etichetta Piazza Cavour" })).toHaveValue(
      "Piazza Cavour chiusa",
    );
    expect(screen.getByRole("combobox", { name: "Finestra Piazza Cavour" })).toHaveValue("both");
    expect(canvas().dataset.disrupted).toContain("77");
  });

  it("le scelte sulla mappa vanno nel corpo di Analizza", async () => {
    const made = await shell();
    fireEvent.click(screen.getByRole("button", { name: copy.pickStreets }));
    fireEvent.click(screen.getByRole("button", { name: "mock: clic su una strada" }));
    fireEvent.click(screen.getByRole("button", { name: copy.pickStops }));
    fireEvent.click(screen.getByRole("button", { name: "mock: clic su una fermata" }));
    fireEvent.click(screen.getByRole("button", { name: copy.analyze }));
    await waitFor(() => expect(made.updateEvent).toHaveBeenCalled());
    const body = made.updateEvent.mock.calls[0]?.[1] as EventInput;
    expect(body.closures?.at(-1)).toMatchObject({
      label: "Via Nuova",
      edge_keys: ["1-2-0", "2-1-0"],
      mode: "closed",
    });
    expect(body.transit_disruptions?.at(-1)).toMatchObject({
      stop_name: "Piazza Cavour",
      stop_ids: ["77"],
    });
  });
});

describe("Event Manager e mappa: strade e fermate dall'API", () => {
  it("l'anteprima del risolutore si chiede per l'evento salvato (e la sua revisione)", async () => {
    const made = await shell();
    await waitFor(() => expect(made.resolveEvent).toHaveBeenCalledWith("match_2027"));
    expect(made.resolveEvent).toHaveBeenCalledTimes(1);
  });

  it("le strade si chiedono solo scegliendo le strade, per il rettangolo attorno all'area", async () => {
    const made = await shell();
    expect(made.networkEdges).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: copy.pickStreets }));
    await waitFor(() => expect(made.networkEdges).toHaveBeenCalledTimes(1));
    const [w, s, e, n] = (made.networkEdges.mock.calls[0]?.[0] as string)
      .split(",")
      .map(Number) as [number, number, number, number];
    expect(w).toBeLessThan(14.235);
    expect(e).toBeGreaterThan(14.235);
    expect(s).toBeLessThan(40.832);
    expect(n).toBeGreaterThan(40.832);
    // il rettangolo è sulla griglia da 0,01°: spegnere e riaccendere non rifà la richiesta
    expect((w * 100) % 1).toBeCloseTo(0, 5);
    fireEvent.click(screen.getByRole("button", { name: copy.pickingStreets }));
    fireEvent.click(screen.getByRole("button", { name: copy.pickStreets }));
    expect(made.networkEdges).toHaveBeenCalledTimes(1);
  });

  it("le fermate si chiedono scegliendo le fermate, e anche per disegnare quelle interrotte", async () => {
    const made = await shell();
    // l'evento ha un'interruzione: serve la posizione della fermata per mostrarla
    await waitFor(() => expect(made.transitStops).toHaveBeenCalled());
    expect(made.networkEdges).not.toHaveBeenCalled();
  });

  it("un evento senza interruzioni non chiede le fermate finché non si scelgono", async () => {
    const made = makeClient();
    const client: ApiClient = {
      ...made.client,
      getEvent: () => Promise.resolve({ ...match, transit_disruptions: [] }),
    };
    render(
      <ApiProvider client={client}>
        <ShellProvider>
          <AppShell />
        </ShellProvider>
      </ApiProvider>,
    );
    await waitFor(() =>
      expect(screen.getByRole("textbox", { name: copy.name })).toHaveValue(match.name),
    );
    expect(made.transitStops).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: copy.pickStops }));
    await waitFor(() => expect(made.transitStops).toHaveBeenCalledTimes(1));
  });
});

describe("Event Manager nel guscio", () => {
  it("sta nella colonna a sinistra, con il titolo «Analisi evento», e Analizza è in basso", async () => {
    await shell();
    const panel = screen.getByRole("region", { name: strings.shell.eventManager.title });
    expect(within(panel).getByRole("button", { name: copy.analyze })).toBeInTheDocument();
    expect(within(panel).getByRole("combobox", { name: copy.eventLabel })).toBeInTheDocument();
  });

  it("avviato il run, l'Event Manager si comprime e la mappa segue il run", async () => {
    const made = makeClient();
    const client: ApiClient = {
      ...made.client,
      createRun: () => Promise.resolve({ run_id: "run_mock_match_2027" }),
    };
    render(
      <ApiProvider client={client}>
        <ShellProvider>
          <AppShell />
        </ShellProvider>
      </ApiProvider>,
    );
    await waitFor(() =>
      expect(screen.getByRole("textbox", { name: copy.name })).toHaveValue(match.name),
    );
    fireEvent.click(screen.getByRole("button", { name: copy.analyze }));
    await waitFor(() =>
      expect(document.querySelector("[data-layout]")).toHaveAttribute("data-layout", "rail"),
    );
    expect(screen.queryByRole("textbox", { name: copy.name })).not.toBeInTheDocument();
  });
});
