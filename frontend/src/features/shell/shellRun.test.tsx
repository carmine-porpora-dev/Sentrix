import {
  act,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";
import { ApiProvider } from "@/api/provider";
import type { RunView } from "@/api/types";
import { AppShell } from "@/features/shell/AppShell";
import { ShellProvider, useShell } from "@/features/shell/ShellProvider";
import { strings } from "@/i18n/it";
import { fixture } from "@/test/fixtures";
import { RUN, doneView, runClient } from "@/test/runPanels";

const topBar = () => screen.getByRole("heading", { level: 1 }).closest("header") as HTMLElement;

describe("pannelli di default del guscio", () => {
  async function open(
    options: Parameters<typeof runClient>[0] = {},
    initial: Parameters<typeof ShellProvider>[0]["initial"] = { runId: RUN },
  ) {
    const made = runClient(options);
    render(
      <ApiProvider client={made.client}>
        <ShellProvider initial={initial}>
          <AppShell />
        </ShellProvider>
      </ApiProvider>,
    );
    return made;
  }

  it("Agenti è la scheda di partenza; le altre due si aprono dalle schede", async () => {
    await open();
    expect(
      await screen.findByRole("heading", { name: strings.panels.agents.title }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: strings.shell.tabs.operations }));
    expect(
      await screen.findByRole("heading", { name: strings.panels.ops.requests }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: strings.shell.tabs.decisions }));
    expect(
      await screen.findByRole("heading", { name: strings.panels.log.title }),
    ).toBeInTheDocument();
  });

  it("le voci della barra laterale aprono la scheda che le corrisponde", async () => {
    await open();
    fireEvent.click(screen.getByRole("button", { name: strings.shell.nav.requests }));
    expect(
      await screen.findByRole("heading", { name: strings.panels.ops.requests }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: strings.shell.nav.log }));
    expect(
      await screen.findByRole("heading", { name: strings.panels.log.title }),
    ).toBeInTheDocument();
  });

  it("un'evidenza con un luogo porta la mappa lì (la mappa riceve il punto)", async () => {
    await open();
    const buttons = await screen.findAllByRole("button", { name: strings.panels.agents.showOnMap });
    fireEvent.click(buttons[0] as HTMLElement);
    await waitFor(() =>
      expect(screen.getByTestId("map-canvas").dataset.focus).toBe("40.8353,14.2449#1"),
    );
    fireEvent.click(buttons[0] as HTMLElement);
    expect(screen.getByTestId("map-canvas").dataset.focus).toBe("40.8353,14.2449#2");
  });

  it("la barra superiore mostra «Decisione richiesta» quando una misura aspetta una persona", async () => {
    await open({ view: fixture<RunView>("run_view_variant_human_decision.json") });
    expect(
      await within(topBar()).findByText(strings.shell.runStates.DECISION_REQUIRED),
    ).toBeInTheDocument();
  });

  it("«Decisione richiesta» tiene la tappa dove il run si è fermato (qui l'ultima: completato)", async () => {
    await open({ view: fixture<RunView>("run_view_variant_human_decision.json") });
    await within(topBar()).findByText(strings.shell.runStates.DECISION_REQUIRED);
    expect(within(topBar()).getByRole("progressbar")).toHaveAttribute("aria-valuenow", "9");
  });

  it("«In corso» si accende con un run in esecuzione e si spegne a run finito (DONE o ERROR)", async () => {
    const running = strings.shell.eventManager.running;
    const { unmount } = render(
      <ApiProvider
        client={runClient({ view: fixture<RunView>("run_view/step_06_await_sent.json") }).client}
      >
        <ShellProvider initial={{ runId: RUN }}>
          <AppShell />
        </ShellProvider>
      </ApiProvider>,
    );
    expect(await screen.findByText(running)).toBeInTheDocument();
    unmount();
    const finished = doneView;
    const errored = { ...finished, run: { ...finished.run, state: "ERROR" as const, error: "x" } };
    for (const view of [finished, errored]) {
      const made = runClient({ view });
      const open = render(
        <ApiProvider client={made.client}>
          <ShellProvider initial={{ runId: RUN }}>
            <AppShell />
          </ShellProvider>
        </ApiProvider>,
      );
      await waitFor(() => expect(made.getRun).toHaveBeenCalled());
      await within(topBar()).findByText(
        view === finished ? strings.shell.runStates.DONE : strings.shell.runStates.ERROR,
      );
      expect(screen.queryByText(running)).not.toBeInTheDocument();
      open.unmount();
    }
  });

  describe("Event Manager a run finito", () => {
    const layout = () => document.querySelector("[data-layout]") as HTMLElement;
    const errored = { ...doneView, run: { ...doneView.run, state: "ERROR" as const, error: "x" } };

    it("un run in ERRORE riapre l'Event Manager (design 11: si riparte da lì); a DONE resta compattato", async () => {
      for (const [view, expected] of [
        [doneView, "rail"],
        [errored, "open"],
      ] as const) {
        const made = runClient({ view });
        const { unmount } = render(
          <ApiProvider client={made.client}>
            <ShellProvider initial={{ runId: RUN, eventManagerOpen: false }}>
              <AppShell />
            </ShellProvider>
          </ApiProvider>,
        );
        await waitFor(() => expect(made.getRun).toHaveBeenCalled());
        await within(topBar()).findByText(
          view === doneView ? strings.shell.runStates.DONE : strings.shell.runStates.ERROR,
        );
        // l'effetto che lo riapre scatta dopo la scrittura dello stato: si lascia passare un attimo
        await act(async () => {
          await new Promise((resolve) => setTimeout(resolve, 50));
        });
        expect(layout()).toHaveAttribute("data-layout", expected);
        unmount();
      }
    });

    it("lo riapre una volta sola: chi lo richiude a mano lo trova richiuso", async () => {
      const made = runClient({ view: errored });
      render(
        <ApiProvider client={made.client}>
          <ShellProvider initial={{ runId: RUN, eventManagerOpen: false }}>
            <AppShell />
          </ShellProvider>
        </ApiProvider>,
      );
      await waitFor(() => expect(layout()).toHaveAttribute("data-layout", "open"));
      fireEvent.click(screen.getByRole("button", { name: strings.shell.eventManager.collapse }));
      expect(layout()).toHaveAttribute("data-layout", "rail");
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 50));
      });
      expect(layout()).toHaveAttribute("data-layout", "rail");
    });
  });

  it("con lo stesso run senza misure in attesa, la barra dice lo stato vero", async () => {
    await open();
    expect(await within(topBar()).findByText(strings.shell.runStates.DONE)).toBeInTheDocument();
  });
});

describe("stato dell'interfaccia per i pannelli", () => {
  const wrapper = ({ children }: { children: ReactNode }) => (
    <ShellProvider>{children}</ShellProvider>
  );

  it("seguire un run dice se è manuale; un run senza indicazione non lo è", () => {
    const { result } = renderHook(() => useShell(), { wrapper });
    expect(result.current.runManual).toBe(false);
    act(() => result.current.followRun("r1", { manual: true }));
    expect(result.current.runId).toBe("r1");
    expect(result.current.runManual).toBe(true);
    act(() => result.current.followRun("r2"));
    expect(result.current.runManual).toBe(false);
  });

  it("cambiare l'interruttore a run avviato non cambia il run", () => {
    const { result } = renderHook(() => useShell(), { wrapper });
    act(() => result.current.followRun("r1", { manual: false }));
    act(() => result.current.setManualResponse(true));
    expect(result.current.manualResponse).toBe(true);
    expect(result.current.runManual).toBe(false);
  });

  it("il punto sulla mappa ha una chiave che cresce a ogni richiesta e si azzera con un run nuovo", () => {
    const { result } = renderHook(() => useShell(), { wrapper });
    expect(result.current.focus).toBeUndefined();
    act(() => result.current.focusOn({ lat: 40.8, lon: 14.2, label: "Qui" }));
    expect(result.current.focus).toEqual({ lat: 40.8, lon: 14.2, label: "Qui", key: 1 });
    act(() => result.current.focusOn({ lat: 40.8, lon: 14.2 }));
    expect(result.current.focus?.key).toBe(2);
    act(() => result.current.followRun("r9"));
    expect(result.current.focus).toBeUndefined();
  });

  it("lo stato iniziale per i test: runManual segue manualResponse se non è dato", () => {
    const { result } = renderHook(() => useShell(), {
      wrapper: ({ children }) => (
        <ShellProvider initial={{ manualResponse: true }}>{children}</ShellProvider>
      ),
    });
    expect(result.current.manualResponse).toBe(true);
    expect(result.current.runManual).toBe(true);
  });
});
