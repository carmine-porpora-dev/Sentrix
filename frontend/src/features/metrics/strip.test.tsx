import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ApiClient } from "@/api/client";
import { ApiError } from "@/api/errors";
import { createMockClient } from "@/api/mock";
import { ApiProvider } from "@/api/provider";
import type { Event, MetricsResponse, Run, RunView } from "@/api/types";
import { MetricStrip } from "@/features/metrics/MetricStrip";
import { AppShell } from "@/features/shell/AppShell";
import { ShellProvider, type EventWindow } from "@/features/shell/ShellProvider";
import { fixture } from "@/test/fixtures";

const RUN = "run_mock_match_2027";
const done = fixture<RunView>("run_view/step_13_done.json");

interface Options {
  run?: Partial<Run>;
  available?: number[];
  failMetrics?: ApiError;
  failEvent?: boolean;
  event?: Partial<Event>;
}

function stripClient({ run, available = [0, 1, 2], failMetrics, failEvent, event }: Options = {}) {
  const view: RunView = { ...done, run: { ...done.run, ...run } };
  const client: ApiClient = {
    ...createMockClient({ authenticated: true }),
    getRun: () => Promise.resolve(view),
    getEvent: () =>
      failEvent
        ? Promise.reject(new ApiError(500, { code: "INTERNAL", message: "x" }))
        : Promise.resolve({ ...fixture<Event>("event_match_2027.json"), ...event }),
    runMetrics: vi.fn((_id: string, iteration: number) => {
      if (failMetrics) return Promise.reject(failMetrics);
      return available.includes(iteration)
        ? Promise.resolve(fixture<MetricsResponse>(`run_metrics/iteration_${iteration}.json`))
        : Promise.reject(new ApiError(404, { code: "NOT_FOUND", message: "non ancora" }));
    }),
  };
  return client;
}

function renderStrip(
  client: ApiClient,
  initial: { runId?: string; window?: EventWindow } = { runId: RUN },
) {
  return render(
    <ApiProvider client={client}>
      <ShellProvider initial={initial}>
        <div data-testid="strip">
          <MetricStrip />
        </div>
      </ShellProvider>
    </ApiProvider>,
  );
}

/** La scheda di una metrica, per etichetta (l'intestazione che comincia con quel testo). */
function card(label: string): HTMLElement {
  const heading = Array.from(document.querySelectorAll("div.truncate")).find((node) =>
    node.textContent?.startsWith(label),
  );
  if (!heading) throw new Error(`nessuna scheda «${label}»`);
  return heading.closest("div.rounded-card") as HTMLElement;
}
const LABELS = [
  "Ore-veicolo",
  "Tempo O/D medio",
  "Archi critici",
  "Carico TPL massimo",
  "Affluenza ipotizzata",
];

async function ready() {
  await waitFor(() => expect(card("Ore-veicolo")).not.toHaveAttribute("aria-busy"));
  await waitFor(() =>
    expect(within(card("Ore-veicolo")).getByText("SIMULATO")).toBeInTheDocument(),
  );
}

describe("la fascia delle cinque card", () => {
  it("ha le cinque card scelte, nell'ordine", async () => {
    renderStrip(stripClient());
    await ready();
    const labels = Array.from(screen.getByTestId("strip").children).map(
      (c) => c.firstElementChild?.textContent,
    );
    expect(labels).toEqual([
      "Ore-veicolo",
      "Tempo O/D medio",
      "Archi critici",
      "Carico TPL massimo · Linea 1",
      "Affluenza ipotizzata",
    ]);
  });

  it("senza un run: cinque card vuote, «Nessuna analisi», nessun numero", () => {
    renderStrip(stripClient(), {});
    LABELS.forEach((label) => {
      expect(within(card(label)).getByLabelText("Non disponibile")).toHaveTextContent("—");
      expect(within(card(label)).getByText("Nessuna analisi")).toBeInTheDocument();
    });
    expect(screen.queryByText(/SIMULATO|STIMA|REALE/)).not.toBeInTheDocument();
  });

  describe("deflusso, a run finito (iterazione 2 contro la 0)", () => {
    it("ore-veicolo: prima → dopo e variazione, in verde", async () => {
      renderStrip(stripClient());
      await ready();
      const c = within(card("Ore-veicolo"));
      expect(c.getByText("4.820")).toBeInTheDocument();
      expect(c.getByText("4.690")).toBeInTheDocument();
      expect(c.getByText("ore-veicolo")).toBeInTheDocument();
      expect(c.getByText("−130").closest("[data-tone]")).toHaveAttribute("data-tone", "better");
      expect(c.getByText("SIMULATO")).toBeInTheDocument();
    });

    it("tempo O/D medio", async () => {
      renderStrip(stripClient());
      await ready();
      const c = within(card("Tempo O/D medio"));
      expect(c.getByText("38,4")).toBeInTheDocument();
      expect(c.getByText("36,2")).toBeInTheDocument();
      expect(c.getByText("−2,2")).toBeInTheDocument();
      expect(c.getAllByText("min")).toHaveLength(2);
    });

    it("archi critici: il numero e i km, con la variazione del numero", async () => {
      renderStrip(stripClient());
      await ready();
      const c = within(card("Archi critici"));
      expect(c.getByText("6")).toBeInTheDocument();
      expect(c.getByText("3")).toBeInTheDocument();
      expect(c.getByText("2,2")).toBeInTheDocument();
      expect(c.getByText("km")).toBeInTheDocument();
      expect(c.getByText("−3").closest("[data-tone]")).toHaveAttribute("data-tone", "better");
    });

    it("carico TPL massimo: la linea più carica, in percentuale, STIMA, variazione in pp", async () => {
      renderStrip(stripClient());
      await ready();
      const c = within(card("Carico TPL massimo"));
      expect(card("Carico TPL massimo")).toHaveTextContent("Carico TPL massimo · Linea 1");
      expect(c.getAllByText("112")).toHaveLength(2);
      expect(c.getByText("%")).toBeInTheDocument();
      expect(c.getByText("STIMA")).toBeInTheDocument();
      expect(c.getByText("pp")).toBeInTheDocument();
      // 0 pp: nessuna variazione, neutra
      expect(c.getByText("0").closest("[data-tone]")).toHaveAttribute("data-tone", "neutral");
    });

    it("affluenza ipotizzata: dall'Evento, SIMULATO, senza variazione", async () => {
      renderStrip(stripClient());
      await ready();
      const c = within(card("Affluenza ipotizzata"));
      await waitFor(() => expect(c.getByText("150.000")).toBeInTheDocument());
      expect(c.getByText("persone")).toBeInTheDocument();
      expect(c.getByText("SIMULATO")).toBeInTheDocument();
      expect(card("Affluenza ipotizzata").querySelector("[data-tone]")).toBeNull();
    });
  });

  it("l'affluenza segue il livello del run", async () => {
    renderStrip(stripClient({ run: { attendance_level: "high" } }));
    await waitFor(() =>
      expect(within(card("Affluenza ipotizzata")).getByText("300.000")).toBeInTheDocument(),
    );
  });

  describe("la finestra", () => {
    it("in arrivo sono le metriche dell'arrivo", async () => {
      renderStrip(stripClient(), { runId: RUN, window: "arrival" });
      await ready();
      expect(within(card("Ore-veicolo")).getAllByText("3.210")).toHaveLength(2);
      expect(within(card("Tempo O/D medio")).getAllByText("24,9")).toHaveLength(2);
      expect(within(card("Archi critici")).getByText("2,1")).toBeInTheDocument();
    });

    it("si cambia dal selettore Arrivo | Deflusso della mappa, e le card seguono", async () => {
      render(
        <ApiProvider client={stripClient()}>
          <ShellProvider initial={{ runId: RUN }}>
            <AppShell />
          </ShellProvider>
        </ApiProvider>,
      );
      await waitFor(() =>
        expect(within(card("Ore-veicolo")).getByText("4.690")).toBeInTheDocument(),
      );
      expect(screen.getByRole("radio", { name: "Deflusso" })).toBeChecked();
      fireEvent.click(screen.getByRole("radio", { name: "Arrivo" }));
      expect(screen.getByRole("radio", { name: "Arrivo" })).toBeChecked();
      await waitFor(() =>
        expect(within(card("Ore-veicolo")).getAllByText("3.210")).toHaveLength(2),
      );
      expect(within(card("Ore-veicolo")).queryByText("4.690")).not.toBeInTheDocument();
    });
  });

  describe("l'iterazione", () => {
    it("alla sola iterazione 0 non c'è «prima» né variazione", async () => {
      renderStrip(stripClient({ run: { state: "RECONCILE", iteration: 0 }, available: [0] }));
      await ready();
      const c = within(card("Ore-veicolo"));
      expect(c.getByText("4.820")).toBeInTheDocument();
      expect(c.queryByText("4.690")).not.toBeInTheDocument();
      expect(card("Ore-veicolo").querySelector("[data-tone]")).toBeNull();
    });

    it("alla prima iterazione si confronta con la 0", async () => {
      renderStrip(stripClient({ run: { state: "REPLAN", iteration: 1 }, available: [0, 1] }));
      await ready();
      expect(within(card("Ore-veicolo")).getByText("4.820")).toBeInTheDocument();
      expect(within(card("Ore-veicolo")).getByText("4.760")).toBeInTheDocument(); // iterazione 1
      expect(within(card("Ore-veicolo")).queryByText("4.690")).not.toBeInTheDocument();
    });
  });

  describe("quando i numeri mancano", () => {
    it("run in corso e metriche non ancora prodotte: le quattro del motore in caricamento, l'affluenza c'è", async () => {
      renderStrip(stripClient({ run: { state: "ANALYZE", iteration: 0 }, available: [] }));
      await waitFor(() =>
        expect(within(card("Affluenza ipotizzata")).getByText("150.000")).toBeInTheDocument(),
      );
      for (const label of LABELS.slice(0, 4)) {
        expect(card(label)).toHaveAttribute("aria-busy", "true");
        expect(within(card(label)).getByText("In caricamento…")).toBeInTheDocument();
      }
      expect(card("Affluenza ipotizzata")).not.toHaveAttribute("aria-busy");
    });

    it("run finito senza metriche: «Non disponibile»", async () => {
      renderStrip(stripClient({ available: [] }));
      await waitFor(() =>
        expect(
          within(card("Ore-veicolo")).getByText("Non disponibile", { selector: "[data-kind]" }),
        ).toBeInTheDocument(),
      );
      for (const label of LABELS.slice(0, 4)) {
        expect(card(label)).not.toHaveAttribute("aria-busy");
      }
    });

    it("un guasto del server sulle metriche: «Non disponibile»", async () => {
      renderStrip(
        stripClient({
          run: { state: "PLAN" },
          failMetrics: new ApiError(500, { code: "INTERNAL", message: "x" }),
        }),
      );
      await waitFor(() =>
        expect(
          within(card("Tempo O/D medio")).getByText("Non disponibile", { selector: "[data-kind]" }),
        ).toBeInTheDocument(),
      );
    });

    it("un Evento che non si legge: l'affluenza «Non disponibile», le altre restano", async () => {
      renderStrip(stripClient({ failEvent: true }));
      await waitFor(() =>
        expect(
          within(card("Affluenza ipotizzata")).getByText("Non disponibile", {
            selector: "[data-kind]",
          }),
        ).toBeInTheDocument(),
      );
      await ready();
      expect(within(card("Ore-veicolo")).getByText("4.690")).toBeInTheDocument();
    });

    it("una metrica che l'API non dà: «Non disponibile» per quella, non per le altre", async () => {
      const client = stripClient();
      const base = client.runMetrics;
      client.runMetrics = (id, iteration) =>
        base(id, iteration).then((response) => ({
          ...response,
          metrics: response.metrics.filter((m) => !m.id.includes("road.departure.od_time.mean")),
        }));
      renderStrip(client);
      await waitFor(() =>
        expect(
          within(card("Tempo O/D medio")).getByText("Non disponibile", { selector: "[data-kind]" }),
        ).toBeInTheDocument(),
      );
      expect(within(card("Ore-veicolo")).getByText("4.690")).toBeInTheDocument();
    });

    it("senza metriche del TPL la card del carico è «Non disponibile»", async () => {
      const client = stripClient();
      const base = client.runMetrics;
      client.runMetrics = (id, iteration) =>
        base(id, iteration).then((response) => ({
          ...response,
          metrics: response.metrics.filter((m) => !m.id.includes("max_section_load")),
        }));
      renderStrip(client);
      await waitFor(() =>
        expect(
          within(card("Carico TPL massimo")).getByText("Non disponibile", {
            selector: "[data-kind]",
          }),
        ).toBeInTheDocument(),
      );
    });
  });

  describe("provenienza", () => {
    it("ogni numero della fascia ha il suo tooltip con la fonte", async () => {
      renderStrip(stripClient());
      await ready();
      const anchors = Array.from(
        screen.getByTestId("strip").querySelectorAll<HTMLElement>("[tabindex='0']"),
      );
      // 4 card × (prima, dopo, variazione, badge) + secondo numero degli archi + affluenza (valore e badge)
      expect(anchors.length).toBeGreaterThanOrEqual(4 * 4 + 1 + 2);
      for (const anchor of anchors) {
        fireEvent.focus(anchor);
        const tip = screen.getByRole("tooltip");
        expect(within(tip).getByText("Fonte")).toBeInTheDocument();
        expect(within(tip).getByText("Ora del dato")).toBeInTheDocument();
        fireEvent.blur(anchor);
      }
    });

    it("l'affluenza dichiara l'Evento da cui viene e che è un'ipotesi", async () => {
      renderStrip(stripClient());
      await waitFor(() =>
        expect(within(card("Affluenza ipotizzata")).getByText("150.000")).toBeInTheDocument(),
      );
      fireEvent.focus(
        within(card("Affluenza ipotizzata"))
          .getByText("150.000")
          .closest("[tabindex]") as HTMLElement,
      );
      const tip = screen.getByRole("tooltip");
      expect(tip).toHaveTextContent("Evento match_2027 (revisione 1)");
      expect(within(tip).getByText("SIMULATO")).toBeInTheDocument();
    });

    it("i dati del mock dichiarano di essere di esempio", async () => {
      renderStrip(stripClient());
      await ready();
      fireEvent.focus(
        within(card("Ore-veicolo")).getByText("4.690").closest("[tabindex]") as HTMLElement,
      );
      expect(within(screen.getByRole("tooltip")).getByText(/mock\.fixture/)).toBeInTheDocument();
    });
  });
});
