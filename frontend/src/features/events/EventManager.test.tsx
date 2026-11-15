import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ApiClient } from "@/api/client";
import { ApiError } from "@/api/errors";
import { createMockClient } from "@/api/mock";
import { ApiProvider } from "@/api/provider";
import type { Event, EventInput, EventSummary, RunView } from "@/api/types";
import { draftFromEvent, renderedPaths } from "@/features/events/draft";
import { EventEditorProvider, useEventEditor } from "@/features/events/EventEditor";
import { fieldId } from "@/features/events/fields";
import { EventManager } from "@/features/events/EventManager";
import { ShellProvider, useShell } from "@/features/shell/ShellProvider";
import { strings } from "@/i18n/it";
import { fixture } from "@/test/fixtures";

const copy = strings.events;
const match = fixture<Event>("event_match_2027.json");
const regate = fixture<Event>("event_regate_sep_2026.json");
const list = fixture<EventSummary[]>("events_list.json");
const runDone = fixture<RunView>("run_view/step_13_done.json");
const runBusy = fixture<RunView>("run_view/step_02_analyze_traffic_transit.json");

const BY_ID: Record<string, Event> = { match_2027: match, regate_sep_2026: regate };

/** L'Evento come lo restituisce il server dopo un salvataggio: il contenuto più i suoi campi. */
const saved = (input: EventInput, revision = 2): Event => ({
  ...input,
  revision,
  created_at: match.created_at,
  updated_at: "2026-11-10T12:00:00+01:00",
});

function makeClient(overrides: Partial<ApiClient> = {}) {
  const calls = {
    getEvent: vi.fn((id: string) => Promise.resolve(BY_ID[id] as Event)),
    createEvent: vi.fn((input: EventInput) => Promise.resolve(saved(input, 1))),
    updateEvent: vi.fn((_id: string, input: EventInput) => Promise.resolve(saved(input))),
    resetEvent: vi.fn((id: string) => Promise.resolve({ ...(BY_ID[id] as Event), revision: 3 })),
    createRun: vi.fn((body: unknown) => Promise.resolve({ run_id: body ? "run_new" : "run_new" })),
  };
  const client: ApiClient = {
    ...createMockClient({ authenticated: true }),
    listEvents: () => Promise.resolve(list),
    ...calls,
    ...overrides,
  };
  return { client, ...calls };
}

function RunProbe() {
  const shell = useShell();
  return <output data-testid="followed-run">{shell.runId ?? "nessuno"}</output>;
}

function setup(client: ApiClient, initial: Parameters<typeof ShellProvider>[0]["initial"] = {}) {
  return render(
    <ApiProvider client={client}>
      <ShellProvider initial={initial}>
        <EventEditorProvider>
          <EventManager />
          <RunProbe />
        </EventEditorProvider>
      </ShellProvider>
    </ApiProvider>,
  );
}

const field = (name: string | RegExp) => screen.getByRole("textbox", { name }) as HTMLInputElement;
const type = (name: string | RegExp, value: string) =>
  fireEvent.change(field(name), { target: { value } });
/** Aspetta che il form mostri l'evento con questo nome (il selettore mostra il nome prima dei campi). */
const showing = (name: string) =>
  waitFor(() => expect(screen.getByRole("textbox", { name: copy.name })).toHaveValue(name));
const analyze = () =>
  screen.getByRole("button", { name: new RegExp(`^(${copy.analyze}|${copy.analyzing})`) });

/** Il form con il Match 2027 caricato. */
async function loaded(client = makeClient()) {
  setup(client.client);
  await showing(match.name);
  return client;
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Event Manager: caricamento", () => {
  it("parte dal primo evento dell'elenco e ne mostra i campi", async () => {
    const { getEvent } = await loaded();
    expect(getEvent).toHaveBeenCalledWith("match_2027");
    expect(field(copy.name)).toHaveValue(match.name);
    expect(screen.getByLabelText(copy.date)).toHaveValue("2027-07-10");
    expect(field("Inizio arrivo")).toHaveValue("16:00");
    expect(field("Fine arrivo")).toHaveValue("19:00");
    expect(field("Picco arrivo")).toHaveValue("18:00");
    expect(field("Picco deflusso")).toHaveValue("21:30");
    expect(field(copy.lat)).toHaveValue("40.832");
    expect(field(copy.lon)).toHaveValue("14.235");
    expect(field(copy.place)).toHaveValue("Rotonda Diaz");
    expect(field(copy.radius)).toHaveValue("400");
    expect(field(/Affluenza ipotizzata · medio/)).toHaveValue("150.000");
    expect(field(copy.attendanceSource)).toHaveValue(match.attendance.source_ref);
    expect(screen.getByRole("textbox", { name: copy.arrival })).toHaveValue("40"); // % di capacità
    expect(screen.getByRole("textbox", { name: copy.departure })).toHaveValue("25");
  });

  it("i tre livelli di affluenza si leggono; il medio è quello dell'analisi", async () => {
    await loaded();
    const group = screen.getByRole("radiogroup", { name: copy.levelLabel });
    const radios = within(group).getAllByRole("radio");
    expect(radios.map((r) => r.textContent)).toEqual([
      "Basso50.000",
      "Medio150.000",
      "Alto300.000",
    ]);
    expect(radios.map((r) => r.getAttribute("aria-checked"))).toEqual(["false", "true", "false"]);
    fireEvent.click(radios[2] as HTMLElement);
    expect(field(/Affluenza ipotizzata · alto/)).toHaveValue("300.000");
  });

  it("le chiusure e le interruzioni dell'evento sono righe, con gli archi e le fermate che coprono", async () => {
    await loaded();
    expect(screen.getByRole("textbox", { name: "Etichetta 1" })).toHaveValue(
      match.closures?.[0]?.label,
    );
    expect(screen.getByRole("textbox", { name: "Etichetta 2" })).toHaveValue("Viale Anton Dohrn");
    expect(screen.getAllByText("2 archi").length).toBe(1);
    expect(screen.getByText("4 archi")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Etichetta Arco Mirelli" })).toHaveValue(
      "Stazione Arco Mirelli chiusa per sicurezza",
    );
    expect(screen.getByText("2 fermate")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Finestra Arco Mirelli" })).toHaveValue("arrival");
  });

  it("un evento completo non dice che manca qualcosa", async () => {
    await loaded();
    expect(screen.queryByText(/Manc/)).not.toBeInTheDocument();
    expect(analyze()).toBeEnabled();
  });

  it("una chiusura a capacità ridotta si conserva e si dice, con la quota che resta", async () => {
    const reduced: Event = {
      ...match,
      closures: [
        {
          label: "Via Rallentata",
          street_names: ["Via Rallentata"],
          bbox: null,
          edge_keys: ["1-2-0"],
          mode: "capacity_reduction",
          capacity_factor: 0.4,
          source_ref: null,
        },
      ],
    };
    const made = makeClient({ getEvent: () => Promise.resolve(reduced) });
    setup(made.client);
    await showing(match.name);
    expect(screen.getByText(/Capacità ridotta al 40%/)).toBeInTheDocument();
    fireEvent.click(analyze());
    await waitFor(() => expect(made.createRun).toHaveBeenCalled()); // nessuna modifica: non si salva
    expect(made.updateEvent).not.toHaveBeenCalled();
  });

  it("ogni campo che il form mostra è tra quelli di cui sa leggere gli errori dell'API", async () => {
    const rich: Event = {
      ...match,
      real_measures: [{ label: "L", measure_type: "traffic_post", target: "t", source_ref: "s" }],
      sources: ["Fonte A", "Fonte B"],
    };
    const made = makeClient({ getEvent: () => Promise.resolve(rich) });
    const { container } = setup(made.client);
    await showing(match.name);
    const shown = new Set(
      Array.from(container.querySelectorAll<HTMLElement>("[id^='ev-']"), (el) => el.id).filter(
        (id) => id !== "ev-picker" && !id.endsWith("-msg"), // il picker e i messaggi dei campi
      ),
    );
    // per un evento esistente l'identificativo non si mostra: non si può cambiare
    const known = new Set([...renderedPaths(draftFromEvent(rich))].map(fieldId));
    known.delete(fieldId("id"));
    // dei tre livelli di affluenza c'è un campo solo (quello scelto, «medio»): gli errori degli altri
    // due si leggono come messaggio sotto i pulsanti (è un test a parte)
    known.delete(fieldId("attendance.low"));
    known.delete(fieldId("attendance.high"));
    expect([...shown].filter((id) => !known.has(id))).toEqual([]);
    expect([...known].filter((id) => !shown.has(id))).toEqual([]);
  });

  it("le risorse dei dipartimenti, nell'ordine dell'Evento, in una sezione chiusa", async () => {
    await loaded();
    const section = screen.getByRole("button", { name: copy.resources });
    expect(section).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByLabelText(/Pattuglie \(totali\) · deflusso/)).not.toBeVisible();
    fireEvent.click(section);
    expect(section).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByLabelText(/Pattuglie \(totali\) · deflusso/)).toBeVisible();
    expect(screen.getByLabelText(/Pattuglie \(totali\) · deflusso/)).toHaveValue(
      String(match.resources.find((r) => r.window === "departure")?.municipal_police_patrols_total),
    );
  });

  it("un errore nel leggere l'elenco o l'evento si dice, senza form a metà", async () => {
    const { client } = makeClient({
      listEvents: () => Promise.reject(new ApiError(500, { code: "INTERNAL", message: "x" })),
    });
    setup(client);
    expect(await screen.findByText(copy.eventsError)).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: copy.name })).not.toBeInTheDocument();
  });

  it("se l'evento non si legge lo dice, e Analizza resta spento", async () => {
    const { client } = makeClient({
      getEvent: () => Promise.reject(new ApiError(404, { code: "NOT_FOUND", message: "x" })),
    });
    setup(client);
    expect(await screen.findByText(copy.eventError)).toBeInTheDocument();
    expect(analyze()).toBeDisabled();
  });
});

describe("Event Manager: il selettore degli eventi", () => {
  it("elenca gli eventi dell'API e segna «preset» quello scelto se viene da un file seed", async () => {
    await loaded();
    const picker = screen.getByRole("combobox", { name: copy.eventLabel });
    expect(
      within(picker)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(list.map((e) => e.name));
    expect(picker).toHaveValue("match_2027");
    expect(screen.getByText(copy.presetChip)).toBeInTheDocument();
  });

  it("sceglierne un altro lo carica", async () => {
    const { getEvent } = await loaded();
    fireEvent.change(screen.getByRole("combobox", { name: copy.eventLabel }), {
      target: { value: "regate_sep_2026" },
    });
    await showing(regate.name);
    expect(getEvent).toHaveBeenCalledWith("regate_sep_2026");
    expect(field("Inizio arrivo")).toHaveValue(regate.arrival.start.slice(0, 5));
    expect(screen.getByLabelText(copy.date)).toHaveValue(regate.date);
  });

  it("con modifiche non salvate chiede se scartarle: «no» le tiene, «sì» cambia evento", async () => {
    await loaded();
    type(copy.name, "Un altro nome");
    expect(screen.getByText(copy.unsaved)).toBeInTheDocument();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const picker = screen.getByRole("combobox", { name: copy.eventLabel });
    fireEvent.change(picker, { target: { value: "regate_sep_2026" } });
    expect(confirm).toHaveBeenCalledWith(copy.discardConfirm);
    expect(field(copy.name)).toHaveValue("Un altro nome");
    expect(picker).toHaveValue("match_2027");

    confirm.mockReturnValue(true);
    fireEvent.change(picker, { target: { value: "regate_sep_2026" } });
    await showing(regate.name);
    expect(screen.queryByText(copy.unsaved)).not.toBeInTheDocument();
  });

  it("senza modifiche non chiede nulla", async () => {
    await loaded();
    const confirm = vi.spyOn(window, "confirm");
    fireEvent.change(screen.getByRole("combobox", { name: copy.eventLabel }), {
      target: { value: "regate_sep_2026" },
    });
    await showing(regate.name);
    expect(confirm).not.toHaveBeenCalled();
  });

  it("«Ripristina preset» è per i seed: riscrive il form con la nuova revisione", async () => {
    const { resetEvent } = await loaded();
    type(copy.name, "Cambiato");
    vi.spyOn(window, "confirm").mockReturnValue(true);
    fireEvent.click(screen.getByRole("button", { name: copy.resetPreset }));
    await waitFor(() => expect(resetEvent).toHaveBeenCalledWith("match_2027"));
    await waitFor(() => expect(field(copy.name)).toHaveValue(match.name));
    expect(screen.queryByText(copy.unsaved)).not.toBeInTheDocument();
  });

  it("«Ripristina preset» chiede conferma se si perde del lavoro, e «no» non chiama l'API", async () => {
    const { resetEvent } = await loaded();
    type(copy.name, "Cambiato");
    vi.spyOn(window, "confirm").mockReturnValue(false);
    fireEvent.click(screen.getByRole("button", { name: copy.resetPreset }));
    expect(resetEvent).not.toHaveBeenCalled();
    expect(field(copy.name)).toHaveValue("Cambiato");
  });

  it("un evento che non è un seed non si ripristina", async () => {
    const custom: EventSummary = {
      ...(list[0] as EventSummary),
      id: "mio",
      name: "Mio",
      is_seed: false,
    };
    const { client } = makeClient({
      listEvents: () => Promise.resolve([custom, ...list]),
      getEvent: (id) =>
        Promise.resolve(id === "mio" ? { ...match, id: "mio", name: "Mio" } : (BY_ID[id] as Event)),
    });
    setup(client);
    await showing("Mio");
    expect(screen.getByRole("button", { name: copy.resetPreset })).toBeDisabled();
    expect(screen.queryByText(copy.presetChip)).not.toBeInTheDocument();
  });
});

describe("Event Manager: evento nuovo", () => {
  async function newEvent() {
    const made = await loaded();
    fireEvent.click(screen.getByRole("button", { name: copy.newEvent }));
    await waitFor(() => expect(field(copy.name)).toHaveValue(""));
    return made;
  }

  it("parte vuoto, con il solo raggio che propone il modello, e non si può analizzare", async () => {
    await newEvent();
    expect(field(copy.radius)).toHaveValue("400");
    expect(field(copy.lat)).toHaveValue("");
    expect(analyze()).toBeDisabled();
    expect(screen.getByText(copy.missing(26))).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: copy.eventLabel })).toHaveValue("__new__");
  });

  it("l'identificativo si ricava dal nome finché non lo si scrive a mano", async () => {
    await newEvent();
    type(copy.name, "Serata di Prova 2027");
    expect(field(copy.id)).toHaveValue("serata_di_prova_2027");
    type(copy.id, "mio_id");
    type(copy.name, "Serata di Prova 2028");
    expect(field(copy.id)).toHaveValue("mio_id");
  });

  it("«Nuovo evento» di nuovo, con del lavoro nel form, riparte da vuoto (dopo la conferma)", async () => {
    await newEvent();
    type(copy.name, "Serata a metà");
    vi.spyOn(window, "confirm").mockReturnValue(true);
    fireEvent.click(screen.getByRole("button", { name: copy.newEvent }));
    await waitFor(() => expect(field(copy.name)).toHaveValue(""));
    expect(field(copy.id)).toHaveValue("");
  });

  it("l'identificativo non coincide con uno già preso", async () => {
    await newEvent();
    type(copy.name, "Match 2027 — serata di regata");
    expect(field(copy.id)).toHaveValue("match_2027_serata_di_regata");
    type(copy.name, "regate_sep_2026");
    expect(field(copy.id)).toHaveValue("regate_sep_2026_2");
  });

  it("un campo vuoto segnala «obbligatorio» solo dopo averlo toccato", async () => {
    await newEvent();
    expect(screen.queryByText(copy.problems.required)).not.toBeInTheDocument();
    fireEvent.blur(field(copy.name));
    const messages = screen.getAllByText(copy.problems.required);
    expect(messages).toHaveLength(1);
    expect(field(copy.name)).toHaveAttribute("aria-invalid", "true");
  });

  it("un valore che non si legge si segnala subito", async () => {
    await newEvent();
    type(/Affluenza ipotizzata · medio/, "tanta");
    expect(screen.getByText(copy.problems.integer)).toBeInTheDocument();
    type("Inizio arrivo", "7pm");
    expect(screen.getByText(copy.problems.time)).toBeInTheDocument();
  });

  it("compilato tutto si può analizzare: crea l'evento (POST) e avvia il run sul suo id", async () => {
    const made = await newEvent();
    type(copy.name, "Serata Nuova");
    fireEvent.change(screen.getByLabelText(copy.date), { target: { value: "2027-08-01" } });
    for (const [window, [a, b, c]] of [
      ["arrivo", ["16:00", "19:00", "18:00"]],
      ["deflusso", ["21:00", "23:00", "21:30"]],
    ] as const) {
      type(`Inizio ${window}`, a);
      type(`Fine ${window}`, b);
      type(`Picco ${window}`, c);
    }
    type(copy.lat, "40,83");
    type(copy.lon, "14.23");
    for (const level of ["basso", "medio", "alto"]) {
      fireEvent.click(screen.getByRole("radio", { name: new RegExp(`^${level}`, "i") }));
      type(
        new RegExp(`Affluenza ipotizzata · ${level}`),
        level === "basso" ? "1.000" : level === "medio" ? "2.000" : "3.000",
      );
    }
    type(copy.arrival, "30");
    type(copy.departure, "20");
    fireEvent.click(screen.getByRole("button", { name: copy.resources }));
    for (const input of screen.getAllByLabelText(
      /(Pattuglie|Modifiche semaforiche|Bus di riserva|Estensioni)/,
    )) {
      fireEvent.change(input, { target: { value: "2" } });
    }
    expect(analyze()).toBeEnabled();

    fireEvent.click(analyze());
    await waitFor(() => expect(made.createEvent).toHaveBeenCalledTimes(1));
    const sent = made.createEvent.mock.calls[0]?.[0] as EventInput;
    expect(sent.id).toBe("serata_nuova");
    expect(sent.name).toBe("Serata Nuova");
    expect(sent.area_center).toEqual({ lat: 40.83, lon: 14.23, label: null });
    expect(sent.attendance).toEqual({ low: 1000, mid: 2000, high: 3000, source_ref: null });
    expect(sent.background).toEqual({ arrival_peak_share: 0.3, departure_peak_share: 0.2 });
    expect(sent.arrival.start).toBe("16:00:00");
    expect(made.updateEvent).not.toHaveBeenCalled();
    await waitFor(() => expect(made.createRun).toHaveBeenCalledTimes(1));
    expect(made.createRun).toHaveBeenCalledWith({
      event_id: "serata_nuova",
      attendance_level: "high", // l'ultimo livello scelto
      manual_response: false,
    });
    expect(await screen.findByTestId("followed-run")).toHaveTextContent("run_new");
  });
});

describe("Event Manager: Analizza", () => {
  it("su un evento non modificato non lo salva: avvia solo il run, con il livello scelto", async () => {
    const made = await loaded();
    fireEvent.click(screen.getByRole("radio", { name: /^alto/i }));
    fireEvent.click(analyze());
    await waitFor(() => expect(made.createRun).toHaveBeenCalledTimes(1));
    expect(made.createRun).toHaveBeenCalledWith({
      event_id: "match_2027",
      attendance_level: "high",
      manual_response: false,
    });
    expect(made.updateEvent).not.toHaveBeenCalled();
    expect(made.createEvent).not.toHaveBeenCalled();
    expect(await screen.findByTestId("followed-run")).toHaveTextContent("run_new");
  });

  it("il livello di partenza è il medio", async () => {
    const made = await loaded();
    fireEvent.click(analyze());
    await waitFor(() => expect(made.createRun).toHaveBeenCalled());
    expect(made.createRun.mock.calls[0]?.[0]).toMatchObject({ attendance_level: "mid" });
  });

  it("la risposta manuale scelta nella barra (shell) parte con il run", async () => {
    const made = makeClient();
    setup(made.client, { manualResponse: true });
    await showing(match.name);
    fireEvent.click(analyze());
    await waitFor(() => expect(made.createRun).toHaveBeenCalled());
    expect(made.createRun.mock.calls[0]?.[0]).toMatchObject({ manual_response: true });
  });

  it("su un evento modificato lo salva (PUT, stesso id) e poi avvia il run", async () => {
    const made = await loaded();
    type(copy.name, "Match rivisto");
    type(copy.arrival, "45");
    fireEvent.click(analyze());
    await waitFor(() => expect(made.updateEvent).toHaveBeenCalledTimes(1));
    const [id, body] = made.updateEvent.mock.calls[0] as [string, EventInput];
    expect(id).toBe("match_2027");
    expect(body.id).toBe("match_2027");
    expect(body.name).toBe("Match rivisto");
    expect(body.background.arrival_peak_share).toBe(0.45);
    // il resto arriva com'era
    expect(body.closures).toEqual(match.closures);
    expect(body.resources).toEqual(match.resources);
    await waitFor(() => expect(made.createRun).toHaveBeenCalledTimes(1));
    expect(made.createRun.mock.calls[0]?.[0]).toMatchObject({ event_id: "match_2027" });
    // salvare e poi avviare, in quest'ordine
    expect(made.updateEvent.mock.invocationCallOrder[0]).toBeLessThan(
      made.createRun.mock.invocationCallOrder[0] as number,
    );
  });

  it("dopo il salvataggio il form non risulta più modificato", async () => {
    await loaded();
    type(copy.name, "Match rivisto");
    fireEvent.click(analyze());
    await waitFor(() => expect(screen.queryByText(copy.unsaved)).not.toBeInTheDocument());
    expect(field(copy.name)).toHaveValue("Match rivisto");
  });

  it("le modifiche alle chiusure, alle interruzioni e alle fonti vanno nel corpo", async () => {
    const made = await loaded();
    fireEvent.click(screen.getByRole("button", { name: `Rimuovi ${match.closures?.[1]?.label}` }));
    type("Etichetta Arco Mirelli", "Mirelli ferma");
    fireEvent.change(screen.getByRole("combobox", { name: "Finestra Arco Mirelli" }), {
      target: { value: "both" },
    });
    type("Fonte etichetta 1", "Ordinanza 12");
    fireEvent.click(analyze());
    await waitFor(() => expect(made.updateEvent).toHaveBeenCalled());
    const body = made.updateEvent.mock.calls[0]?.[1] as EventInput;
    expect(body.closures).toHaveLength(1);
    expect(body.closures?.[0]?.source_ref).toBe("Ordinanza 12");
    expect(body.transit_disruptions?.[0]).toMatchObject({ label: "Mirelli ferma", window: "both" });
  });

  it("occupazione auto e ripartizione modale (Avanzate) vanno nel corpo; vuoti restano predefiniti", async () => {
    const made = await loaded();
    fireEvent.click(screen.getByRole("button", { name: copy.advanced }));
    type(copy.carOccupancy, "2,5");
    type("Zone vicine · Auto", "30");
    type("Zone vicine · TPL", "20");
    type("Zone vicine · A piedi", "50");
    fireEvent.click(analyze());
    await waitFor(() => expect(made.updateEvent).toHaveBeenCalled());
    const body = made.updateEvent.mock.calls[0]?.[1] as EventInput;
    expect(body.car_occupancy).toBe(2.5);
    expect(body.modal_split_override).toEqual({
      near: { car_pct: 30, transit_pct: 20, walk_pct: 50 },
    });
  });

  it("misure reali e fonti: si aggiungono e si tolgono", async () => {
    const made = await loaded();
    fireEvent.click(screen.getByRole("button", { name: copy.extras }));
    fireEvent.click(screen.getByRole("button", { name: copy.addMeasure }));
    type("Nome della misura 1", "Presidio");
    type("Tipo 1", "traffic_post");
    type("Dove 1", "Piazza Vittoria");
    type("Fonte 1", "Ordinanza 9");
    fireEvent.click(screen.getByRole("button", { name: copy.addSource }));
    fireEvent.click(screen.getByRole("button", { name: copy.addSource }));
    fireEvent.change(screen.getAllByRole("textbox", { name: /^Fonte [12]$/ })[1] as HTMLElement, {
      target: { value: "Comune di Napoli" },
    });
    fireEvent.click(analyze());
    await waitFor(() => expect(made.updateEvent).toHaveBeenCalled());
    const body = made.updateEvent.mock.calls[0]?.[1] as EventInput;
    expect(body.real_measures).toEqual([
      {
        label: "Presidio",
        measure_type: "traffic_post",
        target: "Piazza Vittoria",
        source_ref: "Ordinanza 9",
      },
    ]);
    // la riga di fonte vuota non parte
    expect(body.sources).toEqual(["Comune di Napoli"]);
  });
});

describe("Event Manager: errori", () => {
  const validation = (fields: { path: string; message: string }[]) =>
    new ApiError(400, {
      code: "VALIDATION_ERROR",
      message: "La richiesta non è valida",
      details: { fields },
    });

  it("gli errori dell'API stanno accanto al loro campo e il run non parte", async () => {
    const made = makeClient({
      updateEvent: vi.fn(() =>
        Promise.reject(
          validation([
            { path: "arrival.peak", message: "il picco deve cadere nella finestra" },
            {
              path: "attendance.high",
              message: "il livello alto non può essere inferiore al medio",
            },
            { path: "resources.0.municipal_police_patrols_committed", message: "troppe pattuglie" },
          ]),
        ),
      ),
    });
    setup(made.client);
    await showing(match.name);
    type(copy.name, "Match rivisto");
    fireEvent.click(analyze());
    expect(await screen.findByText("il picco deve cadere nella finestra")).toBeInTheDocument();
    expect(field("Picco arrivo")).toHaveAttribute("aria-invalid", "true");
    expect(field("Picco arrivo")).toHaveAccessibleDescription(
      "il picco deve cadere nella finestra",
    );
    // «Alto» non è il livello scelto: l'errore si legge lo stesso, col nome del livello
    expect(
      screen.getByText("Alto: il livello alto non può essere inferiore al medio"),
    ).toBeInTheDocument();
    expect(screen.getByText("troppe pattuglie")).toBeInTheDocument();
    expect(made.createRun).not.toHaveBeenCalled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument(); // tutti hanno un campo
    expect(analyze()).toBeEnabled(); // si corregge e si riprova
    // modificando il campo l'errore se ne va
    type("Picco arrivo", "17:30");
    expect(screen.queryByText("il picco deve cadere nella finestra")).not.toBeInTheDocument();
    expect(screen.getByText("troppe pattuglie")).toBeInTheDocument();
  });

  it("un errore su ciò che il form non mostra si legge in cima, con il suo percorso", async () => {
    const update = vi
      .fn()
      .mockRejectedValueOnce(
        validation([{ path: "closures.0.edge_keys", message: "chiavi arco non valide" }]),
      )
      .mockImplementation((_id: string, input: EventInput) => Promise.resolve(saved(input)));
    const made = makeClient({ updateEvent: update });
    setup(made.client);
    await showing(match.name);
    type(copy.name, "Match rivisto");
    fireEvent.click(analyze());
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(copy.invalidTitle);
    expect(alert).toHaveTextContent("closures.0.edge_keys: chiavi arco non valide");
    // si riprova: il corpo è lo stesso e questa volta va
    fireEvent.click(analyze());
    await waitFor(() => expect(made.createRun).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    expect(update).toHaveBeenCalledTimes(2);
  });

  it("un errore dell'API che non è di validazione (limite di richieste) si legge e si può riprovare", async () => {
    const createRun = vi
      .fn()
      .mockRejectedValueOnce(
        new ApiError(429, {
          code: "RATE_LIMITED",
          message: "Troppe analisi: riprova tra un minuto",
        }),
      )
      .mockResolvedValue({ run_id: "run_new" });
    setup(makeClient({ createRun }).client);
    await showing(match.name);
    fireEvent.click(analyze());
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Troppe analisi: riprova tra un minuto",
    );
    expect(screen.getByTestId("followed-run")).toHaveTextContent("nessuno");
    expect(analyze()).toBeEnabled();
    fireEvent.click(analyze());
    await waitFor(() => expect(screen.getByTestId("followed-run")).toHaveTextContent("run_new"));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("se il run non parte dopo il salvataggio l'evento resta salvato (non si salva due volte)", async () => {
    const createRun = vi
      .fn()
      .mockRejectedValueOnce(new ApiError(429, { code: "RATE_LIMITED", message: "ritenta" }))
      .mockResolvedValue({ run_id: "run_new" });
    const made = makeClient({ createRun });
    setup(made.client);
    await showing(match.name);
    type(copy.name, "Match rivisto");
    fireEvent.click(analyze());
    await screen.findByRole("alert");
    expect(made.updateEvent).toHaveBeenCalledTimes(1);
    fireEvent.click(analyze());
    await waitFor(() => expect(createRun).toHaveBeenCalledTimes(2));
    expect(made.updateEvent).toHaveBeenCalledTimes(1);
  });
});

describe("Event Manager: run in corso", () => {
  it("con un run non finito Analizza è spento e dice «in corso»", async () => {
    const { client } = makeClient({ getRun: () => Promise.resolve(runBusy) });
    setup(client, { runId: "run_mock_match_2027" });
    await showing(match.name);
    await waitFor(() => expect(analyze()).toHaveTextContent(copy.analyzing));
    expect(analyze()).toBeDisabled();
    expect(analyze()).toHaveAttribute("aria-busy", "true");
    // un run in corso non è un campo mancante
    expect(screen.queryByText(/Manc/)).not.toBeInTheDocument();
  });

  it("con un run finito si può analizzare di nuovo", async () => {
    const { client } = makeClient({ getRun: () => Promise.resolve(runDone) });
    setup(client, { runId: "run_mock_match_2027" });
    await showing(match.name);
    await waitFor(() => expect(analyze()).toBeEnabled());
    expect(analyze()).toHaveTextContent(copy.analyze);
    expect(analyze()).not.toHaveAttribute("aria-busy");
  });
});

describe("Event Manager: analyze chiamato direttamente", () => {
  /** Chi non passa dal pulsante (un altro punto dell'interfaccia) usa `analyze` dell'editor. */
  function AnalyzeProbe() {
    const editor = useEventEditor();
    return <button onClick={() => void editor.analyze()}>analizza da fuori</button>;
  }

  it("con un run in corso non salva e non avvia nulla (la guardia è dell'editor, non del pulsante)", async () => {
    const made = makeClient({ getRun: () => Promise.resolve(runBusy) });
    render(
      <ApiProvider client={made.client}>
        <ShellProvider initial={{ runId: "run_mock_match_2027" }}>
          <EventEditorProvider>
            <EventManager />
            <AnalyzeProbe />
          </EventEditorProvider>
        </ShellProvider>
      </ApiProvider>,
    );
    await showing(match.name);
    await waitFor(() => expect(analyze()).toHaveAttribute("aria-busy", "true"));
    type(copy.name, "Match rivisto"); // anche con modifiche da salvare
    fireEvent.click(screen.getByRole("button", { name: "analizza da fuori" }));
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(made.updateEvent).not.toHaveBeenCalled();
    expect(made.createRun).not.toHaveBeenCalled();
  });
});

describe("Event Manager: scelte sulla mappa", () => {
  it("le tre modalità si accendono una per volta e si spengono con un secondo clic", async () => {
    await loaded();
    const centre = screen.getByRole("button", { name: copy.pickCenter });
    const streets = screen.getByRole("button", { name: copy.pickStreets });
    const stops = screen.getByRole("button", { name: copy.pickStops });
    for (const b of [centre, streets, stops]) expect(b).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(streets);
    expect(screen.getByRole("button", { name: copy.pickingStreets })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(centre).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(screen.getByRole("button", { name: copy.pickStops }));
    expect(screen.getByRole("button", { name: copy.pickingStops })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: copy.pickStreets })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    fireEvent.click(screen.getByRole("button", { name: copy.pickingStops }));
    expect(screen.getByRole("button", { name: copy.pickStops })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("cambiare evento spegne la modalità", async () => {
    await loaded();
    fireEvent.click(screen.getByRole("button", { name: copy.pickStreets }));
    fireEvent.change(screen.getByRole("combobox", { name: copy.eventLabel }), {
      target: { value: "regate_sep_2026" },
    });
    await showing(regate.name);
    expect(screen.getByRole("button", { name: copy.pickStreets })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("il cursore del raggio e il suo campo vanno insieme", async () => {
    await loaded();
    const slider = screen.getByRole("slider", { name: copy.radiusSlider });
    fireEvent.change(slider, { target: { value: "700" } });
    expect(field(copy.radius)).toHaveValue("700");
    type(copy.radius, "950");
    expect(slider).toHaveValue("950");
  });
});
