import { describe, expect, it } from "vitest";
import { ApiError } from "@/api/errors";
import { createMockClient, type MockOptions } from "@/api/mock";
import type { LayerName, RunView } from "@/api/types";
import { fixture } from "@/test/fixtures";

const RUN = "run_mock_match_2027";
const LAYERS: LayerName[] = [
  "edges_vc",
  "closures",
  "critical_intersections",
  "stops",
  "sections",
  "event_area",
  "requests",
];
const manifest = fixture<{
  run_sequence: {
    state: string;
    run_view: string;
    decisions: string;
    iterations_available: number[];
  }[];
}>("manifest.json");
const SEQUENCE = manifest.run_sequence;

/** Un client mock con la sessione già aperta. */
const open = (options: MockOptions = {}) => createMockClient({ authenticated: true, ...options });

async function fails(promise: Promise<unknown>): Promise<ApiError> {
  const error = await promise.then(
    () => undefined,
    (e: unknown) => e,
  );
  expect(error).toBeInstanceOf(ApiError);
  return error as ApiError;
}

/** Il client con `steps` `getRun` già serviti. */
async function after(steps: number, options: MockOptions = {}) {
  const client = open(options);
  for (let n = 0; n < steps; n++) await client.getRun(RUN);
  return client;
}

describe("mock: sessione", () => {
  it("senza sessione ogni operazione protetta risponde 401, come il server", async () => {
    const client = createMockClient();
    const calls = [
      () => client.listEvents(),
      () => client.getEvent("match_2027"),
      () => client.createEvent({} as never),
      () => client.networkEdges("0,0,1,1"),
      () =>
        client.createRun({
          event_id: "match_2027",
          attendance_level: "mid",
          manual_response: false,
        }),
      () => client.getRun(RUN),
      () => client.runMetrics(RUN, 0),
      () => client.runNotifications(RUN),
      () => client.ackNotification(2),
      () => client.vdeptRegistry(),
      () => client.liveFlow(),
      () => client.listSensors(),
    ];
    for (const call of calls) {
      const error = await fails(call());
      expect(error).toMatchObject({ status: 401, code: "UNAUTHENTICATED" });
      expect(error.isUnauthorized).toBe(true);
    }
  });

  it("health, me, login e logout non richiedono la sessione", async () => {
    const client = createMockClient();
    await expect(client.health()).resolves.toEqual(fixture("health.json"));
    await expect(client.me()).resolves.toEqual({ authenticated: false });
  });

  it("login con una password non vuota apre la sessione, logout la chiude", async () => {
    const client = createMockClient();
    await expect(client.login("qualunque")).resolves.toEqual({ authenticated: true });
    await expect(client.me()).resolves.toEqual({ authenticated: true });
    await expect(client.listEvents()).resolves.toHaveLength(2);
    await expect(client.logout()).resolves.toEqual({ authenticated: false });
    await expect(client.me()).resolves.toEqual({ authenticated: false });
    expect((await fails(client.listEvents())).status).toBe(401);
  });

  it("la password vuota è una richiesta non valida e non apre la sessione", async () => {
    const client = createMockClient();
    const error = await fails(client.login(""));
    expect(error).toMatchObject({ status: 400 });
    await expect(client.me()).resolves.toEqual({ authenticated: false });
  });

  it("si può partire con la sessione già aperta", async () => {
    await expect(open().me()).resolves.toEqual({ authenticated: true });
  });

  it("health in modalità degradata dà la fixture con il grafo assente", async () => {
    const client = createMockClient({ health: "degraded" });
    await expect(client.health()).resolves.toEqual(fixture("health_degraded.json"));
    expect(fixture("health_degraded.json")).not.toEqual(fixture("health.json"));
  });
});

describe("mock: eventi", () => {
  it("elenca e legge i due preset", async () => {
    const client = open();
    await expect(client.listEvents()).resolves.toEqual(fixture("events_list.json"));
    await expect(client.getEvent("match_2027")).resolves.toEqual(fixture("event_match_2027.json"));
    await expect(client.getEvent("regate_sep_2026")).resolves.toEqual(
      fixture("event_regate_sep_2026.json"),
    );
  });

  it("un evento sconosciuto è un 404", async () => {
    const client = open();
    for (const call of [
      () => client.getEvent("nessuno"),
      () => client.updateEvent("nessuno", {} as never),
      () => client.resetEvent("nessuno"),
      () => client.resolveEvent("nessuno"),
    ]) {
      expect(await fails(call())).toMatchObject({
        status: 404,
        code: "NOT_FOUND",
        message: "Evento non trovato",
      });
    }
  });

  it("l'evento creato si può poi leggere", async () => {
    const client = open();
    const created = await client.createEvent({} as never);
    expect(created).toEqual(fixture("event_created.json"));
    await expect(client.getEvent(created.id)).resolves.toEqual(created);
    await expect(client.updateEvent(created.id, {} as never)).resolves.toEqual(
      fixture("event_updated.json"),
    );
  });

  it("ripristino e risoluzione danno le fixture", async () => {
    const client = open();
    await expect(client.resetEvent("match_2027")).resolves.toEqual(fixture("event_reset.json"));
    await expect(client.resolveEvent("match_2027")).resolves.toEqual(
      fixture("event_resolve_preview.json"),
    );
  });

  it("rete e trasporto pubblico", async () => {
    const client = open();
    await expect(client.networkEdges("0,0,1,1")).resolves.toEqual(fixture("network_edges.json"));
    await expect(client.transitStops("0,0,1,1")).resolves.toEqual(fixture("transit_stops.json"));
    await expect(client.transitLines()).resolves.toEqual(fixture("transit_lines.json"));
  });
});

describe("mock: la sequenza di un run", () => {
  it("a ogni polling avanza di un fotogramma, nell'ordine del manifest, e si ferma su DONE", async () => {
    const client = open();
    const seen: string[] = [];
    for (let n = 0; n < SEQUENCE.length + 3; n++) {
      const view = await client.getRun(RUN);
      seen.push(view.run.state);
      const index = Math.min(n, SEQUENCE.length - 1);
      expect(view).toEqual(fixture(SEQUENCE[index]?.run_view ?? ""));
    }
    expect(seen.slice(0, SEQUENCE.length)).toEqual(SEQUENCE.map((frame) => frame.state));
    expect(seen.slice(SEQUENCE.length)).toEqual(["DONE", "DONE", "DONE"]);
    expect(seen).toContain("REPLAN"); // il rifiuto e la ripianificazione ci sono
  });

  it("createRun riparte dal primo fotogramma", async () => {
    const client = await after(6);
    await expect(
      client.createRun({ event_id: "match_2027", attendance_level: "mid", manual_response: false }),
    ).resolves.toEqual(fixture("run_created.json"));
    expect((await client.getRun(RUN)).run.state).toBe("INTAKE");
  });

  it("le decisioni sono quelle del fotogramma corrente", async () => {
    const client = open();
    await expect(client.runDecisions(RUN)).resolves.toEqual(fixture(SEQUENCE[0]?.decisions ?? ""));
    for (let n = 0; n < SEQUENCE.length; n++) {
      await client.getRun(RUN);
      await expect(client.runDecisions(RUN)).resolves.toEqual(
        fixture(SEQUENCE[n]?.decisions ?? ""),
      );
    }
    expect(
      fixture<unknown[]>(SEQUENCE[SEQUENCE.length - 1]?.decisions ?? "").length,
    ).toBeGreaterThan(fixture<unknown[]>(SEQUENCE[0]?.decisions ?? "").length);
  });

  it("le comunicazioni partono dopo DONE: prima niente, all'ultimo fotogramma WhatsApp e i bollettini", async () => {
    const client = open();
    await expect(client.runNotifications(RUN)).resolves.toEqual([]);
    for (let n = 0; n < SEQUENCE.length - 1; n++) await client.getRun(RUN); // fino a un passo dalla fine
    await expect(client.runNotifications(RUN, "whatsapp")).resolves.toEqual([]);
    await client.getRun(RUN); // DONE
    const all = await client.runNotifications(RUN);
    expect(all).toEqual(fixture("run_notifications.json"));
    const whatsapp = await client.runNotifications(RUN, "whatsapp");
    expect(whatsapp).toHaveLength(1);
    expect(whatsapp[0]).toMatchObject({ channel: "whatsapp", state: "SENT", simulation: false });
    expect(whatsapp[0]?.recipient_label).toBe("+39 *** *** **12"); // mai il numero vero
    const bulletins = await client.runNotifications(RUN, "emergency_bulletin");
    expect(bulletins).toHaveLength(8); // uno per destinatario di config/emergency_services.yaml
    expect(bulletins.every((row) => row.simulation && row.state === "DELIVERED")).toBe(true);
    expect(new Set(bulletins.map((row) => row.recipient_id)).size).toBe(8);
    expect(bulletins[0]?.text.startsWith("BOLLETTINO VIABILITÀ — SIMULATO")).toBe(true);
  });

  it("«Conferma ricezione»: il bollettino passa a ACKNOWLEDGED, una volta sola; WhatsApp non si conferma", async () => {
    const client = await after(SEQUENCE.length);
    const [first, second] = await client.runNotifications(RUN, "emergency_bulletin");
    const done = await client.ackNotification(first?.id as number);
    expect(done).toMatchObject({ id: first?.id, state: "ACKNOWLEDGED", simulation: true });
    const after2 = await client.runNotifications(RUN, "emergency_bulletin");
    expect(after2.map((row) => row.state).slice(0, 2)).toEqual(["ACKNOWLEDGED", "DELIVERED"]);
    expect(after2[1]?.id).toBe(second?.id);
    expect(await fails(client.ackNotification(first?.id as number))).toMatchObject({
      status: 409,
      code: "NOT_ACKNOWLEDGEABLE",
      details: { state: "ACKNOWLEDGED" },
    });
    const [whatsapp] = await client.runNotifications(RUN, "whatsapp");
    expect(await fails(client.ackNotification(whatsapp?.id as number))).toMatchObject({
      status: 409,
      details: { state: "SENT" },
    });
    expect(await fails(client.ackNotification(424242))).toMatchObject({ status: 404 });
  });

  it("un run sconosciuto è un 404 per ogni operazione del run", async () => {
    const client = open();
    for (const call of [
      () => client.getRun("nessuno"),
      () => client.runMetrics("nessuno", 0),
      () => client.runLayer("nessuno", "stops", 0),
      () => client.runDecisions("nessuno"),
      () => client.runNotifications("nessuno"),
      () => client.exportRun("nessuno"),
      () => client.exportRunCsv("nessuno", "metrics"),
    ]) {
      expect(await fails(call())).toMatchObject({ status: 404, message: "Run non trovato" });
    }
  });

  it("elenca i run, filtrati per evento", async () => {
    const client = open();
    const all = await client.listRuns();
    expect(all).toEqual(fixture("runs_list.json"));
    expect(all.length).toBeGreaterThan(1);
    const only = await client.listRuns("regate_sep_2026");
    expect(only.length).toBeGreaterThan(0);
    expect(only.every((run) => run.event_id === "regate_sep_2026")).toBe(true);
    await expect(client.listRuns("nessuno")).resolves.toEqual([]);
  });
});

describe("mock: la risposta manuale (04 5)", () => {
  const viewOf = (index: number) => fixture<RunView>(SEQUENCE[index]?.run_view ?? "");
  /** Il primo fotogramma con richieste ricevute: dove un run manuale aspetta. */
  const HOLD = SEQUENCE.findIndex((frame) =>
    fixture<RunView>(frame.run_view).requests.some((item) => item.request.state === "RECEIVED"),
  );
  const PENDING = viewOf(HOLD)
    .requests.filter((item) => item.request.state === "RECEIVED")
    .map((item) => item.request.action_id);
  const START = { event_id: "match_2027", attendance_level: "mid" } as const;

  /** Un run partito con `manual_response`, arrivato al fotogramma delle richieste ricevute. */
  async function manualAtHold(manual = true) {
    const client = open();
    await client.createRun({ ...START, manual_response: manual });
    for (let n = 0; n <= HOLD; n++) await client.getRun(RUN);
    return client;
  }
  const request = (view: RunView, id: string) =>
    view.requests.find((item) => item.request.action_id === id)?.request;

  it("il fotogramma delle richieste ricevute c'è, e ne ha più d'una", () => {
    expect(HOLD).toBeGreaterThan(0);
    expect(PENDING.length).toBeGreaterThan(1);
  });

  it("un run manuale resta sul fotogramma delle richieste ricevute, per quanti polling si vogliano", async () => {
    const client = await manualAtHold();
    for (let n = 0; n < 5; n++) expect(await client.getRun(RUN)).toEqual(viewOf(HOLD));
  });

  it("senza la risposta manuale il run non si ferma", async () => {
    const client = await manualAtHold(false);
    expect(await client.getRun(RUN)).toEqual(viewOf(HOLD + 1));
    expect(await client.getRun(RUN)).toEqual(viewOf(HOLD + 2));
  });

  it("chi risponde Accetta vede la richiesta accettata e le altre ancora in attesa", async () => {
    const client = await manualAtHold();
    await client.manualResponse("municipal_police", PENDING[0] ?? "", { decision: "accept" });
    const view = await client.getRun(RUN);
    expect(request(view, PENDING[0] ?? "")).toMatchObject({ state: "ACCEPTED", reject_code: null });
    for (const id of PENDING.slice(1)) expect(request(view, id)?.state).toBe("RECEIVED");
    expect(view.run).toEqual(viewOf(HOLD).run); // il run non è andato avanti
  });

  it("chi risponde Rifiuta vede lo stato rifiutato con il suo codice e il suo motivo", async () => {
    const client = await manualAtHold();
    await client.manualResponse("municipal_police", PENDING[0] ?? "", {
      decision: "reject",
      reject_code: "UNAVAILABLE",
      reject_reason: "Nessuna pattuglia libera",
    });
    expect(request(await client.getRun(RUN), PENDING[0] ?? "")).toMatchObject({
      state: "REJECTED",
      reject_code: "UNAVAILABLE",
      reject_reason: "Nessuna pattuglia libera",
    });
  });

  it("una richiesta senza risposta tiene fermo il run anche se le altre hanno risposto", async () => {
    const client = await manualAtHold();
    for (const id of PENDING.slice(1)) {
      await client.manualResponse("municipal_police", id, { decision: "accept" });
    }
    for (let n = 0; n < 3; n++) {
      const view = await client.getRun(RUN);
      expect(view.run).toEqual(viewOf(HOLD).run);
      expect(request(view, PENDING[0] ?? "")?.state).toBe("RECEIVED");
    }
  });

  it("con tutte le risposte date il run riprende dal fotogramma dopo, com'è registrato", async () => {
    const client = await manualAtHold();
    for (const id of PENDING) {
      await client.manualResponse("municipal_police", id, { decision: "accept" });
    }
    expect(await client.getRun(RUN)).toEqual(viewOf(HOLD + 1));
    expect(await client.getRun(RUN)).toEqual(viewOf(HOLD + 2));
  });

  it("un run nuovo riparte da capo: né l'attesa né le risposte del precedente", async () => {
    const client = await manualAtHold();
    await client.manualResponse("municipal_police", PENDING[0] ?? "", { decision: "accept" });
    await client.createRun({ ...START, manual_response: true });
    for (let n = 0; n <= HOLD; n++) await client.getRun(RUN);
    const view = await client.getRun(RUN);
    expect(view).toEqual(viewOf(HOLD)); // la risposta data al run di prima non c'è più
    await client.createRun({ ...START, manual_response: false });
    expect((await client.getRun(RUN)).run.state).toBe(SEQUENCE[0]?.state);
  });
});

describe("mock: le iterazioni compaiono quando il run le produce", () => {
  it("prima del fotogramma che le rende disponibili sono un 404", async () => {
    const client = open();
    expect(await fails(client.runMetrics(RUN, 0))).toMatchObject({ status: 404 });
    for (const [step, frame] of SEQUENCE.entries()) {
      await client.getRun(RUN);
      for (const iteration of [0, 1, 2]) {
        const available = frame.iterations_available.includes(iteration);
        const answer = client.runMetrics(RUN, iteration);
        if (available) {
          await expect(answer).resolves.toEqual(fixture(`run_metrics/iteration_${iteration}.json`));
        } else {
          expect(await fails(answer), `passo ${step}, iterazione ${iteration}`).toMatchObject({
            status: 404,
          });
        }
      }
    }
  });

  it("a run finito ogni layer di ogni iterazione è la sua fixture", async () => {
    const client = await after(SEQUENCE.length);
    for (const layer of LAYERS) {
      for (const iteration of [0, 1, 2]) {
        await expect(client.runLayer(RUN, layer, iteration)).resolves.toEqual(
          fixture(`run_layers/${layer}_it${iteration}.json`),
        );
      }
    }
  });

  it("un layer di un'iterazione non ancora prodotta è un 404", async () => {
    const client = await after(4); // il fotogramma «PLAN»: c'è solo l'iterazione 0
    await expect(client.runLayer(RUN, "stops", 0)).resolves.toBeDefined();
    expect((await fails(client.runLayer(RUN, "stops", 1))).status).toBe(404);
  });
});

describe("mock: varianti del run", () => {
  it.each([
    ["degraded", "run_view_variant_degraded.json"],
    ["error", "run_view_variant_error.json"],
    ["human_decision", "run_view_variant_human_decision.json"],
  ] as const)("%s: un solo fotogramma fisso", async (variant, file) => {
    const client = open({ runVariant: variant });
    const first: RunView = await client.getRun(RUN);
    expect(first).toEqual(fixture(file));
    await expect(client.getRun(RUN)).resolves.toEqual(first);
  });

  it("la variante di errore ha lo stato ERROR e il suo messaggio", async () => {
    const view = await open({ runVariant: "error" }).getRun(RUN);
    expect(view.run.state).toBe("ERROR");
    expect(view.run.error).toBeTruthy();
  });
});

describe("mock: esportazione, dipartimenti e LIVE", () => {
  it("esporta JSON e i due CSV", async () => {
    const client = open();
    await expect(client.exportRun(RUN)).resolves.toEqual(fixture("run_export.json"));
    await expect(client.exportRunCsv(RUN, "metrics")).resolves.toBe(
      fixture("run_export_metrics.csv"),
    );
    await expect(client.exportRunCsv(RUN, "critical_edges")).resolves.toBe(
      fixture("run_export_critical_edges.csv"),
    );
    expect((await client.exportRunCsv(RUN, "metrics")).split("\n")[0]).toContain("id");
  });

  it("registro, creazione, lettura e risposta manuale delle richieste", async () => {
    const client = open();
    await expect(client.vdeptRegistry(RUN)).resolves.toEqual(fixture("vdept_registry.json"));
    await expect(client.createVdeptRequest("municipal_police", {} as never)).resolves.toEqual(
      fixture("vdept_request_created.json"),
    );
    await expect(client.getVdeptRequest("municipal_police", "act_1")).resolves.toEqual(
      fixture("vdept_request.json"),
    );
    await expect(
      client.manualResponse("municipal_police", "act_1", { decision: "accept" }),
    ).resolves.toEqual(fixture("vdept_manual_response.json"));
  });

  it.each(["fresh", "cached", "snapshot", "unavailable"] as const)(
    "liveFlow in modo %s",
    async (mode) => {
      const client = open({ liveMode: mode });
      await expect(client.liveFlow()).resolves.toEqual(fixture(`live_flow_${mode}.json`));
    },
  );

  it("liveFlow è «fresh» se non si dice altro", async () => {
    await expect(open().liveFlow()).resolves.toEqual(fixture("live_flow_fresh.json"));
  });

  it("i sensori previsti sono la fixture: tutti `planned`, senza numeri né misure", async () => {
    const sensors = await open().listSensors();
    expect(sensors).toEqual(fixture("sensors.json"));
    expect(sensors.length).toBeGreaterThan(0);
    for (const sensor of sensors) {
      expect(sensor.status).toBe("planned");
      expect(Object.keys(sensor)).not.toContain("value"); // nessun Measured
    }
  });

  it("con l'accesso libero ogni chiamata passa senza sessione e uscire non chiude nulla", async () => {
    const client = createMockClient({ publicAccess: true });
    await expect(client.me()).resolves.toEqual({ authenticated: true, public_access: true });
    await expect(client.login("qualunque")).resolves.toEqual({
      authenticated: true,
      public_access: true,
    });
    await expect(client.listEvents()).resolves.toEqual(fixture("events_list.json"));
    await expect(client.logout()).resolves.toEqual({ authenticated: true, public_access: true });
    await expect(client.listEvents()).resolves.toEqual(fixture("events_list.json")); // ancora aperto
  });

  it("la base map è il file vero del backend: nessuna fixture", () => {
    expect(open().tilesUrl).toBe("/tiles/napoli.pmtiles");
  });
});

describe("mock: i dati dichiarano di essere di esempio", () => {
  it("ogni Measured delle metriche ha fonte «mock.fixture» e lo dice nelle assunzioni", async () => {
    const client = await after(SEQUENCE.length);
    const { metrics } = await client.runMetrics(RUN, 0);
    expect(metrics.length).toBeGreaterThan(10);
    // l'affluenza dell'Evento non è un valore di esempio: è il dato dell'Evento, scritto dalla stessa
    // funzione del backend vero (e per questo dichiara l'Evento come fonte)
    const examples = metrics.filter((m) => !m.id.endsWith(".event.attendance"));
    expect(examples.length).toBe(metrics.length - 1);
    expect(examples.every((m) => m.source.startsWith("mock.fixture"))).toBe(true);
    expect(examples.every((m) => (m.assumptions ?? []).some((a) => /esempio|mock/i.test(a)))).toBe(
      true,
    );
    const attendance = metrics.find((m) => m.id.endsWith(".event.attendance"));
    expect(attendance?.source).toMatch(/^Evento match_2027/);
  });
});
