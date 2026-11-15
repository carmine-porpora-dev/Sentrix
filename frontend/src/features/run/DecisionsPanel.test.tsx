import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/api/errors";
import type { RequestView, RunView } from "@/api/types";
import { DecisionsPanel } from "@/features/run/DecisionsPanel";
import { OperationsPanel } from "@/features/run/OperationsPanel";
import { downloadText } from "@/lib/download";
import { strings } from "@/i18n/it";
import { decisions, doneView, renderPanel, runClient, RUN, withRun } from "@/test/runPanels";

vi.mock("@/lib/download", () => ({ downloadText: vi.fn() }));

const copy = strings.panels.log;

beforeEach(() => {
  vi.mocked(downloadText).mockClear();
});

async function shown(options: Parameters<typeof runClient>[0] = {}) {
  const made = runClient(options);
  renderPanel(made.client, <DecisionsPanel />);
  await screen.findByRole("table");
  return made;
}

describe("DecisionsPanel: il registro", () => {
  it("una riga per decisione, nell'ordine del registro, con ora, attore, decisione e motivo", async () => {
    await shown();
    const rows = screen.getAllByRole("row").slice(1); // senza l'intestazione
    expect(rows).toHaveLength(decisions.length);
    const first = within(rows[0] as HTMLElement);
    expect(first.getByText("10:00")).toBeInTheDocument();
    expect(first.getByText(copy.actors.system)).toBeInTheDocument();
    expect(first.getByText(decisions[0]?.decision as string)).toBeInTheDocument();
    expect(first.getByText(decisions[0]?.rationale as string)).toBeInTheDocument();
    expect(
      rows.map((r) =>
        within(r)
          .getAllByRole("cell")[2]
          ?.textContent?.startsWith(decisions[rows.indexOf(r)]?.decision as string),
      ),
    ).not.toContain(false);
  });

  it("ha l'aspetto di `.nuo-log` del design: contenitore surface-2, intestazione in grassetto, riga con linea a sinistra", async () => {
    await shown();
    const table = screen.getByRole("table");
    expect(table.parentElement).toHaveClass("rounded-card-inner", "bg-surface-2");
    const head = table.querySelector("thead tr") as HTMLElement;
    expect(head).toHaveClass("border-border-strong");
    expect(within(head).getAllByRole("columnheader")[0]).toHaveClass(
      "font-semibold",
      "text-text-secondary",
    );
    const row = table.querySelector("tbody tr") as HTMLElement;
    expect(row).toHaveClass("group", "hover:bg-row-hover");
    // la linea cobalto di 2 px sta sulla prima cella e si accende con il mouse sulla riga
    expect(within(row).getAllByRole("cell")[0]).toHaveClass(
      "before:w-0.5",
      "before:bg-accent",
      "before:opacity-0",
      "group-hover:before:opacity-100",
    );
    // la decisione in grassetto, il motivo in secondario
    expect(within(row).getByText(decisions[0]?.decision as string)).toHaveClass("font-semibold");
  });

  it("l'intestazione: Ora, Attore, Decisione e motivo", async () => {
    await shown();
    expect(screen.getAllByRole("columnheader").map((h) => h.textContent)).toEqual([
      copy.time,
      copy.actor,
      copy.decision,
    ]);
  });

  it("gli attori in parole: sistema, orchestratore, agenti, dipartimenti", async () => {
    await shown();
    const table = within(screen.getByRole("table"));
    expect(table.getAllByText(copy.actors.orchestrator).length).toBeGreaterThan(0);
    expect(table.getByText(copy.actors.event_demand)).toBeInTheDocument();
    expect(table.getAllByText("Polizia Municipale (virtuale)").length).toBeGreaterThan(0);
  });

  it("l'ora è quella di Roma (il registro la scrive con il fuso)", async () => {
    const late = [{ ...decisions[0], at: "2026-11-09T09:05:00+00:00" }] as typeof decisions;
    renderPanel(runClient({ decisions: late }).client, <DecisionsPanel />);
    expect(await screen.findByText("10:05")).toBeInTheDocument();
  });

  it("i riferimenti, con il nome della metrica e l'id intero come suggerimento", async () => {
    await shown();
    const ref = screen.getAllByText("road.departure.critical_intersection.1.vc")[0] as HTMLElement;
    expect(ref).toHaveAttribute("title", `m.${RUN}.it0.road.departure.critical_intersection.1.vc`);
    expect(screen.getAllByText("act_001").length).toBeGreaterThan(0); // una richiesta resta com'è
  });

  it("registro vuoto o senza run: lo dice", async () => {
    renderPanel(runClient({ decisions: [] }).client, <DecisionsPanel />);
    expect(await screen.findByText(copy.empty)).toBeInTheDocument();
    renderPanel(runClient().client, <DecisionsPanel />, {});
    expect(await screen.findByText(copy.noRun)).toBeInTheDocument();
  });

  it("si chiede per il run e si rilegge quando il run cambia", async () => {
    const made = await shown();
    expect(made.runDecisions).toHaveBeenCalledWith(RUN);
    expect(made.runDecisions).toHaveBeenCalledTimes(1);
  });
});

describe("DecisionsPanel: esportazione", () => {
  it("«Esporta JSON» scarica il pacchetto del run", async () => {
    const made = await shown();
    fireEvent.click(screen.getByRole("button", { name: copy.exportJson }));
    await waitFor(() => expect(downloadText).toHaveBeenCalledTimes(1));
    expect(made.exportRun).toHaveBeenCalledWith(RUN);
    const [name, mime, content] = vi.mocked(downloadText).mock.calls[0] as [string, string, string];
    expect(name).toBe(`${RUN}.json`);
    expect(mime).toBe("application/json");
    expect(JSON.parse(content)).toEqual({ run: doneView.run });
    expect(content).toContain('\n  "run"'); // a righe indentate: si legge a occhio
  });

  it("i due CSV: metriche e archi critici, ognuno con la sua richiesta e il suo nome", async () => {
    const made = await shown();
    fireEvent.click(screen.getByRole("button", { name: copy.exportMetrics }));
    await waitFor(() => expect(downloadText).toHaveBeenCalledTimes(1));
    expect(made.exportRunCsv).toHaveBeenLastCalledWith(RUN, "metrics");
    expect(vi.mocked(downloadText).mock.calls[0]).toEqual([
      `${RUN}_metrics.csv`,
      "text/csv",
      "a,b\n1,2\n",
    ]);
    fireEvent.click(screen.getByRole("button", { name: copy.exportEdges }));
    await waitFor(() => expect(downloadText).toHaveBeenCalledTimes(2));
    expect(made.exportRunCsv).toHaveBeenLastCalledWith(RUN, "critical_edges");
    expect(vi.mocked(downloadText).mock.calls[1]?.[0]).toBe(`${RUN}_critical_edges.csv`);
  });

  describe("solo a run finito", () => {
    const buttons = () => [copy.exportJson, copy.exportMetrics, copy.exportEdges];

    it("a run in corso i pulsanti sono spenti e lo dicono; l'API non si chiama", async () => {
      const made = runClient({ view: withRun({ state: "AWAIT", iteration: 0, ended_at: null }) });
      renderPanel(made.client, <DecisionsPanel />);
      await screen.findByRole("table");
      for (const name of buttons()) expect(screen.getByRole("button", { name })).toBeDisabled();
      expect(screen.getByText(copy.exportWhenDone)).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: copy.exportJson }));
      expect(made.exportRun).not.toHaveBeenCalled();
    });

    it("a run finito (DONE) sono accesi e non c'è l'avviso", async () => {
      await shown();
      for (const name of buttons()) expect(screen.getByRole("button", { name })).toBeEnabled();
      expect(screen.queryByText(copy.exportWhenDone)).not.toBeInTheDocument();
    });

    it("un run in errore si esporta: il registro serve proprio allora", async () => {
      renderPanel(
        runClient({ view: withRun({ state: "ERROR", error: "Motore non disponibile" }) }).client,
        <DecisionsPanel />,
      );
      await screen.findByRole("table");
      for (const name of buttons()) expect(screen.getByRole("button", { name })).toBeEnabled();
    });

    it("senza un run i pulsanti sono spenti e l'avviso non c'è (non c'è niente da aspettare)", async () => {
      renderPanel(runClient().client, <DecisionsPanel />, {});
      await screen.findByText(copy.noRun);
      for (const name of buttons()) expect(screen.getByRole("button", { name })).toBeDisabled();
      expect(screen.queryByText(copy.exportWhenDone)).not.toBeInTheDocument();
    });

    it("quando il run finisce i pulsanti si accendono da soli", async () => {
      let view = withRun({ state: "VERIFY", ended_at: null });
      const made = runClient({ view });
      made.getRun.mockImplementation(() => Promise.resolve(view));
      renderPanel(made.client, <DecisionsPanel />);
      await screen.findByRole("table");
      expect(screen.getByRole("button", { name: copy.exportJson })).toBeDisabled();
      view = doneView;
      await waitFor(
        () => expect(screen.getByRole("button", { name: copy.exportJson })).toBeEnabled(),
        { timeout: 3000 },
      );
    });
  });

  it("durante un'esportazione gli altri pulsanti aspettano", async () => {
    let finish: (text: string) => void = () => undefined;
    const exportRunCsv = vi.fn(() => new Promise<string>((resolve) => (finish = resolve)));
    await shown({ overrides: { exportRunCsv } });
    fireEvent.click(screen.getByRole("button", { name: copy.exportMetrics }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: copy.exporting })).toBeDisabled(),
    );
    expect(screen.getByRole("button", { name: copy.exportJson })).toBeDisabled();
    expect(screen.getByRole("button", { name: copy.exportEdges })).toBeDisabled();
    finish("x");
    await waitFor(() =>
      expect(screen.getByRole("button", { name: copy.exportJson })).toBeEnabled(),
    );
    expect(exportRunCsv).toHaveBeenCalledTimes(1);
  });

  it("se l'esportazione fallisce lo dice, non scarica nulla e si può riprovare", async () => {
    await shown({
      overrides: {
        exportRun: () => Promise.reject(new ApiError(500, { code: "INTERNAL", message: "x" })),
      },
    });
    fireEvent.click(screen.getByRole("button", { name: copy.exportJson }));
    expect(await screen.findByRole("alert")).toHaveTextContent(copy.exportError);
    expect(downloadText).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: copy.exportJson })).toBeEnabled();
  });

  it("dopo un errore il riquadro se ne va al tentativo successivo", async () => {
    const exportRun = vi
      .fn()
      .mockRejectedValueOnce(new ApiError(500, { code: "INTERNAL", message: "x" }))
      .mockResolvedValue({ run: doneView.run });
    await shown({ overrides: { exportRun } });
    fireEvent.click(screen.getByRole("button", { name: copy.exportJson }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: copy.exportJson }));
    await waitFor(() => expect(downloadText).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("senza run i pulsanti ci sono ma non rispondono", async () => {
    renderPanel(runClient().client, <DecisionsPanel />, {});
    for (const name of [copy.exportJson, copy.exportMetrics, copy.exportEdges]) {
      expect(screen.getByRole("button", { name })).toBeDisabled();
    }
  });
});

describe("DecisionsPanel: si aggiorna con le richieste", () => {
  it("una risposta manuale rilegge il registro (la risposta vi si scrive)", async () => {
    const view: RunView = {
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
    };
    const made = runClient({ view });
    renderPanel(
      made.client,
      <>
        <OperationsPanel />
        <DecisionsPanel />
      </>,
      { runId: RUN, runManual: true },
    );
    await screen.findByRole("table");
    const before = made.runDecisions.mock.calls.length;
    fireEvent.click(
      within(screen.getByRole("article", { name: "act_002" })).getByRole("button", {
        name: strings.panels.ops.accept,
      }),
    );
    await waitFor(() => expect(made.runDecisions.mock.calls.length).toBeGreaterThan(before));
  });
});
