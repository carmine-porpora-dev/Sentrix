import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@/api/errors";
import type { Event, Notification, RequestView, RunView } from "@/api/types";
import { OperationsPanel } from "@/features/run/OperationsPanel";
import {
  NOTIFICATION_POLL_MS,
  NOTIFICATION_WAIT_MS,
  notificationPollInterval,
} from "@/features/run/queries";
import { formatClock, formatDelta } from "@/lib/format";
import { strings } from "@/i18n/it";
import { fixture } from "@/test/fixtures";
import { doneView, event, metrics, renderPanel, runClient, RUN, withRun } from "@/test/runPanels";

const copy = strings.panels.ops;
const section = (name: string) => screen.getByRole("region", { name });
const card = (code: string) => screen.getByRole("article", { name: code });

async function shown(
  options: Parameters<typeof runClient>[0] = {},
  initial?: Parameters<typeof renderPanel>[2],
) {
  const made = runClient(options);
  renderPanel(made.client, <OperationsPanel />, initial);
  await screen.findByRole("region", { name: copy.plan(5) });
  return made;
}

describe("OperationsPanel: il piano", () => {
  it("ogni misura con il suo testo, il tipo, il dipartimento, la finestra e lo stato", async () => {
    await shown();
    const plan = within(section(copy.plan(5)));
    expect(plan.getAllByRole("listitem").length).toBeGreaterThanOrEqual(6);
    const first = plan
      .getByText(doneView.plan[0]?.recommendation.rationale as string)
      .closest("li") as HTMLElement;
    expect(within(first).getByText(copy.measureTypes.traffic_post)).toBeInTheDocument();
    expect(within(first).getByText("Polizia Municipale (virtuale)")).toBeInTheDocument();
    expect(within(first).getByText(strings.metrics.windows.departure)).toBeInTheDocument();
    expect(within(first).getByText(copy.planStatus.accepted)).toBeInTheDocument();
  });

  it("«Sostituita dalla misura n» solo per le sostituite", async () => {
    const view: RunView = {
      ...doneView,
      plan: doneView.plan.map((item) =>
        item.status === "accepted" ? { ...item, replaced_by: 4 } : item,
      ),
    };
    await shown({ view });
    expect(within(section(copy.plan(5))).getAllByText(copy.replacedBy(4))).toHaveLength(1); // solo la sostituita
  });

  it("una misura sostituita dice da quale; una scartata dice perché", async () => {
    await shown();
    const plan = within(section(copy.plan(5)));
    expect(plan.getByText(copy.replacedBy(4))).toBeInTheDocument();
    expect(plan.getByText(copy.planStatus.replaced)).toBeInTheDocument();
    const discarded = doneView.plan.find((p) => p.status === "discarded");
    expect(plan.getByText(discarded?.note as string)).toBeInTheDocument();
    expect(plan.getByText(copy.planStatus.discarded)).toBeInTheDocument();
  });

  it("i numeri citati come evidenza hanno la loro provenienza (letti dalle metriche)", async () => {
    await shown();
    const row = within(section(copy.plan(5)))
      .getByText(doneView.plan[0]?.recommendation.rationale as string)
      .closest("li") as HTMLElement;
    const chip = within(row)
      .getByText("road.departure.critical_intersection.1.vc")
      .closest("li") as HTMLElement;
    await waitFor(() => expect(within(chip).getByText("%")).toBeInTheDocument());
  });

  it("il piano è tra le ipotesi: porta il badge SIMULATO", async () => {
    await shown();
    expect(
      within(section(copy.plan(5))).getByText(strings.metrics.badges.simulated),
    ).toBeInTheDocument();
  });

  it("le misure adottate nella realtà, dall'Evento, con il badge REALE", async () => {
    const real: Event = {
      ...event,
      real_measures: [
        {
          label: "Presidio reale",
          measure_type: "traffic_post",
          target: "Piazza Vittoria",
          source_ref: "Comune di Napoli",
        },
      ],
    };
    await shown({ event: real });
    const measures = within(await screen.findByRole("region", { name: copy.realMeasures }));
    expect(measures.getByText("Presidio reale")).toBeInTheDocument();
    expect(measures.getByText(/Comune di Napoli/)).toBeInTheDocument();
    expect(measures.getByText(strings.metrics.badges.real)).toBeInTheDocument();
  });

  it("una misura reale di un tipo sconosciuto non mostra il codice e dice che il motore non la modella", async () => {
    const real: Event = {
      ...event,
      real_measures: [
        {
          label: "Senso unico in corsia preferenziale",
          measure_type: "bus_lane_opening",
          target: "Riviera di Chiaia",
          source_ref: "Comune di Napoli",
        },
        {
          label: "Metro prolungata",
          measure_type: "extend_hours",
          target: "metro",
          source_ref: "ANM",
        },
        {
          label: "Tipo che somiglia a una proprietà degli oggetti",
          measure_type: "constructor",
          target: "x",
          source_ref: "y",
        },
      ],
    };
    await shown({ event: real });
    const items = within(
      await screen.findByRole("region", { name: copy.realMeasures }),
    ).getAllByRole("listitem");
    const [unknown, known, odd] = items as [HTMLElement, HTMLElement, HTMLElement];
    expect(odd).toHaveTextContent(copy.realNotModelled); // non è un tipo noto solo perché esiste su Object
    expect(unknown).not.toHaveTextContent("bus_lane_opening");
    expect(unknown).toHaveTextContent("Riviera di Chiaia · Comune di Napoli");
    expect(unknown).toHaveTextContent(copy.realNotModelled);
    // un tipo che il sistema conosce ha il suo nome e nessuna nota
    expect(known).toHaveTextContent("Estensione d'orario · metro · ANM");
    expect(known).not.toHaveTextContent(copy.realNotModelled);
  });

  it("senza misure reali la sezione non c'è", async () => {
    await shown();
    expect(screen.queryByRole("region", { name: copy.realMeasures })).not.toBeInTheDocument();
  });

  it("un piano non ancora arrivato lo dice", async () => {
    const made = runClient({ view: withRun({ state: "ANALYZE" }, { plan: [] }) });
    renderPanel(made.client, <OperationsPanel />);
    expect(await screen.findByText(copy.noPlan)).toBeInTheDocument();
  });
});

describe("OperationsPanel: i dipartimenti", () => {
  it("quattro schede con le risorse residue della finestra scelta", async () => {
    await shown();
    const departments = within(section(copy.departments));
    const police = departments
      .getByText("Polizia Municipale (virtuale)")
      .closest("li") as HTMLElement;
    expect(police).toHaveTextContent("0");
    expect(police).toHaveTextContent(`${copy.of} 6`);
    expect(within(police).getByText(copy.resources.patrols)).toBeInTheDocument();
    const transport = departments
      .getByText("Controllo Trasporti (virtuale)")
      .closest("li") as HTMLElement;
    expect(within(transport).getByText(copy.resources.reserve_buses)).toBeInTheDocument();
    expect(within(transport).getByText(copy.resources.hour_extensions)).toBeInTheDocument();
    const comms = departments
      .getByText("Comunicazione Pubblica (virtuale)")
      .closest("li") as HTMLElement;
    expect(within(comms).getByText(copy.noResources)).toBeInTheDocument();
  });

  it("le risorse esaurite sono in rosso, le altre no", async () => {
    await shown();
    const departments = within(section(copy.departments));
    const police = departments
      .getByText("Polizia Municipale (virtuale)")
      .closest("li") as HTMLElement;
    expect(within(police).getByText("0")).toHaveClass("text-status-rejected");
    // le scorte di bus (8 su 8): il primo «8» è il residuo, il secondo il totale
    const buses = within(
      departments.getByText("Controllo Trasporti (virtuale)").closest("li") as HTMLElement,
    ).getAllByText("8")[0];
    expect(buses).not.toHaveClass("text-status-rejected");
  });

  it("le risorse esaurite si vedono (0 in rosso) e cambiano con la finestra", async () => {
    await shown({}, { runId: RUN, window: "arrival" });
    const police = within(section(copy.departments))
      .getByText("Polizia Municipale (virtuale)")
      .closest("li") as HTMLElement;
    expect(police).toHaveTextContent("3");
    expect(police).toHaveTextContent(`${copy.of} 6`);
  });

  it("tra le ipotesi: badge SIMULATO; non c'è senza un run", async () => {
    await shown();
    expect(
      within(section(copy.departments)).getByText(strings.metrics.badges.simulated),
    ).toBeInTheDocument();
    const none = runClient();
    renderPanel(none.client, <OperationsPanel />, {});
    // il registro dei dipartimenti c'è (senza risorse), ma senza un run non si mostrano le schede
    await waitFor(() => expect(none.vdeptRegistry).toHaveBeenCalledTimes(1));
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(screen.queryAllByRole("region", { name: copy.departments })).toHaveLength(1); // quello di prima
  });

  it("le risorse si chiedono per il run", async () => {
    const made = await shown();
    await waitFor(() => expect(made.vdeptRegistry).toHaveBeenCalledWith(RUN));
  });
});

describe("OperationsPanel: le richieste", () => {
  it("ogni richiesta con il dipartimento, il codice, lo stato e che cosa chiede", async () => {
    await shown();
    const first = card("act_001");
    expect(within(first).getByText("Polizia Municipale (virtuale)")).toBeInTheDocument();
    expect(within(first).getByText(copy.state.IN_PROGRESS)).toBeInTheDocument();
    expect(first).toHaveTextContent(`${copy.measureTypes.traffic_post} — Incrocio Piazza Vittoria`);
    expect(within(card("act_003")).getByText(copy.state.ACCEPTED)).toBeInTheDocument();
    expect(within(card("act_005")).getByText(copy.state.COMPLETED)).toBeInTheDocument();
  });

  it("una misura stradale in vigore dice l'effetto locale: carico massimo prima → dopo, dal motore", async () => {
    await shown();
    // act_001: presidio in Piazza Vittoria, v/c 1,08 → 1,01; act_004: semaforo in Piazza Sannazaro, 0,97 → 0,91
    const effect = copy.effect;
    const first = card("act_001");
    expect(first).toHaveTextContent(effect.label);
    expect(first).toHaveTextContent(effect.what);
    const [before, after] = within(first).getAllByText(/^\d+$/);
    expect(before).toHaveTextContent("108");
    expect(after).toHaveTextContent("101");
    expect(first).toHaveTextContent("108→101%");
    expect(card("act_004")).toHaveTextContent("97→91%");
    // sono numeri del motore, con il loro tooltip di provenienza (principio 2): `data-measured`
    expect(first.querySelectorAll("[data-measured='simulated']")).toHaveLength(2);
    // «dopo» più basso è meglio: colore del design per il miglioramento
    expect(after?.closest("[data-measured]")).toHaveClass("text-delta-better");
  });

  it("le richieste senza effetto da dire non hanno la riga: rifiutata, linea, avviso", async () => {
    await shown();
    for (const code of ["act_002", "act_003", "act_005"]) {
      expect(card(code)).not.toHaveTextContent(copy.effect.label);
    }
  });

  it("se il carico sale, dopo è nel colore del peggioramento", async () => {
    const worse = structuredClone(metrics(1));
    for (const m of worse.metrics) {
      if (m.id.endsWith(".measure_effect.act_001.vc_after")) m.value = 1.3;
    }
    await shown({
      overrides: { runMetrics: (_runId, n) => Promise.resolve(n === 1 ? worse : metrics(n)) },
    });
    const first = card("act_001");
    await waitFor(() => expect(first).toHaveTextContent("108→130%"));
    const after = within(first).getByText("130");
    expect(after.closest("[data-measured]")).toHaveClass("text-delta-worse");
  });

  it("un rifiuto dice il codice e il motivo", async () => {
    await shown();
    const rejected = card("act_002");
    expect(within(rejected).getByText(copy.state.REJECTED)).toBeInTheDocument();
    expect(within(rejected).getByText("UNAVAILABLE")).toBeInTheDocument();
    expect(rejected).toHaveTextContent("Pattuglie esaurite nella finestra 21:00–23:00");
  });

  it("l'alternativa sta sotto la richiesta rifiutata, e il suo titolo la apre e la chiude", async () => {
    await shown();
    const toggle = screen.getByRole("button", { name: copy.alternatives(1) });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(card("act_004")).toHaveTextContent(copy.alternativeTo("act_002"));
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("article", { name: "act_004" })).not.toBeInTheDocument();
    fireEvent.click(toggle);
    expect(card("act_004")).toBeInTheDocument();
  });

  it("se il tipo di misura e il bersaglio si chiamano uguale (l'avviso) il testo non si ripete", async () => {
    await shown();
    const notice = card("act_005");
    expect(notice).toHaveTextContent(
      `${copy.measureTypes.citizen_notice} · ${strings.metrics.windows.departure}`,
    );
    expect(notice.textContent).not.toContain(`${copy.measureTypes.citizen_notice} —`);
  });

  it("senza richieste lo dice; le richieste con un luogo lo mostrano sulla mappa", async () => {
    const none = runClient({ view: withRun({ state: "PLAN" }, { requests: [] }) });
    renderPanel(none.client, <OperationsPanel />);
    expect(await screen.findByText(copy.noRequests)).toBeInTheDocument();
  });

  it("«Mostra sulla mappa» porta la mappa sul luogo della richiesta", async () => {
    await shown();
    const geo = doneView.requests.find((r) => r.request.action_id === "act_001")?.request
      .target_geo;
    fireEvent.click(within(card("act_001")).getByRole("button", { name: copy.showOnMap }));
    expect(screen.getByTestId("shell")).toHaveTextContent(`focus=${geo?.lat},${geo?.lon}#1`);
    // una richiesta senza luogo (l'avviso ai cittadini) non ha il pulsante
    expect(
      within(card("act_005")).queryByRole("button", { name: copy.showOnMap }),
    ).not.toBeInTheDocument();
  });
});

describe("OperationsPanel: risposta manuale", () => {
  it("l'interruttore parte spento, dice che cosa cambia e si accende", async () => {
    await shown();
    const toggle = screen.getByRole("switch", { name: new RegExp(copy.manualSwitch) });
    expect(toggle).toHaveAttribute("aria-checked", "false");
    expect(screen.getByText(new RegExp(copy.manualOff))).toBeInTheDocument();
    expect(screen.getByTestId("shell")).toHaveTextContent("manual=false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-checked", "true");
    expect(screen.getByText(new RegExp(copy.manualOn))).toBeInTheDocument();
    expect(screen.getByTestId("shell")).toHaveTextContent("manual=true");
    // il run seguito è già partito: la scelta vale dal prossimo
    expect(screen.getByText(new RegExp(copy.manualNextRun))).toBeInTheDocument();
    expect(screen.getByTestId("shell")).toHaveTextContent("runManual=false");
  });

  it("senza un run non dice «dalla prossima analisi»", async () => {
    renderPanel(runClient().client, <OperationsPanel />, {});
    await screen.findByRole("switch", { name: new RegExp(copy.manualSwitch) });
    expect(screen.queryByText(new RegExp(copy.manualNextRun))).not.toBeInTheDocument();
  });

  const waiting = (): RunView => ({
    ...doneView,
    run: { ...doneView.run, state: "AWAIT" },
    requests: doneView.requests.map((r) =>
      r.request.action_id === "act_002"
        ? ({
            ...r,
            request: { ...r.request, state: "RECEIVED", reject_code: null, reject_reason: null },
          } as RequestView)
        : r,
    ),
  });

  it("solo un run partito con la risposta manuale e una richiesta ricevuta hanno Accetta / Rifiuta", async () => {
    await shown({ view: waiting() }, { runId: RUN, runManual: true });
    expect(within(card("act_002")).getByRole("button", { name: copy.accept })).toBeInTheDocument();
    expect(within(card("act_002")).getByRole("button", { name: copy.reject })).toBeInTheDocument();
    // le altre richieste (non «ricevute») no
    expect(
      within(card("act_001")).queryByRole("button", { name: copy.accept }),
    ).not.toBeInTheDocument();
  });

  it("senza la risposta manuale, una richiesta ricevuta non ha pulsanti", async () => {
    await shown({ view: waiting() }, { runId: RUN, runManual: false });
    expect(screen.queryByRole("button", { name: copy.accept })).not.toBeInTheDocument();
  });

  it("Accetta manda la risposta al dipartimento giusto e rilegge subito il run e le risorse", async () => {
    const made = await shown({ view: waiting() }, { runId: RUN, runManual: true });
    // le risorse del run si leggono quando arriva il run; le letture senza run sono dei nomi dei
    // dipartimenti e del registro che c'è prima del run: si parte da quando le risorse sono assestate
    const resourceReads = () => made.vdeptRegistry.mock.calls.filter(([id]) => id === RUN).length;
    await waitFor(() => expect(resourceReads()).toBe(1));
    const runReads = made.getRun.mock.calls.length;
    const readsBefore = resourceReads();
    fireEvent.click(within(card("act_002")).getByRole("button", { name: copy.accept }));
    await waitFor(() => expect(made.manualResponse).toHaveBeenCalledTimes(1));
    expect(made.manualResponse).toHaveBeenCalledWith("municipal_police", "act_002", {
      decision: "accept",
    });
    // subito, senza aspettare il giro di 1 s del polling: la risposta ha cambiato lo stato e le risorse
    await waitFor(() => expect(made.getRun.mock.calls.length).toBeGreaterThan(runReads), {
      timeout: 500,
    });
    await waitFor(() => expect(resourceReads()).toBeGreaterThan(readsBefore), { timeout: 500 });
  });

  it("dopo una risposta riuscita i pulsanti restano spenti: un secondo clic non parte (la richiesta è già decisa)", async () => {
    const made = await shown({ view: waiting() }, { runId: RUN, runManual: true });
    const accept = within(card("act_002")).getByRole("button", { name: copy.accept });
    fireEvent.click(accept);
    await waitFor(() => expect(made.manualResponse).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(accept).toBeDisabled());
    expect(within(card("act_002")).getByRole("button", { name: copy.reject })).toBeDisabled();
    fireEvent.click(accept);
    expect(made.manualResponse).toHaveBeenCalledTimes(1);
  });

  const waitingBoth = (): RequestView[] =>
    doneView.requests.map((r) =>
      ["act_001", "act_002"].includes(r.request.action_id)
        ? ({
            ...r,
            request: { ...r.request, state: "RECEIVED", reject_code: null, reject_reason: null },
          } as RequestView)
        : r,
    );

  it("con più richieste in attesa «Accetta tutte» le accetta una dopo l'altra, ognuna al suo dipartimento", async () => {
    const view: RunView = {
      ...doneView,
      run: { ...doneView.run, state: "AWAIT" },
      requests: waitingBoth(),
    };
    const made = await shown({ view }, { runId: RUN, runManual: true });
    fireEvent.click(await screen.findByRole("button", { name: copy.acceptAll(2) }));
    await waitFor(() => expect(made.manualResponse).toHaveBeenCalledTimes(2));
    const sent = made.manualResponse.mock.calls.map(([dept, id, body]) => [
      dept,
      id,
      body.decision,
    ]);
    expect(sent).toEqual(
      expect.arrayContaining([
        ["municipal_police", "act_002", "accept"],
        [expect.any(String), "act_001", "accept"],
      ]),
    );
    expect(
      screen.queryByText(/non sono state accettate|non è stata accettata/),
    ).not.toBeInTheDocument();
    // un secondo clic non c'è: il pulsante e quelli delle richieste sono spariti
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /Accetta tutte/ })).not.toBeInTheDocument(),
    );
    expect(screen.queryByRole("button", { name: copy.accept })).not.toBeInTheDocument();
    expect(made.manualResponse).toHaveBeenCalledTimes(2);
  });

  it("«Accetta tutte» non c'è con una sola richiesta in attesa né senza la risposta manuale", async () => {
    await shown({ view: waiting() }, { runId: RUN, runManual: true });
    expect(screen.queryByRole("button", { name: /Accetta tutte/ })).not.toBeInTheDocument();
  });

  it("senza la risposta manuale non ci sono pulsanti di risposta, nemmeno «Accetta tutte»", async () => {
    const view: RunView = {
      ...doneView,
      run: { ...doneView.run, state: "AWAIT" },
      requests: waitingBoth(),
    };
    await shown({ view }, { runId: RUN, runManual: false });
    expect(screen.queryByRole("button", { name: /Accetta tutte/ })).not.toBeInTheDocument();
  });

  it("se il dipartimento non accetta una richiesta, «Accetta tutte» lo dice e le altre sono andate", async () => {
    const view: RunView = {
      ...doneView,
      run: { ...doneView.run, state: "AWAIT" },
      requests: waitingBoth(),
    };
    const made = await shown(
      {
        view,
        overrides: {
          manualResponse: vi.fn((_dept: string, id: string) =>
            id === "act_001"
              ? Promise.reject(new Error("409"))
              : Promise.resolve(view.requests[0] as RequestView),
          ),
        },
      },
      { runId: RUN, runManual: true },
    );
    fireEvent.click(await screen.findByRole("button", { name: copy.acceptAll(2) }));
    expect(await screen.findByText(copy.acceptAllFailed(1))).toBeInTheDocument();
    expect(made.getRun).toHaveBeenCalled();
  });

  it("Rifiuta chiede codice e motivo: senza motivo non parte; poi manda codice e motivo", async () => {
    const made = await shown({ view: waiting() }, { runId: RUN, runManual: true });
    const request = card("act_002");
    fireEvent.click(within(request).getByRole("button", { name: copy.reject }));
    const code = within(request).getByRole("combobox", { name: copy.rejectCode });
    expect(
      within(code)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["UNAVAILABLE"]);
    fireEvent.click(within(request).getByRole("button", { name: copy.confirmReject }));
    expect(within(request).getByText(copy.rejectReasonRequired)).toBeInTheDocument();
    expect(made.manualResponse).not.toHaveBeenCalled();

    fireEvent.change(within(request).getByRole("textbox", { name: copy.rejectReason }), {
      target: { value: "  Nessuna pattuglia libera  " },
    });
    fireEvent.click(within(request).getByRole("button", { name: copy.confirmReject }));
    await waitFor(() => expect(made.manualResponse).toHaveBeenCalledTimes(1));
    expect(made.manualResponse).toHaveBeenCalledWith("municipal_police", "act_002", {
      decision: "reject",
      reject_code: "UNAVAILABLE",
      reject_reason: "Nessuna pattuglia libera",
    });
  });

  it("i codici di rifiuto sono quelli del dipartimento della richiesta", async () => {
    const view = waiting();
    const traffic = {
      ...view,
      requests: view.requests.map((r) =>
        r.request.action_id === "act_004"
          ? ({ ...r, request: { ...r.request, state: "RECEIVED" } } as RequestView)
          : r,
      ),
    };
    await shown({ view: traffic }, { runId: RUN, runManual: true });
    const request = card("act_004");
    fireEvent.click(within(request).getByRole("button", { name: copy.reject }));
    const options = within(
      within(request).getByRole("combobox", { name: copy.rejectCode }),
    ).getAllByRole("option");
    expect(options.map((o) => o.textContent)).toEqual(["LIMIT_REACHED", "CONFLICT_ACTIVE_DETOUR"]);
  });

  it("«Annulla» torna ai due pulsanti senza mandare nulla", async () => {
    const made = await shown({ view: waiting() }, { runId: RUN, runManual: true });
    const request = card("act_002");
    fireEvent.click(within(request).getByRole("button", { name: copy.reject }));
    fireEvent.click(within(request).getByRole("button", { name: copy.cancel }));
    expect(within(request).getByRole("button", { name: copy.accept })).toBeInTheDocument();
    expect(made.manualResponse).not.toHaveBeenCalled();
  });

  it("se l'API rifiuta (409: non più in attesa) lo dice e si può riprovare", async () => {
    const made = runClient({
      view: waiting(),
      overrides: {
        manualResponse: () =>
          Promise.reject(
            new ApiError(409, { code: "CONFLICT", message: "La richiesta non è più in attesa" }),
          ),
      },
    });
    renderPanel(made.client, <OperationsPanel />, { runId: RUN, runManual: true });
    await screen.findByRole("region", { name: copy.plan(5) });
    const request = card("act_002");
    fireEvent.click(within(request).getByRole("button", { name: copy.accept }));
    const alert = await within(request).findByRole("alert");
    expect(alert).toHaveTextContent(copy.responseError);
    expect(alert).toHaveTextContent("La richiesta non è più in attesa");
    expect(within(request).getByRole("button", { name: copy.accept })).toBeEnabled();
  });
});

describe("OperationsPanel: decisione umana", () => {
  it("una misura che aspetta una persona è in evidenza, con la sua nota", async () => {
    const view = fixture<RunView>("run_view_variant_human_decision.json");
    await shown({ view });
    const alert = screen.getByText(copy.decisionTitle).closest("div") as HTMLElement;
    const item = view.plan.find((p) => p.status === "human_decision_required");
    expect(alert).toHaveTextContent((item?.note ?? item?.recommendation.rationale) as string);
    expect(screen.getAllByText(copy.planStatus.human_decision_required).length).toBeGreaterThan(0);
  });

  it("senza misure in attesa non c'è il riquadro", async () => {
    await shown();
    expect(screen.queryByText(copy.decisionTitle)).not.toBeInTheDocument();
  });

  it("con la decisione richiesta le richieste stanno subito sotto il riquadro (schermata 09)", async () => {
    const fixed = fixture<RunView>("run_view_variant_human_decision.json");
    // a run finito l'ordine di partenza ha le richieste dopo il piano: la decisione le porta su
    const view = { ...fixed, run: { ...fixed.run, state: "DONE" as const } };
    await shown({ view });
    const alert = screen.getByText(copy.decisionTitle).closest("div") as HTMLElement;
    const requests = screen.getByRole("heading", { name: copy.requests });
    expect(alert.compareDocumentPosition(requests) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // e prima del piano e del confronto
    const plan = screen.getByRole("heading", {
      name: new RegExp(`^${copy.plan(1).split(" ")[0]}`),
    });
    expect(requests.compareDocumentPosition(plan) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});

describe("OperationsPanel: confronto tra iterazioni", () => {
  it("ha lo stesso aspetto del registro (`.nuo-log`): contenitore, intestazione in grassetto, riga con linea", async () => {
    await shown();
    const table = await screen.findByRole("table");
    expect(table.parentElement).toHaveClass("rounded-card-inner", "bg-surface-2");
    expect(table.querySelector("thead tr")).toHaveClass("border-border-strong");
    expect(within(table).getAllByRole("columnheader")[0]).toHaveClass("font-semibold");
    const row = table.querySelector("tbody tr") as HTMLElement;
    expect(row).toHaveClass("hover:bg-row-hover");
    expect(within(row).getAllByRole("rowheader")[0]).toHaveClass("before:bg-accent");
  });

  it("una colonna per iterazione (Prima, poi i numeri della barra) e la variazione dell'ultima", async () => {
    await shown();
    const table = within(await screen.findByRole("table"));
    expect(table.getAllByRole("columnheader").map((h) => h.textContent)).toEqual([
      copy.comparisonMetric,
      copy.before,
      copy.iteration(2),
      copy.iteration(3),
      copy.comparisonDelta,
    ]);
    expect(table.getAllByRole("rowheader").map((h) => h.textContent)).toEqual([
      expect.stringContaining(strings.metrics.cards.vehicleHours),
      expect.stringContaining(strings.metrics.cards.odTime),
      expect.stringContaining(strings.metrics.cards.criticalEdges),
      expect.stringContaining(strings.metrics.cards.transitLoad),
    ]);
  });

  it("le unità lunghe stanno sotto il nome della metrica, non in ogni cella; quelle corte accanto al numero", async () => {
    await shown();
    const hours = (
      await screen.findByRole("rowheader", { name: new RegExp(strings.metrics.cards.vehicleHours) })
    ).closest("tr") as HTMLElement;
    expect(within(hours).getByRole("rowheader")).toHaveTextContent("ore-veicolo");
    for (const cell of within(hours).getAllByRole("cell"))
      expect(cell.textContent).not.toContain("ore-veicolo");
    const odTime = (
      await screen.findByRole("rowheader", { name: new RegExp(`^${strings.metrics.cards.odTime}`) })
    ).closest("tr") as HTMLElement;
    expect(within(odTime).getAllByRole("cell")[0]).toHaveTextContent("min");
  });

  it("il badge sta su una riga sua, sotto il nome", async () => {
    await shown();
    const odTime = (await screen.findByRole("rowheader", {
      name: new RegExp(`^${strings.metrics.cards.odTime}`),
    })) as HTMLElement;
    const badge = odTime.querySelector("[data-kind]") as HTMLElement;
    expect(badge.parentElement).toHaveClass("block"); // «min» è corta: senza questo il badge starebbe accanto al nome
  });

  it("i segnaposto «—» non sono in text-muted (contrasto 3,3:1, design D7): solo testo secondario", async () => {
    const made = runClient({
      view: withRun({ state: "VERIFY" }),
      overrides: {
        runMetrics: (_id, n) =>
          Promise.resolve({
            ...metrics(n),
            // senza la variazione né le metriche della prima iterazione: celle vuote
            metrics: n === 0 ? [] : metrics(n).metrics,
            deltas: [],
          }),
      },
    });
    renderPanel(made.client, <OperationsPanel />);
    const table = within(await screen.findByRole("table"));
    const dashes = table.getAllByText("—");
    expect(dashes.length).toBeGreaterThan(0);
    for (const dash of dashes) {
      expect(dash).toHaveClass("text-text-secondary");
      expect(dash).not.toHaveClass("text-text-muted");
    }
  });

  it("sotto il nome di ogni metrica c'è il badge della natura del dato (design, schermata 08)", async () => {
    await shown();
    const rows = within(await screen.findByRole("table")).getAllByRole("rowheader");
    const kinds = rows.map((header) =>
      header.querySelector("[data-kind]")?.getAttribute("data-kind"),
    );
    const expected = [
      "road.departure.veh_hours",
      "road.departure.od_time.mean",
      "road.departure.critical_edges.count",
      "transit.departure.max_section_load.metro_line_1",
    ].map((name) => metrics(2).metrics.find((m) => m.id.endsWith(name))?.kind);
    expect(kinds).toEqual(expected);
    expect(kinds.every(Boolean)).toBe(true);
  });

  it("i valori sono quelli delle metriche e la variazione quella del backend (non ricalcolata)", async () => {
    await shown();
    const row = (
      await screen.findByRole("rowheader", { name: new RegExp(strings.metrics.cards.vehicleHours) })
    ).closest("tr") as HTMLElement;
    const cells = within(row).getAllByRole("cell");
    const hours = (n: number) =>
      metrics(n).metrics.find((m) => m.id.endsWith("road.departure.veh_hours"))?.value as number;
    expect(cells[0]).toHaveTextContent(
      new Intl.NumberFormat("it-IT", { useGrouping: "always" }).format(hours(0)),
    );
    const delta = metrics(2).deltas.find((d) =>
      d.metric_id.endsWith("it2.road.departure.veh_hours"),
    )?.vs_previous;
    expect(cells[3]).toHaveTextContent(formatDelta(delta as { value: number; unit: string }).text);
  });

  it("segue la finestra scelta", async () => {
    await shown({}, { runId: RUN, window: "arrival" });
    const row = (
      await screen.findByRole("rowheader", { name: new RegExp(strings.metrics.cards.vehicleHours) })
    ).closest("tr") as HTMLElement;
    const arrival = metrics(0).metrics.find((m) => m.id.endsWith("road.arrival.veh_hours"))
      ?.value as number;
    expect(within(row).getAllByRole("cell")[0]).toHaveTextContent(
      new Intl.NumberFormat("it-IT", { useGrouping: "always" }).format(arrival),
    );
  });

  it("un run con tre ripianificazioni ha quattro passate, ognuna col suo numero e nessuna chiave doppia", async () => {
    // il run vero può arrivare all'iterazione 3 (MAX_REPLANS): «Iterazione 3» non può nominarne due
    const warn = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const made = runClient({
      view: withRun({ state: "DONE", iteration: 3, replans: 3 }),
      overrides: { runMetrics: (_id, n) => Promise.resolve(metrics(Math.min(n, 2))) },
    });
    renderPanel(made.client, <OperationsPanel />);
    const table = within(await screen.findByRole("table"));
    await waitFor(() => expect(table.getAllByRole("columnheader")).toHaveLength(6));
    expect(table.getAllByRole("columnheader").map((h) => h.textContent)).toEqual([
      copy.comparisonMetric,
      copy.before,
      copy.iteration(2),
      copy.iteration(3),
      copy.iteration(4),
      copy.comparisonDelta,
    ]);
    expect(warn.mock.calls.flat().join(" ")).not.toMatch(/same key/);
    warn.mockRestore();
  });

  it("se le metriche dell'ultima iterazione non ci sono ancora, la colonna non c'è e la variazione è quella dell'ultima che c'è", async () => {
    // il run è all'iterazione 2, ma le sue metriche arrivano dopo (404)
    const made = runClient({
      view: withRun({ state: "VERIFY", iteration: 2 }),
      overrides: {
        runMetrics: (_id, n) =>
          n <= 1
            ? Promise.resolve(metrics(n))
            : Promise.reject(new ApiError(404, { code: "NOT_FOUND", message: "non ancora" })),
      },
    });
    renderPanel(made.client, <OperationsPanel />);
    const table = within(await screen.findByRole("table"));
    expect(table.getAllByRole("columnheader").map((h) => h.textContent)).toEqual([
      copy.comparisonMetric,
      copy.before,
      copy.iteration(2),
      copy.comparisonDelta,
    ]);
    // le quattro righe ci sono, con la variazione dell'iterazione 1 (backend)
    expect(table.getAllByRole("rowheader")).toHaveLength(4);
    const row = table.getAllByRole("rowheader")[0]?.closest("tr") as HTMLElement;
    const delta = metrics(1).deltas.find((d) =>
      d.metric_id.endsWith("road.departure.veh_hours"),
    )?.vs_previous;
    expect(within(row).getAllByRole("cell").at(-1)).toHaveTextContent(
      formatDelta(delta as { value: number; unit: string }).text,
    );
  });

  it("con una sola iterazione non c'è il confronto", async () => {
    const made = runClient({ view: withRun({ iteration: 0, state: "PLAN" }) });
    renderPanel(made.client, <OperationsPanel />);
    await screen.findByRole("region", { name: copy.plan(5) });
    await waitFor(() => expect(made.runMetrics).toHaveBeenCalled());
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});

describe("OperationsPanel: l'ordine segue la fase del run", () => {
  const headings = () =>
    screen
      .getAllByRole("heading", { level: 3 })
      .map((h) => h.textContent as string)
      .map((text) =>
        text.startsWith("Piano")
          ? "plan"
          : text === copy.departments
            ? "departments"
            : text === copy.requests
              ? "requests"
              : text === copy.comparison
                ? "comparison"
                : text,
      );

  async function inState(state: RunView["run"]["state"]) {
    const made = runClient({ view: withRun({ state }) });
    renderPanel(made.client, <OperationsPanel />);
    await screen.findByRole("region", { name: copy.plan(5) });
    await screen.findByRole("table"); // il confronto arriva con le metriche
    await waitFor(() => expect(screen.getAllByRole("heading", { level: 3 })).toHaveLength(4));
  }

  it("mentre si pianifica, il piano per primo", async () => {
    await inState("PLAN");
    expect(headings()).toEqual(["plan", "departments", "requests", "comparison"]);
  });

  it("mentre si inviano le richieste e si aspettano le risposte, dipartimenti e richieste", async () => {
    await inState("AWAIT");
    expect(headings()).toEqual(["departments", "requests", "plan", "comparison"]);
  });

  it("quando si verifica, il confronto tra le iterazioni", async () => {
    await inState("VERIFY");
    expect(headings()[0]).toBe("comparison");
  });
});

describe("OperationsPanel: senza run", () => {
  it("c'è l'interruttore e «nessuna richiesta»; né piano né dipartimenti né confronto", async () => {
    renderPanel(runClient().client, <OperationsPanel />, {});
    expect(
      await screen.findByRole("switch", { name: new RegExp(copy.manualSwitch) }),
    ).toBeInTheDocument();
    expect(screen.getByText(copy.noRequests)).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: copy.departments })).not.toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByText(/^Piano —/)).not.toBeInTheDocument();
  });
});

describe("OperationsPanel: Comunicazioni (WhatsApp, spech 12.4)", () => {
  const sentRow = fixture<Notification[]>("run_notifications.json")[0] as Notification;
  const row = (changes: Partial<Notification>): Notification => ({ ...sentRow, ...changes });
  // come il server: le notifiche del canale chiesto
  const withNotifications = (rows: Notification[]) => ({
    overrides: {
      runNotifications: vi.fn((_runId: string, channel?: Notification["channel"]) =>
        Promise.resolve(channel ? rows.filter((row) => row.channel === channel) : rows),
      ),
    },
  });

  it("una riga di stato: «WhatsApp · inviato a +39 *** *** **12 · ora»", async () => {
    await shown(withNotifications([sentRow]));
    const line = await within(
      await screen.findByRole("region", { name: copy.communications }),
    ).findByText(/WhatsApp/);
    expect(line).toHaveTextContent(
      `WhatsApp · inviato a +39 *** *** **12 · ${formatClock(sentRow.created_at)}`,
    );
    expect(line).toHaveAttribute("data-state", "SENT");
  });

  it("nessuna anteprima del testo e nessun pulsante di invio", async () => {
    await shown(withNotifications([sentRow]));
    const box = within(await screen.findByRole("region", { name: copy.communications }));
    await box.findByText(/WhatsApp/);
    expect(box.queryByRole("button")).toBeNull();
    expect(box.queryByText(/Sentrix — Avviso viabilità/)).toBeNull(); // il testo non si mostra
    expect(box.queryByText(/Via Francesco Caracciolo/)).toBeNull();
  });

  it.each([
    ["mode_off", "invio disattivato"],
    ["not_configured", "chiavi mancanti"],
    ["daily_limit", "tetto giornaliero raggiunto"],
    ["unreachable", "servizio non raggiungibile"],
    ["rejected", "rifiutato dal servizio"],
  ])("non inviato (%s): «non inviato: %s»", async (code, reason) => {
    const state = code === "unreachable" || code === "rejected" ? "FAILED" : "SKIPPED";
    await shown(withNotifications([row({ state, error_code: code, recipient_label: null })]));
    const line = await within(
      await screen.findByRole("region", { name: copy.communications }),
    ).findByText(/WhatsApp/);
    expect(line).toHaveTextContent(`WhatsApp · non inviato: ${reason}`);
    expect(line).toHaveAttribute("data-state", state);
  });

  it("un codice sconosciuto non rompe la riga", async () => {
    await shown(withNotifications([row({ state: "FAILED", error_code: "nuovo_codice" })]));
    const line = await within(
      await screen.findByRole("region", { name: copy.communications }),
    ).findByText(/WhatsApp/);
    expect(line).toHaveTextContent(`non inviato: ${copy.whatsapp.unknownReason}`);
  });

  it("senza notifiche la sezione non c'è", async () => {
    const none = withNotifications([]);
    await shown(none);
    await waitFor(() => expect(none.overrides.runNotifications).toHaveBeenCalled());
    expect(screen.queryByRole("region", { name: copy.communications })).toBeNull();
  });

  it("si chiede solo dopo DONE, solo per WhatsApp e per quel run", async () => {
    const running = withNotifications([sentRow]);
    const { client } = runClient({
      view: withRun({ state: "VERIFY", ended_at: null }),
      overrides: running.overrides,
    });
    renderPanel(client, <OperationsPanel />);
    await screen.findByRole("region", { name: copy.plan(5) });
    expect(running.overrides.runNotifications).not.toHaveBeenCalled();

    const finished = withNotifications([sentRow]);
    await shown(finished);
    await waitFor(() => expect(finished.overrides.runNotifications).toHaveBeenCalledTimes(2));
    expect(finished.overrides.runNotifications).toHaveBeenCalledWith(RUN, "whatsapp");
    expect(finished.overrides.runNotifications).toHaveBeenCalledWith(RUN, "emergency_bulletin");
  });
});

describe("notificationPollInterval: quanto si aspetta il messaggio", () => {
  const ended = Date.parse("2026-11-14T16:40:00+01:00");
  it("rilegge ogni 2 s finché non c'è, per al più 45 s dalla fine del run", () => {
    expect(notificationPollInterval(false, ended, ended + 1_000)).toBe(NOTIFICATION_POLL_MS);
    expect(notificationPollInterval(false, ended, ended + NOTIFICATION_WAIT_MS - 1)).toBe(
      NOTIFICATION_POLL_MS,
    );
    expect(notificationPollInterval(false, ended, ended + NOTIFICATION_WAIT_MS)).toBe(false);
  });
  it("si ferma appena c'è, e non insiste su un run finito da tempo o senza fine", () => {
    expect(notificationPollInterval(true, ended, ended + 1_000)).toBe(false);
    expect(notificationPollInterval(false, ended, ended + 3_600_000)).toBe(false);
    expect(notificationPollInterval(false, Number.NaN, ended)).toBe(false);
  });
});

describe("OperationsPanel: Servizi di emergenza (bollettino simulato, spech 12.3)", () => {
  const all = fixture<Notification[]>("run_notifications.json");
  const bulletins = all.filter((row) => row.channel === "emergency_bulletin");
  const emergency = copy.emergency;

  /** Un server finto con lo stato dei bollettini: la conferma li cambia, la lista si rilegge. */
  function liveBulletins(rows: Notification[] = all) {
    const state = new Map(rows.map((row) => [row.id, row.state]));
    const current = () => rows.map((row) => ({ ...row, state: state.get(row.id) ?? row.state }));
    const ackNotification = vi.fn((id: number) => {
      state.set(id, "ACKNOWLEDGED");
      return Promise.resolve(current().find((row) => row.id === id) as Notification);
    });
    const runNotifications = vi.fn((_runId: string, channel?: Notification["channel"]) =>
      Promise.resolve(current().filter((row) => !channel || row.channel === channel)),
    );
    return { overrides: { runNotifications, ackNotification }, ackNotification, runNotifications };
  }

  const panel = () => screen.findByRole("region", { name: emergency.title });
  const cardOf = async (name: string) => within(await panel()).findByRole("group", { name });

  it("una scheda per destinatario, nella sezione con il badge SIMULATO e la nota", async () => {
    await shown(liveBulletins());
    const region = within(await panel());
    expect(region.getByText(emergency.note)).toBeInTheDocument();
    expect(region.getAllByRole("group")).toHaveLength(8);
    for (const bulletin of bulletins) {
      expect(region.getByRole("group", { name: bulletin.recipient_label as string })).toBeVisible();
    }
    expect(panelBadge(await panel())).toHaveAttribute("data-kind", "simulated");
  });

  it("ogni scheda dice lo stato e l'ora; il testo è chiuso finché non lo si apre", async () => {
    await shown(liveBulletins());
    const questura = within(await cardOf("Questura di Napoli (sala operativa)"));
    expect(questura.getByText(emergency.state.DELIVERED as string)).toBeInTheDocument();
    expect(
      questura.getByText(emergency.sentAt(formatClock(bulletins[0]?.created_at as string))),
    ).toBeInTheDocument();
    expect(questura.queryByText(/BOLLETTINO VIABILITÀ/)).toBeNull();
    const toggle = questura.getByRole("button", { name: emergency.showText });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(questura.getByText(/BOLLETTINO VIABILITÀ — SIMULATO/)).toBeInTheDocument();
    expect(questura.getByRole("button", { name: emergency.hideText })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    fireEvent.click(questura.getByRole("button", { name: emergency.hideText }));
    expect(questura.queryByText(/BOLLETTINO VIABILITÀ/)).toBeNull();
  });

  it("«Conferma ricezione» conferma quel bollettino e solo quello; poi il pulsante sparisce", async () => {
    const made = liveBulletins();
    await shown(made);
    expect(
      within(await panel()).getAllByRole("button", { name: emergency.acknowledge }),
    ).toHaveLength(8);
    const target = bulletins[2] as Notification;
    const card = within(await cardOf(target.recipient_label as string));
    fireEvent.click(card.getByRole("button", { name: emergency.acknowledge }));
    await waitFor(() => expect(made.ackNotification).toHaveBeenCalledWith(target.id));
    expect(made.ackNotification).toHaveBeenCalledTimes(1);
    await waitFor(() =>
      expect(card.getByText(emergency.state.ACKNOWLEDGED as string)).toBeInTheDocument(),
    );
    expect(card.queryByRole("button", { name: emergency.acknowledge })).toBeNull();
    expect(
      within(await panel()).getAllByRole("button", { name: emergency.acknowledge }),
    ).toHaveLength(7);
  });

  it("un bollettino già confermato non ha il pulsante", async () => {
    const rows = all.map((row) =>
      row.id === bulletins[0]?.id ? { ...row, state: "ACKNOWLEDGED" as const } : row,
    );
    await shown(liveBulletins(rows));
    const card = within(await cardOf(bulletins[0]?.recipient_label as string));
    expect(card.getByText(emergency.state.ACKNOWLEDGED as string)).toBeInTheDocument();
    expect(card.queryByRole("button", { name: emergency.acknowledge })).toBeNull();
  });

  it("se la conferma non riesce lo dice e il pulsante resta; un 409 (già confermato) non è un errore", async () => {
    const made = liveBulletins();
    made.ackNotification.mockRejectedValueOnce(
      new ApiError(500, { code: "X", message: "no", details: {} }),
    );
    await shown(made);
    const card = within(await cardOf(bulletins[0]?.recipient_label as string));
    fireEvent.click(card.getByRole("button", { name: emergency.acknowledge }));
    expect(await card.findByRole("alert")).toHaveTextContent(emergency.acknowledgeFailed);
    expect(card.getByRole("button", { name: emergency.acknowledge })).toBeEnabled();

    made.ackNotification.mockRejectedValueOnce(
      new ApiError(409, {
        code: "NOT_ACKNOWLEDGEABLE",
        message: "già",
        details: { state: "ACKNOWLEDGED" },
      }),
    );
    const other = within(await cardOf(bulletins[1]?.recipient_label as string));
    fireEvent.click(other.getByRole("button", { name: emergency.acknowledge }));
    await waitFor(() => expect(made.ackNotification).toHaveBeenCalledTimes(2));
    expect(other.queryByRole("alert")).toBeNull();
  });

  it("senza bollettini la sezione non c'è, e prima di DONE non si chiede nulla", async () => {
    const none = liveBulletins(all.filter((row) => row.channel === "whatsapp"));
    await shown(none);
    await waitFor(() => expect(none.runNotifications).toHaveBeenCalled());
    expect(screen.queryByRole("region", { name: emergency.title })).toBeNull();

    const running = liveBulletins();
    const { client } = runClient({
      view: withRun({ state: "VERIFY", ended_at: null }),
      overrides: running.overrides,
    });
    renderPanel(client, <OperationsPanel />);
    await screen.findByRole("region", { name: copy.plan(5) });
    expect(running.runNotifications).not.toHaveBeenCalled();
  });

  it("i bollettini vengono prima della riga WhatsApp, in fondo alla scheda", async () => {
    await shown(liveBulletins());
    const emergencyRegion = await panel();
    const whatsappRegion = await screen.findByRole("region", { name: copy.communications });
    expect(
      emergencyRegion.compareDocumentPosition(whatsappRegion) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });
});

const panelBadge = (region: HTMLElement) => region.querySelector("[data-kind]") as HTMLElement;
