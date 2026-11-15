import { fireEvent, render, screen, within } from "@testing-library/react";
import { Building2, LayoutDashboard, ScrollText } from "lucide-react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { IterationIndicator } from "@/components/IterationIndicator";
import { ModeSelector, type Mode } from "@/components/ModeSelector";
import { RunStatus } from "@/components/RunStatus";
import { Sidebar } from "@/components/Sidebar";
import { SimulationBanner } from "@/components/SimulationBanner";
import { Tabs } from "@/components/Tabs";
import { WindowToggle, type WindowChoice } from "@/components/WindowToggle";
import { strings } from "@/i18n/it";

const ITEMS = [
  { id: "dashboard", icon: LayoutDashboard, label: "Plancia" },
  { id: "requests", icon: Building2, label: "Richieste" },
  { id: "log", icon: ScrollText, label: "Registro" },
] as const;

describe("Sidebar", () => {
  it("è la navigazione principale: il marchio e le sezioni, quella attiva è la pagina corrente", () => {
    render(<Sidebar items={ITEMS} active="requests" onSelect={() => undefined} />);
    const nav = screen.getByRole("navigation", { name: strings.shell.navLabel });
    expect(within(nav).getByTitle(strings.appName)).toHaveTextContent(strings.shell.brand);
    const buttons = within(nav).getAllByRole("button");
    expect(buttons.map((button) => button.getAttribute("aria-label"))).toEqual([
      "Plancia",
      "Richieste",
      "Registro",
    ]);
    expect(buttons.map((button) => button.getAttribute("aria-current"))).toEqual([
      null,
      "page",
      null,
    ]);
  });

  it("un clic sceglie la sezione", () => {
    const onSelect = vi.fn();
    render(<Sidebar items={ITEMS} active="dashboard" onSelect={onSelect} />);
    fireEvent.click(screen.getByRole("button", { name: "Registro" }));
    expect(onSelect).toHaveBeenCalledWith("log");
  });

  it("la sezione attiva ha le classi dell'attivo (token) e le altre no", () => {
    render(<Sidebar items={ITEMS} active="log" onSelect={() => undefined} />);
    expect(screen.getByRole("button", { name: "Registro" })).toHaveClass(
      "border-action",
      "text-action",
      "bg-surface-2",
    );
    expect(screen.getByRole("button", { name: "Plancia" })).not.toHaveClass("border-action");
  });
});

describe("ModeSelector", () => {
  it("due opzioni esclusive con il nome e la descrizione del design", () => {
    render(<ModeSelector value="scenario" onChange={() => undefined} />);
    const group = screen.getByRole("radiogroup", { name: strings.shell.modeLabel });
    const radios = within(group).getAllByRole("radio");
    expect(radios).toHaveLength(2);
    expect(radios[0]).toHaveTextContent("LIVE");
    expect(radios[0]).toHaveTextContent("Dati reali");
    expect(radios[1]).toHaveTextContent("SCENARIO");
    expect(radios[1]).toHaveTextContent("Simulazione");
    expect(radios.map((radio) => radio.getAttribute("aria-checked"))).toEqual(["false", "true"]);
  });

  it("l'opzione attiva ha il suo colore: verde dei dati reali per LIVE, arancione per SCENARIO", () => {
    const { rerender } = render(<ModeSelector value="live" onChange={() => undefined} />);
    expect(screen.getByRole("radio", { name: /LIVE/ })).toHaveClass(
      "border-data-real",
      "bg-mode-fill-live",
    );
    expect(screen.getByRole("radio", { name: /SCENARIO/ })).not.toHaveClass(
      "border-scenario-frame",
    );
    rerender(<ModeSelector value="scenario" onChange={() => undefined} />);
    expect(screen.getByRole("radio", { name: /SCENARIO/ })).toHaveClass(
      "border-scenario-frame",
      "bg-mode-fill-scenario",
    );
    expect(screen.getByRole("radio", { name: /SCENARIO/ })).toHaveClass("border-control");
  });

  it("un clic sceglie la modalità", () => {
    const seen: Mode[] = [];
    render(<ModeSelector value="scenario" onChange={(mode) => seen.push(mode)} />);
    fireEvent.click(screen.getByRole("radio", { name: /LIVE/ }));
    fireEvent.click(screen.getByRole("radio", { name: /SCENARIO/ }));
    expect(seen).toEqual(["live", "scenario"]);
  });
});

describe("SimulationBanner", () => {
  it("dice SIMULAZIONE, in arancione", () => {
    render(<SimulationBanner />);
    const banner = screen.getByText(strings.shell.simulationBanner);
    expect(banner).toHaveClass("bg-scenario-frame");
  });

  it("accetta una posizione", () => {
    render(<SimulationBanner className="absolute" />);
    expect(screen.getByText("SIMULAZIONE")).toHaveClass("absolute");
  });
});

describe("Tabs", () => {
  const TABS = [
    { id: "a", label: "Agenti" },
    { id: "b", label: "Operations" },
    { id: "c", label: "Decisioni" },
  ] as const;

  function Harness({ start = "a" }: { start?: "a" | "b" | "c" }) {
    const [active, setActive] = useState<"a" | "b" | "c">(start);
    return (
      <Tabs items={TABS} active={active} onChange={setActive} label="Pannello">
        <p>contenuto di {active}</p>
      </Tabs>
    );
  }
  const selected = () => screen.getByRole("tab", { selected: true }).textContent;

  it("elenco di schede, la selezionata e il suo pannello collegati", () => {
    render(<Harness start="b" />);
    const list = screen.getByRole("tablist", { name: "Pannello" });
    expect(within(list).getAllByRole("tab")).toHaveLength(3);
    expect(selected()).toBe("Operations");
    const panel = screen.getByRole("tabpanel");
    expect(panel).toHaveTextContent("contenuto di b");
    expect(screen.getByRole("tab", { selected: true })).toHaveAttribute("aria-controls", panel.id);
    expect(panel).toHaveAttribute(
      "aria-labelledby",
      screen.getByRole("tab", { selected: true }).id,
    );
  });

  it("solo la scheda selezionata è raggiungibile con Tab", () => {
    render(<Harness />);
    expect(screen.getAllByRole("tab").map((tab) => tab.getAttribute("tabindex"))).toEqual([
      "0",
      "-1",
      "-1",
    ]);
  });

  it("un clic cambia scheda e pannello", () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("tab", { name: "Decisioni" }));
    expect(selected()).toBe("Decisioni");
    expect(screen.getByRole("tabpanel")).toHaveTextContent("contenuto di c");
  });

  it("le frecce passano alla scheda accanto (e tornano all'inizio), il fuoco la segue", () => {
    render(<Harness />);
    const first = screen.getByRole("tab", { name: "Agenti" });
    first.focus();
    fireEvent.keyDown(first, { key: "ArrowRight" });
    expect(selected()).toBe("Operations");
    expect(screen.getByRole("tab", { name: "Operations" })).toHaveFocus();
    fireEvent.keyDown(screen.getByRole("tab", { name: "Operations" }), { key: "ArrowRight" });
    fireEvent.keyDown(screen.getByRole("tab", { name: "Decisioni" }), { key: "ArrowRight" });
    expect(selected()).toBe("Agenti");
    fireEvent.keyDown(screen.getByRole("tab", { name: "Agenti" }), { key: "ArrowLeft" });
    expect(selected()).toBe("Decisioni");
    fireEvent.keyDown(screen.getByRole("tab", { name: "Decisioni" }), { key: "ArrowLeft" });
    expect(selected()).toBe("Operations");
  });

  it("Home e Fine vanno alla prima e all'ultima", () => {
    render(<Harness start="b" />);
    fireEvent.keyDown(screen.getByRole("tab", { name: "Operations" }), { key: "End" });
    expect(selected()).toBe("Decisioni");
    fireEvent.keyDown(screen.getByRole("tab", { name: "Decisioni" }), { key: "Home" });
    expect(selected()).toBe("Agenti");
  });

  it("gli altri tasti non fanno niente", () => {
    render(<Harness />);
    fireEvent.keyDown(screen.getByRole("tab", { name: "Agenti" }), { key: "a" });
    expect(selected()).toBe("Agenti");
  });
});

describe("RunStatus", () => {
  it.each([
    ["INTAKE", "Acquisizione"],
    ["ANALYZE", "Analisi"],
    ["RECONCILE", "Riconciliazione"],
    ["PLAN", "Pianificazione"],
    ["DISPATCH", "Invio richieste"],
    ["AWAIT", "In attesa risposte"],
    ["REPLAN", "Ripianificazione"],
    ["VERIFY", "Verifica"],
    ["DONE", "Completato"],
    ["ERROR", "Errore"],
    ["DECISION_REQUIRED", "Decisione richiesta"],
  ] as const)("%s si legge «%s»", (state, label) => {
    render(<RunStatus state={state} />);
    expect(screen.getByText(label)).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuetext", label);
  });

  const steps = () =>
    [...screen.getByRole("progressbar").querySelectorAll("i")].map((i) =>
      i.getAttribute("data-step"),
    );

  it("nove tappe: quelle prima dello stato fatte, la sua in corso, le altre da fare", () => {
    render(<RunStatus state="PLAN" />);
    expect(steps()).toEqual([
      "done",
      "done",
      "done",
      "current",
      "todo",
      "todo",
      "todo",
      "todo",
      "todo",
    ]);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "4");
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuemax", "9");
  });

  it("a run completato sono tutte fatte, in verde", () => {
    render(<RunStatus state="DONE" />);
    expect(steps()).toEqual(Array(9).fill("done"));
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "9");
    expect(screen.getByRole("progressbar").querySelector("i")).toHaveClass("bg-data-real");
  });

  it("i colori seguono il tipo di stato", () => {
    const { rerender } = render(<RunStatus state="ANALYZE" />);
    expect(screen.getByText("Analisi")).toHaveClass("border-action", "bg-state-fill-running");
    rerender(<RunStatus state="AWAIT" />);
    expect(screen.getByText("In attesa risposte")).toHaveClass(
      "border-warning",
      "bg-state-fill-waiting",
    );
    rerender(<RunStatus state="DONE" />);
    expect(screen.getByText("Completato")).toHaveClass("border-data-real", "bg-state-fill-done");
    rerender(<RunStatus state="ERROR" step={4} />);
    expect(screen.getByText("Errore")).toHaveClass("border-danger", "bg-state-fill-error");
  });

  it("un errore o una decisione richiesta si fermano alla tappa data, con il suo colore", () => {
    render(<RunStatus state="ERROR" step={4} />);
    expect(steps()).toEqual([
      "done",
      "done",
      "done",
      "done",
      "current",
      "todo",
      "todo",
      "todo",
      "todo",
    ]);
    expect(screen.getByRole("progressbar").querySelectorAll("i")[4]).toHaveClass("bg-danger");
  });

  it("l'attesa ha la tappa gialla e ferma", () => {
    render(<RunStatus state="AWAIT" />);
    const current = screen.getByRole("progressbar").querySelectorAll("i")[5];
    expect(current).toHaveClass("bg-warning");
    expect(current).not.toHaveClass("animate-pulse");
  });

  it("il nome tecnico dello stato è nel suggerimento", () => {
    render(<RunStatus state="AWAIT" />);
    expect(screen.getByTitle("AWAIT")).toBeInTheDocument();
  });
});

describe("IterationIndicator", () => {
  it("«Iterazione n di 3» con una tacca per iterazione, accese fino alla corrente", () => {
    const { container } = render(<IterationIndicator current={2} total={3} />);
    expect(screen.getByText("Iterazione 2 di 3")).toBeInTheDocument();
    const ticks = [...container.querySelectorAll("i")];
    expect(ticks.map((tick) => tick.getAttribute("data-on"))).toEqual(["true", "true", "false"]);
    expect(ticks[0]).toHaveClass("bg-action");
    expect(ticks[2]).not.toHaveClass("bg-action");
  });
});

describe("IterationIndicator con più di tre passate", () => {
  it("«Iterazione 4 di 4» ha quattro tacche, tutte accese: mai «4 di 3»", () => {
    const { container } = render(<IterationIndicator current={4} total={4} />);
    expect(screen.getByText("Iterazione 4 di 4")).toBeInTheDocument();
    const ticks = [...container.querySelectorAll("i")];
    expect(ticks.map((tick) => tick.getAttribute("data-on"))).toEqual([
      "true",
      "true",
      "true",
      "true",
    ]);
  });
});

describe("WindowToggle", () => {
  it("Arrivo | Deflusso, esclusivi, con la finestra scelta selezionata", () => {
    render(<WindowToggle value="departure" onChange={() => undefined} />);
    const group = screen.getByRole("radiogroup", { name: strings.metrics.windowLabel });
    const radios = within(group).getAllByRole("radio");
    expect(radios.map((radio) => radio.textContent)).toEqual(["Arrivo", "Deflusso"]);
    expect(radios.map((radio) => radio.getAttribute("aria-checked"))).toEqual(["false", "true"]);
    expect(radios[1]).toHaveClass("bg-surface-3", "text-text-primary");
    expect(radios[0]).not.toHaveClass("bg-surface-3");
  });

  it("un clic sceglie la finestra", () => {
    const seen: WindowChoice[] = [];
    render(<WindowToggle value="departure" onChange={(window) => seen.push(window)} />);
    fireEvent.click(screen.getByRole("radio", { name: "Arrivo" }));
    fireEvent.click(screen.getByRole("radio", { name: "Deflusso" }));
    expect(seen).toEqual(["arrival", "departure"]);
  });
});
