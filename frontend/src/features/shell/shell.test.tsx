import {
  act,
  cleanup,
  fireEvent,
  render,
  renderHook,
  screen,
  within,
} from "@testing-library/react";
import type { ComponentProps, ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import App from "@/App";
import type { ApiClient } from "@/api/client";
import { createMockClient, type MockOptions } from "@/api/mock";
import { ApiProvider } from "@/api/provider";
import { AppShell } from "@/features/shell/AppShell";
import { ShellProvider, useShell } from "@/features/shell/ShellProvider";
import { strings } from "@/i18n/it";
import { RUN, runClient, withRun } from "@/test/runPanels";

const copy = strings.shell;

/** L'applicazione con la sessione aperta sul mock, già dentro il guscio. */
async function openApp(options: MockOptions = {}, client?: ApiClient) {
  render(<App client={client ?? createMockClient({ authenticated: true, ...options })} />);
  await screen.findByRole("heading", { level: 1, name: strings.appName });
}

/** La barra superiore: il pannello Agenti mostra lo stato del run anche lui, quindi si cerca qui dentro. */
const topBar = () => screen.getByRole("heading", { level: 1 }).closest("header") as HTMLElement;
const layout = () => document.querySelector("[data-layout]") as HTMLElement;
const radio = (name: RegExp) => screen.getByRole("radio", { name });

describe("il guscio", () => {
  it("ha il nome del prodotto come titolo, la barra laterale e le tre colonne", async () => {
    await openApp();
    expect(screen.getByRole("navigation", { name: copy.navLabel })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: copy.eventManager.title })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: copy.regions.map })).toBeInTheDocument();
    expect(screen.getByRole("tablist", { name: copy.panelTabs })).toBeInTheDocument();
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
      "Agenti",
      "Operations",
      "Decisioni",
    ]);
  });

  it("la fascia delle metriche ha le cinque card, vuote finché non c'è un run", async () => {
    await openApp();
    const strip = screen.getByRole("region", { name: strings.metrics.regionLabel });
    expect(strip.children).toHaveLength(5);
    expect(strip).toHaveClass("h-size-metrics-height", "grid-cols-5");
    expect(within(strip).getAllByText(strings.metrics.noRun)).toHaveLength(5);
  });

  it("il selettore Arrivo | Deflusso sta sulla mappa; si parte dal deflusso", async () => {
    await openApp();
    const map = screen.getByRole("region", { name: copy.regions.map });
    const toggle = within(map).getByRole("radiogroup", { name: strings.metrics.windowLabel });
    expect(within(toggle).getByRole("radio", { name: "Deflusso" })).toBeChecked();
    fireEvent.click(within(toggle).getByRole("radio", { name: "Arrivo" }));
    expect(within(toggle).getByRole("radio", { name: "Arrivo" })).toBeChecked();
  });

  it("mette negli slot ciò che gli si dà (metriche, Event Manager, mappa, pannelli)", () => {
    render(
      <ApiProvider client={createMockClient({ authenticated: true })}>
        <ShellProvider initial={{ tab: "operations" }}>
          <AppShell
            metrics={<p>le metriche</p>}
            eventManager={<p>il form</p>}
            map={<p>la mappa</p>}
            panels={{ agents: <p>gli agenti</p>, operations: <p>le operations</p> }}
          />
        </ShellProvider>
      </ApiProvider>,
    );
    expect(screen.getByText("le metriche")).toBeInTheDocument();
    expect(screen.getByText("il form")).toBeInTheDocument();
    expect(screen.getByText("la mappa")).toBeInTheDocument();
    expect(screen.getByRole("tabpanel")).toHaveTextContent("le operations");
    expect(screen.queryByText("gli agenti")).not.toBeInTheDocument();
    expect(
      screen.queryAllByLabelText("", { selector: "[aria-hidden]" }).length,
    ).toBeGreaterThanOrEqual(0);
  });
});

describe("SCENARIO e LIVE (07 2)", () => {
  it("si parte da SCENARIO: cornice, banner SIMULAZIONE e avviso sono sempre visibili", async () => {
    await openApp();
    expect(radio(/SCENARIO/)).toBeChecked();
    expect(screen.getByText(copy.simulationBanner)).toBeInTheDocument();
    expect(screen.getByText(copy.disclaimer)).toBeInTheDocument();
    const frame = screen.getByTestId("scenario-frame");
    expect(frame).toHaveClass(
      "fixed",
      "inset-0",
      "pointer-events-none",
      "border-scenario-frame",
      "border-scenario-frame-width",
    );
    expect(frame).toHaveAttribute("aria-hidden", "true");
  });

  it("la cornice sta sopra a tutto e non cattura i clic", async () => {
    await openApp();
    const frame = screen.getByTestId("scenario-frame");
    expect(frame).toHaveClass("z-50", "pointer-events-none");
  });

  it("in LIVE la cornice, il banner e l'avviso spariscono; si torna con SCENARIO", async () => {
    await openApp();
    fireEvent.click(radio(/LIVE/));
    expect(radio(/LIVE/)).toBeChecked();
    expect(screen.queryByText(copy.simulationBanner)).not.toBeInTheDocument();
    expect(screen.queryByText(copy.disclaimer)).not.toBeInTheDocument();
    expect(screen.queryByTestId("scenario-frame")).not.toBeInTheDocument();
    fireEvent.click(radio(/SCENARIO/));
    expect(screen.getByText(copy.simulationBanner)).toBeInTheDocument();
    expect(screen.getByTestId("scenario-frame")).toBeInTheDocument();
  });

  it("si può partire da LIVE", () => {
    render(
      <ApiProvider client={createMockClient({ authenticated: true })}>
        <ShellProvider initial={{ mode: "live" }}>
          <AppShell />
        </ShellProvider>
      </ApiProvider>,
    );
    expect(radio(/LIVE/)).toBeChecked();
    expect(screen.queryByTestId("scenario-frame")).not.toBeInTheDocument();
  });
});

/** Il guscio che segue un run (concluso: l'Event Manager non si riapre da solo). */
function openWithRun() {
  render(
    <ApiProvider client={runClient().client}>
      <ShellProvider initial={{ runId: RUN }}>
        <AppShell />
      </ShellProvider>
    </ApiProvider>,
  );
}

describe("le colonne", () => {
  it("aperto: Event Manager 360 / mappa / pannello 440 (300 e 360 sotto 1440 px)", async () => {
    await openApp();
    expect(layout()).toHaveAttribute("data-layout", "open");
    const classes = layout().className;
    expect(classes).toContain(
      "grid-cols-[var(--layout-event-manager-compact)_minmax(0,1fr)_var(--layout-right-panel-compact)]",
    );
    expect(classes).toContain(
      "compact:grid-cols-[var(--layout-event-manager)_minmax(0,1fr)_var(--layout-right-panel)]",
    );
  });

  it("senza un run l'intestazione non ha la freccia (design 01–03); con un run sì", async () => {
    await openApp();
    expect(
      screen.queryByRole("button", { name: copy.eventManager.collapse }),
    ).not.toBeInTheDocument();
    cleanup();
    openWithRun();
    expect(
      await screen.findByRole("button", { name: copy.eventManager.collapse }),
    ).toBeInTheDocument();
  });

  it("compresso: binario di 108 px e pannello destro di 692", async () => {
    openWithRun();
    fireEvent.click(await screen.findByRole("button", { name: copy.eventManager.collapse }));
    expect(layout()).toHaveAttribute("data-layout", "rail");
    expect(layout().className).toContain(
      "grid-cols-[var(--layout-event-manager-rail)_minmax(0,1fr)_var(--layout-right-panel-wide)]",
    );
    expect(layout().className).not.toContain("compact:grid-cols");
    expect(screen.queryByRole("region", { name: copy.eventManager.title })).not.toBeInTheDocument();
  });

  it("il binario riapre l'Event Manager", async () => {
    openWithRun();
    fireEvent.click(await screen.findByRole("button", { name: copy.eventManager.collapse }));
    const rail = screen.getByRole("button", { name: copy.eventManager.title });
    expect(rail).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(rail);
    expect(layout()).toHaveAttribute("data-layout", "open");
    expect(screen.getByRole("button", { name: copy.eventManager.collapse })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });

  it("la mappa occupa lo spazio che resta e non esce dalla sua scheda", async () => {
    await openApp();
    expect(screen.getByRole("region", { name: copy.regions.map })).toHaveClass(
      "min-h-0",
      "overflow-hidden",
      "relative",
    );
    expect(layout().className).toContain("minmax(0,1fr)");
  });
});

describe("barra laterale e schede", () => {
  const selected = () => screen.getByRole("tab", { selected: true }).textContent;
  const section = (name: string) => screen.getByRole("button", { name });

  it("si parte dalla plancia e dalla scheda Agenti", async () => {
    await openApp();
    expect(section(copy.nav.dashboard)).toHaveAttribute("aria-current", "page");
    expect(selected()).toBe("Agenti");
  });

  it("«Richieste e dipartimenti» apre Operations, «Registro decisioni» Decisioni", async () => {
    await openApp();
    fireEvent.click(section(copy.nav.requests));
    expect(selected()).toBe("Operations");
    expect(section(copy.nav.requests)).toHaveAttribute("aria-current", "page");
    fireEvent.click(section(copy.nav.log));
    expect(selected()).toBe("Decisioni");
    expect(section(copy.nav.requests)).not.toHaveAttribute("aria-current");
  });

  it("la plancia lascia la scheda com'è", async () => {
    await openApp();
    fireEvent.click(section(copy.nav.log));
    fireEvent.click(section(copy.nav.dashboard));
    expect(selected()).toBe("Decisioni");
    expect(section(copy.nav.dashboard)).toHaveAttribute("aria-current", "page");
  });

  it("le schede si scelgono anche da sole", async () => {
    await openApp();
    fireEvent.click(screen.getByRole("tab", { name: "Operations" }));
    expect(selected()).toBe("Operations");
  });
});

describe("la barra superiore", () => {
  it("senza un run non mostra stato né iterazione", async () => {
    await openApp();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    expect(screen.queryByText(/Iterazione \d di 3/)).not.toBeInTheDocument();
  });

  it("con un run mostra il suo stato, la barra di avanzamento e «Iterazione n di 3»", async () => {
    const client = createMockClient({ authenticated: true });
    render(
      <ApiProvider client={client}>
        <ShellProvider initial={{ runId: "run_mock_match_2027" }}>
          <AppShell />
        </ShellProvider>
      </ApiProvider>,
    );
    // il primo fotogramma del mock è INTAKE, iterazione 0 → «Iterazione 1 di 3»
    const bar = within(topBar());
    expect(await bar.findByText(copy.runStates.INTAKE)).toBeInTheDocument();
    expect(bar.getByRole("progressbar", { name: copy.progressLabel })).toBeInTheDocument();
    expect(bar.getByText("Iterazione 1 di 3")).toBeInTheDocument();
  });

  it("un run alla quarta passata (tre ripianificazioni) dice «Iterazione 4 di 4», non «4 di 3»", async () => {
    const view = withRun({ state: "DONE", iteration: 3, replans: 3 });
    const made = runClient({ view });
    render(
      <ApiProvider client={made.client}>
        <ShellProvider initial={{ runId: RUN }}>
          <AppShell />
        </ShellProvider>
      </ApiProvider>,
    );
    const bar = within(topBar());
    expect(await bar.findByText("Iterazione 4 di 4")).toBeInTheDocument();
    expect(bar.queryByText(/di 3/)).not.toBeInTheDocument();
  });

  it("un run in errore lo dice", async () => {
    render(
      <ApiProvider client={createMockClient({ authenticated: true, runVariant: "error" })}>
        <ShellProvider initial={{ runId: "run_mock_match_2027" }}>
          <AppShell />
        </ShellProvider>
      </ApiProvider>,
    );
    expect(await within(topBar()).findByText(copy.runStates.ERROR)).toBeInTheDocument();
  });

  it("tre zone: a sinistra nome e run, al centro il banner, a destra modalità e uscita", async () => {
    await openApp();
    const bar = screen.getByRole("heading", { level: 1 }).closest("header") as HTMLElement;
    expect(bar).toHaveClass("h-size-topbar-height", "grid", "grid-cols-[1fr_auto_1fr]");
    const [left, center, right] = Array.from(bar.children) as HTMLElement[];
    expect(within(left as HTMLElement).getByRole("heading", { level: 1 })).toBeInTheDocument();
    expect(within(center as HTMLElement).getByText(copy.simulationBanner)).toBeInTheDocument();
    expect(within(right as HTMLElement).getByRole("radiogroup")).toBeInTheDocument();
    expect(
      within(right as HTMLElement).getByRole("button", { name: copy.logout }),
    ).toBeInTheDocument();
  });

  it("il banner non si sovrappone a niente: non è posizionato in modo assoluto", async () => {
    await openApp();
    expect(screen.getByText(copy.simulationBanner)).not.toHaveClass("absolute");
  });

  it("in LIVE la zona centrale resta (vuota) e la modalità resta a destra", async () => {
    await openApp();
    fireEvent.click(radio(/LIVE/));
    const bar = screen.getByRole("heading", { level: 1 }).closest("header") as HTMLElement;
    expect(bar.children).toHaveLength(3);
    expect(bar.children[1]).toBeEmptyDOMElement();
    expect(within(bar.children[2] as HTMLElement).getByRole("radiogroup")).toBeInTheDocument();
  });

  it("Esci chiude la sessione e torna al login", async () => {
    await openApp();
    fireEvent.click(screen.getByRole("button", { name: copy.logout }));
    expect(await screen.findByLabelText(strings.login.passwordLabel)).toBeInTheDocument();
  });
});

describe("ShellProvider", () => {
  const wrapper = ({ children }: { children: ReactNode }) => (
    <ShellProvider>{children}</ShellProvider>
  );

  it("parte da SCENARIO, plancia, Agenti, deflusso, Event Manager aperto e nessun run", () => {
    const { result } = renderHook(() => useShell(), { wrapper });
    expect(result.current).toMatchObject({
      mode: "scenario",
      section: "dashboard",
      tab: "agents",
      window: "departure",
      eventManagerOpen: true,
      runId: undefined,
    });
  });

  it("seguire un run comprime l'Event Manager; smettere di seguirlo non lo riapre", () => {
    const { result } = renderHook(() => useShell(), { wrapper });
    act(() => result.current.followRun("run_1"));
    expect(result.current.runId).toBe("run_1");
    expect(result.current.eventManagerOpen).toBe(false);
    act(() => result.current.setEventManagerOpen(true));
    act(() => result.current.followRun(undefined));
    expect(result.current.runId).toBeUndefined();
    expect(result.current.eventManagerOpen).toBe(true);
  });

  it("entrando in LIVE si apre la scheda Operations (design 01); tornando a SCENARIO la scheda resta", () => {
    const { result } = renderHook(() => useShell(), { wrapper });
    expect(result.current.tab).toBe("agents");
    act(() => result.current.setMode("live"));
    expect(result.current).toMatchObject({ mode: "live", tab: "operations" });
    act(() => result.current.setTab("decisions"));
    act(() => result.current.setMode("scenario"));
    expect(result.current).toMatchObject({ mode: "scenario", tab: "decisions" });
  });

  it("seguire un run porta a SCENARIO anche da LIVE; smettere di seguirlo non cambia la modalità", () => {
    const { result } = renderHook(() => useShell(), { wrapper });
    act(() => result.current.setMode("live"));
    act(() => result.current.followRun(undefined));
    expect(result.current.mode).toBe("live");
    act(() => result.current.followRun("run_1"));
    expect(result.current.mode).toBe("scenario");
  });

  it("la finestra si cambia e si può impostare all'inizio", () => {
    const { result } = renderHook(() => useShell(), { wrapper });
    act(() => result.current.setWindow("arrival"));
    expect(result.current.window).toBe("arrival");
    const initial = renderHook(() => useShell(), {
      wrapper: ({ children }: { children: ReactNode }) => (
        <ShellProvider initial={{ window: "arrival" }}>{children}</ShellProvider>
      ),
    });
    expect(initial.result.current.window).toBe("arrival");
  });

  it("usare lo stato fuori dal provider è un errore", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    expect(() => renderHook(() => useShell())).toThrow("useShell fuori da <ShellProvider>");
  });

  function shellWith(initial: ComponentProps<typeof ShellProvider>["initial"]) {
    return (
      <ApiProvider client={createMockClient({ authenticated: true })}>
        <ShellProvider initial={initial}>
          <AppShell />
        </ShellProvider>
      </ApiProvider>
    );
  }

  it("«In corso» compare sull'intestazione e sul binario solo con un run", () => {
    const { unmount } = render(shellWith({}));
    expect(screen.queryByText(copy.eventManager.running)).not.toBeInTheDocument();
    unmount();
    const open = render(shellWith({ runId: "run_mock_match_2027" }));
    expect(screen.getByText(copy.eventManager.running)).toBeInTheDocument();
    open.unmount();
    render(shellWith({ runId: "run_mock_match_2027", eventManagerOpen: false }));
    expect(
      within(screen.getByRole("button", { name: copy.eventManager.title })).getByText(
        copy.eventManager.running,
      ),
    ).toBeInTheDocument();
  });
});
