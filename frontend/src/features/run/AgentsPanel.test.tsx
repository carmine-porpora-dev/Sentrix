import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { RunView } from "@/api/types";
import { AgentsPanel } from "@/features/run/AgentsPanel";
import { strings } from "@/i18n/it";
import { fixture } from "@/test/fixtures";
import { doneView, metrics, renderPanel, runClient, RUN, withRun } from "@/test/runPanels";

const copy = strings.panels.agents;
const agent = (name: string) => screen.getByText(name).closest("li") as HTMLElement;

describe("AgentsPanel: senza run", () => {
  it("dice che non c'è un run e mostra i quattro agenti in attesa", () => {
    renderPanel(runClient().client, <AgentsPanel />, {});
    expect(screen.getByRole("heading", { name: copy.title })).toBeInTheDocument();
    expect(screen.getByText(copy.noRun)).toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    for (const name of Object.values(copy.names)) {
      expect(within(agent(name)).getByText(copy.states.waiting)).toBeInTheDocument();
    }
  });
});

describe("AgentsPanel: run finito", () => {
  async function shown() {
    const made = runClient();
    renderPanel(made.client, <AgentsPanel />);
    await screen.findByText(copy.states.done_fallback);
    return made;
  }

  it("mostra lo stato del run con la barra a nove tappe", async () => {
    await shown();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "9");
    expect(screen.getByTitle("DONE")).toHaveTextContent(strings.shell.runStates.DONE);
  });

  it("ogni agente ha il suo stato: «con testo di riserva» per quello che l'ha usato", async () => {
    await shown();
    expect(within(agent(copy.names.event_demand)).getByText(copy.states.done)).toBeInTheDocument();
    expect(within(agent(copy.names.traffic)).getByText(copy.states.done)).toBeInTheDocument();
    expect(
      within(agent(copy.names.transit)).getByText(copy.states.done_fallback),
    ).toBeInTheDocument();
    expect(within(agent(copy.names.operations)).getByText(copy.states.done)).toBeInTheDocument();
  });

  it("il testo dell'agente e la sua origine (LLM, cache, testo di riserva)", async () => {
    await shown();
    const text = doneView.agents.find((a) => a.agent === "traffic")?.text as string;
    expect(within(agent(copy.names.traffic)).getByText(text)).toBeInTheDocument();
    expect(
      within(agent(copy.names.traffic)).getByText(copy.textOrigin.llm_cache),
    ).toBeInTheDocument();
    expect(
      within(agent(copy.names.transit)).getByText(copy.textOrigin.template),
    ).toBeInTheDocument();
  });

  it("gli strumenti eseguiti", async () => {
    await shown();
    const tools = within(agent(copy.names.event_demand))
      .getAllByRole("listitem")
      .map((li) => li.textContent);
    expect(tools).toEqual(["create_event_context", "build_demand"]);
  });

  it("un agente si comprime e si riapre dal suo titolo", async () => {
    await shown();
    const traffic = agent(copy.names.traffic);
    const toggle = within(traffic).getByRole("button", { name: new RegExp(copy.names.traffic) });
    const text = doneView.agents.find((a) => a.agent === "traffic")?.text as string;
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(within(traffic).queryByText(text)).not.toBeInTheDocument();
    fireEvent.click(toggle);
    expect(within(traffic).getByText(text)).toBeInTheDocument();
  });

  it("le evidenze di un'affermazione: nome della metrica, numero e provenienza, letti dalla metrica", async () => {
    const made = await shown();
    const traffic = agent(copy.names.traffic);
    const finding = doneView.agents.find((a) => a.agent === "traffic")?.findings?.[0];
    expect(within(traffic).getByText(finding?.summary as string)).toBeInTheDocument();
    const name = "road.departure.critical_intersection.1.vc";
    const chip = within(traffic).getByText(name).closest("li") as HTMLElement;
    // il valore della metrica (rapporto → percentuale), con il suo tooltip di provenienza
    const metric = metrics(0).metrics.find((m) => m.id.endsWith(name));
    expect(chip).toHaveTextContent(String(Math.round((metric?.value as number) * 100)));
    expect(within(chip).getByText("%")).toBeInTheDocument();
    expect(chip).toHaveAttribute("title", `m.${RUN}.it0.${name}`);
    // le metriche si chiedono per l'iterazione dell'evidenza, una volta sola
    await waitFor(() => expect(made.runMetrics).toHaveBeenCalledWith(RUN, 0));
    expect(made.runMetrics.mock.calls.filter((c) => c[1] === 0)).toHaveLength(1);
  });

  it("un'evidenza che non è una metrica si mostra col suo id e basta", async () => {
    const view: RunView = {
      ...doneView,
      agents: [
        {
          ...doneView.agents[0],
          agent: "event_demand",
          state: "done",
          findings: [
            {
              summary: "Una chiusura",
              severity: "info",
              window: "departure",
              trigger: "closure",
              evidence_ids: ["18122092-8475097329-0"],
              location: null,
            },
          ],
        },
      ],
    } as RunView;
    renderPanel(runClient({ view }).client, <AgentsPanel />);
    const chip = (await screen.findByText("18122092-8475097329-0")).closest("li") as HTMLElement;
    expect(chip.textContent).toBe("18122092-8475097329-0");
  });

  it("l'evidenza con un luogo si mostra sulla mappa: ogni clic chiede di tornarci", async () => {
    await shown();
    const traffic = agent(copy.names.traffic);
    const buttons = within(traffic).getAllByRole("button", { name: copy.showOnMap });
    expect(buttons).toHaveLength(2);
    fireEvent.click(buttons[0] as HTMLElement);
    expect(screen.getByTestId("shell")).toHaveTextContent("focus=40.8353,14.2449#1");
    fireEvent.click(buttons[0] as HTMLElement);
    expect(screen.getByTestId("shell")).toHaveTextContent("focus=40.8353,14.2449#2");
  });

  it("senza luogo non c'è il pulsante", async () => {
    await shown();
    expect(
      within(agent(copy.names.event_demand)).queryByRole("button", { name: copy.showOnMap }),
    ).not.toBeInTheDocument();
  });

  it("la gravità si dice in parole (non solo il colore)", async () => {
    await shown();
    const traffic = agent(copy.names.traffic);
    expect(within(traffic).getByRole("img", { name: copy.severity.critical })).toBeInTheDocument();
    expect(
      within(traffic).getAllByRole("img", { name: copy.severity.warning }).length,
    ).toBeGreaterThan(0);
  });
});

describe("AgentsPanel: stati particolari", () => {
  it("un agente in esecuzione e uno in attesa, durante l'analisi", async () => {
    const view = fixture<RunView>("run_view/step_01_analyze_event_demand.json");
    renderPanel(runClient({ view }).client, <AgentsPanel />);
    await screen.findByText(strings.shell.runStates.ANALYZE);
    const states = Object.values(copy.names).map(
      (name) => within(agent(name)).getByText(/.+/, { selector: "span.text-xs" }).textContent,
    );
    expect(states).toContain(copy.states.running);
    expect(states).toContain(copy.states.waiting);
  });

  it("le fonti degradate si dicono, con il loro nome", async () => {
    const view = fixture<RunView>("run_view_variant_degraded.json");
    renderPanel(runClient({ view }).client, <AgentsPanel />);
    expect(await screen.findByText(copy.degradedTitle)).toBeInTheDocument();
    expect(screen.getByText(copy.sources.gtfs)).toBeInTheDocument();
  });

  it("quando l'LLM non ha risposto il run lo dice in parole, non con il codice (`llm_fallback`)", async () => {
    const view = {
      ...fixture<RunView>("run_view_variant_degraded.json"),
      degraded: ["llm_fallback"],
    };
    renderPanel(runClient({ view }).client, <AgentsPanel />);
    expect(await screen.findByText(copy.sources.llm_fallback)).toBeInTheDocument();
    expect(screen.queryByText("llm_fallback")).not.toBeInTheDocument();
  });

  it("una fonte che l'interfaccia non conosce resta com'è, non sparisce", async () => {
    const view = {
      ...fixture<RunView>("run_view_variant_degraded.json"),
      degraded: ["nuova_fonte"],
    };
    renderPanel(runClient({ view }).client, <AgentsPanel />);
    expect(await screen.findByText("nuova_fonte")).toBeInTheDocument();
  });

  it("senza fonti degradate non c'è l'avviso", async () => {
    renderPanel(runClient().client, <AgentsPanel />);
    await screen.findByText(copy.states.done_fallback);
    expect(screen.queryByText(copy.degradedTitle)).not.toBeInTheDocument();
  });

  it("un run in errore dice che cosa è successo e come riprovare, e il chip è «Errore»", async () => {
    const view = fixture<RunView>("run_view_variant_error.json");
    renderPanel(runClient({ view }).client, <AgentsPanel />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(copy.errorTitle);
    expect(alert).toHaveTextContent(view.run.error as string);
    expect(alert).toHaveTextContent(copy.errorHint);
    expect(screen.getByText(strings.shell.runStates.ERROR)).toBeInTheDocument();
  });

  it("una misura che aspetta una persona rende «Decisione richiesta» lo stato mostrato", async () => {
    const view = fixture<RunView>("run_view_variant_human_decision.json");
    renderPanel(runClient({ view }).client, <AgentsPanel />);
    expect(await screen.findByText(strings.shell.runStates.DECISION_REQUIRED)).toBeInTheDocument();
  });

  it("un run in errore senza messaggio dice comunque che si è interrotto e come riprovare", async () => {
    const view = withRun({ state: "ERROR", error: null });
    renderPanel(runClient({ view }).client, <AgentsPanel />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(copy.errorTitle);
    expect(alert).toHaveTextContent(copy.errorHint);
  });

  it("un messaggio d'errore su un run che non è in errore non apre il riquadro", async () => {
    renderPanel(
      runClient({ view: withRun({ state: "VERIFY", error: "un avviso" }) }).client,
      <AgentsPanel />,
    );
    await screen.findByText(strings.shell.runStates.VERIFY);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("i quattro agenti nell'ordine fisso: Event & Demand, Traffic, Transit, Operations", async () => {
    renderPanel(runClient().client, <AgentsPanel />);
    await screen.findByText(copy.states.done_fallback);
    const names = within(screen.getByRole("list", { name: copy.title }))
      .getAllByRole("listitem")
      .map((li) => li.querySelector("span.font-semibold")?.textContent)
      .filter(Boolean);
    expect(names.slice(0, 4)).toEqual(Object.values(copy.names));
  });

  it("un'origine del testo che il pannello non conosce si legge com'è", async () => {
    const view = {
      ...doneView,
      agents: [{ ...doneView.agents[0], text_origin: "nuova_origine" }],
    } as unknown as RunView;
    renderPanel(runClient({ view }).client, <AgentsPanel />);
    expect(await screen.findByText("nuova_origine")).toBeInTheDocument();
  });

  it("un run senza errore non ha il riquadro dell'errore", async () => {
    renderPanel(runClient({ view: withRun({ state: "VERIFY" }) }).client, <AgentsPanel />);
    await screen.findByText(strings.shell.runStates.VERIFY);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
