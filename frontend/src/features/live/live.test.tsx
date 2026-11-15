import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { createMockClient, type MockLiveMode } from "@/api/mock";
import { ApiProvider } from "@/api/provider";
import type { LiveFlowResponse } from "@/api/types";
import { SourceChip } from "@/components/SourceChip";
import { LivePanel } from "@/features/live/LivePanel";
import { LiveSourceChip } from "@/features/live/LiveSourceChip";
import { LiveStrip } from "@/features/live/LiveStrip";
import { AppShell } from "@/features/shell/AppShell";
import { ShellProvider } from "@/features/shell/ShellProvider";
import { strings } from "@/i18n/it";
import { fixture } from "@/test/fixtures";

const copy = strings.live;

function show(node: React.ReactNode, mode: MockLiveMode = "fresh", flow?: LiveFlowResponse) {
  const client = createMockClient({ authenticated: true, liveMode: mode });
  if (flow) client.liveFlow = () => Promise.resolve(flow);
  return render(<ApiProvider client={client}>{node}</ApiProvider>);
}

const allClear = (): LiveFlowResponse => {
  const flow = fixture<LiveFlowResponse>("live_flow_fresh.json");
  return {
    ...flow,
    segments: flow.segments.map((s) => ({ ...s, congestion_class: 0 })),
  };
};

describe("LiveStrip: le cinque card con numeri veri", () => {
  it("mostra il riepilogo dei tratti, ognuno con la sua provenienza (STIMA o REALE)", async () => {
    show(
      <section aria-label="Metriche">
        <LiveStrip />
      </section>,
    );
    await screen.findByText("41,4");
    for (const label of [
      copy.cards.meanSpeed,
      copy.cards.meanRatio,
      copy.cards.slowed,
      copy.cards.slowest,
      copy.cards.covered,
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    // media e conteggi sono STIME (derivati), il tratto più lento è REALE: lo dicono i badge
    expect(screen.getAllByText(strings.metrics.badges.estimate)).toHaveLength(4);
    expect(screen.getAllByText(strings.metrics.badges.real)).toHaveLength(1);
    // il nome del tratto più lento viene dalla risposta
    expect(screen.getByText(/Via Caracciolo/)).toBeInTheDocument();
    // nessun numero di SCENARIO: né ore-veicolo né affluenza
    expect(screen.queryByText(strings.metrics.cards.vehicleHours)).not.toBeInTheDocument();
    expect(screen.queryByText(strings.metrics.cards.attendance)).not.toBeInTheDocument();
  });

  it("senza dati le cinque card dicono «Non disponibile» e non inventano un numero", async () => {
    show(<LiveStrip />, "unavailable");
    await waitFor(() =>
      expect(screen.getAllByText(strings.metrics.unavailable).length).toBeGreaterThanOrEqual(5),
    );
    expect(screen.queryByText("41,4")).not.toBeInTheDocument();
  });

  it("mentre legge, le card sono in caricamento", () => {
    show(<LiveStrip />);
    expect(screen.getAllByText(strings.metrics.loading).length).toBeGreaterThanOrEqual(1);
  });
});

describe("LivePanel: lo stato dei tratti in parole", () => {
  it("tratti rallentati: l'elenco, dal più lento, con le velocità e la classe", async () => {
    show(<LivePanel />);
    await screen.findByText(copy.panel.slowedTitle);
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(2); // Via Caracciolo (intensa) e Via Acton (rallentata)
    expect(items[0]).toHaveTextContent("Via Caracciolo");
    expect(items[0]).toHaveTextContent("Intensa");
    expect(items[1]).toHaveTextContent("Via Acton");
    expect(items[1]).toHaveTextContent("Rallentata");
    // le velocità (attuale e a flusso libero) sono numeri REALI con il tooltip, non testo
    expect(within(items[0] as HTMLElement).getAllByText(/^\d+,\d$/)).toHaveLength(2);
    expect(screen.queryByText(copy.panel.ordinaryTitle)).not.toBeInTheDocument();
  });

  it("nessun rallentamento: «Nessuna criticità» (situazione ordinaria)", async () => {
    show(<LivePanel />, "fresh", allClear());
    expect(await screen.findByText(copy.panel.ordinaryTitle)).toBeInTheDocument();
    expect(screen.getByText(copy.panel.ordinaryHint)).toBeInTheDocument();
  });

  it("con lo snapshot non dice «nessuna criticità»: dice «Dati parziali» (design, domanda 20)", async () => {
    show(<LivePanel />, "snapshot");
    expect(await screen.findByText(copy.panel.partialTitle)).toBeInTheDocument();
    expect(screen.queryByText(copy.panel.ordinaryTitle)).not.toBeInTheDocument();
  });

  it("senza nessun dato: «Nessun dato»", async () => {
    show(<LivePanel />, "unavailable");
    expect(await screen.findByText(copy.panel.noneTitle)).toBeInTheDocument();
  });

  it("mentre legge lo dice", () => {
    show(<LivePanel />);
    expect(screen.getByText(copy.panel.loading)).toBeInTheDocument();
  });
});

describe("il chip «Fonte non disponibile: TomTom» (design 02)", () => {
  it("con i dati recenti non c'è", async () => {
    show(
      <>
        <LiveSourceChip />
        <LiveStrip />
      </>,
    );
    await screen.findByText("41,4");
    expect(screen.queryByRole("button", { name: /Fonte non disponibile/ })).not.toBeInTheDocument();
  });

  it("con lo snapshot c'è, e il popover dice cosa succede, perché e l'ora dell'ultimo dato", async () => {
    show(<LiveSourceChip />, "snapshot");
    const chip = await screen.findByRole("button", { name: copy.sourceChip(copy.source) });
    expect(chip).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(chip);
    expect(chip).toHaveAttribute("aria-expanded", "true");
    const popover = screen.getByRole("dialog", { name: copy.sourceChip(copy.source) });
    expect(popover).toHaveTextContent(copy.source);
    expect(popover).toHaveTextContent(copy.sourceNote.snapshot);
    expect(popover).toHaveTextContent(copy.reasons.tomtom_unreachable);
    expect(popover).toHaveTextContent(/Ultimo dato alle \d{2}:\d{2}/);
  });

  it("senza nessun dato noto lo dice", async () => {
    show(<LiveSourceChip />, "unavailable");
    fireEvent.click(await screen.findByRole("button", { name: /Fonte non disponibile/ }));
    const popover = screen.getByRole("dialog");
    expect(popover).toHaveTextContent(copy.sourceNote.unavailable);
    expect(popover).toHaveTextContent(copy.reasons.tomtom_key_missing);
    expect(popover).not.toHaveTextContent(/Ultimo dato alle/);
  });

  it("un errore verso il nostro server è lo stesso: il chip, non un errore a tutto schermo", async () => {
    const client = createMockClient({ authenticated: true });
    client.liveFlow = () => Promise.reject(new Error("giù"));
    render(
      <ApiProvider client={client}>
        <LiveSourceChip />
      </ApiProvider>,
    );
    expect(
      await screen.findByRole("button", { name: /Fonte non disponibile/ }),
    ).toBeInTheDocument();
  });

  it("un motivo che non conosce lo mostra com'è", async () => {
    const flow = {
      ...fixture<LiveFlowResponse>("live_flow_snapshot.json"),
      degraded_reason: "boh_nuovo",
    };
    show(<LiveSourceChip />, "snapshot", flow);
    fireEvent.click(await screen.findByRole("button", { name: /Fonte non disponibile/ }));
    expect(screen.getByRole("dialog")).toHaveTextContent("boh_nuovo");
  });
});

describe("SourceChip: apre e chiude", () => {
  const chip = () => (
    <div>
      <SourceChip label="Fonte non disponibile: X" title="X">
        <p>nota</p>
      </SourceChip>
      <button type="button">fuori</button>
    </div>
  );

  it("un secondo clic lo chiude", () => {
    render(chip());
    const button = screen.getByRole("button", { name: /Fonte non disponibile/ });
    fireEvent.click(button);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.click(button);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("Esc lo chiude", () => {
    render(chip());
    fireEvent.click(screen.getByRole("button", { name: /Fonte non disponibile/ }));
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("un clic fuori lo chiude; uno dentro no", () => {
    render(chip());
    fireEvent.click(screen.getByRole("button", { name: /Fonte non disponibile/ }));
    fireEvent.pointerDown(screen.getByText("nota"));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    act(() => {
      fireEvent.pointerDown(screen.getByRole("button", { name: "fuori" }));
    });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("l'icona e il testo dicono lo stato: non solo il colore", () => {
    render(chip());
    const button = screen.getByRole("button", { name: /Fonte non disponibile: X/ });
    expect(button.querySelectorAll("svg")).toHaveLength(2); // l'avviso e la freccia
    expect(button).toHaveTextContent("Fonte non disponibile: X");
  });
});

describe("il guscio in LIVE", () => {
  const shell = (mode: MockLiveMode = "fresh", initial: "live" | "scenario" = "live") => {
    const client = createMockClient({ authenticated: true, liveMode: mode });
    const liveFlow = vi.spyOn(client, "liveFlow");
    render(
      <ApiProvider client={client}>
        <ShellProvider initial={{ mode: initial, tab: "operations" }}>
          <AppShell />
        </ShellProvider>
      </ApiProvider>,
    );
    return { client, liveFlow };
  };

  it("fascia, pannello e mappa parlano dei tratti: una sola lettura per tutti", async () => {
    const { liveFlow } = shell();
    // la fascia con i numeri veri e il pannello Operations con i tratti rallentati
    await screen.findByText(copy.cards.meanSpeed);
    await screen.findByText(copy.panel.slowedTitle);
    expect(await screen.findByText("41,4")).toBeInTheDocument();
    expect(screen.queryByText(strings.metrics.cards.vehicleHours)).not.toBeInTheDocument();
    // il chip della fonte non c'è con i dati recenti
    expect(screen.queryByRole("button", { name: /Fonte non disponibile/ })).not.toBeInTheDocument();
    // fascia, pannello, mappa e barra leggono la stessa cache: una chiamata sola
    expect(liveFlow).toHaveBeenCalledTimes(1);
  });

  it("con lo snapshot la barra ha il chip e il pannello dice «Dati parziali»", async () => {
    shell("snapshot");
    expect(
      await screen.findByRole("button", { name: copy.sourceChip(copy.source) }),
    ).toBeInTheDocument();
    expect(await screen.findByText(copy.panel.partialTitle)).toBeInTheDocument();
    // i numeri ci sono comunque (gli ultimi noti), con la loro ora
    expect(screen.getByText(copy.cards.meanSpeed)).toBeInTheDocument();
  });

  it("senza dati: «Non disponibile» nelle card, «Nessun dato» nel pannello, il chip, e il resto vive", async () => {
    shell("unavailable");
    expect(await screen.findByText(copy.panel.noneTitle)).toBeInTheDocument();
    expect(screen.getAllByText(strings.metrics.unavailable).length).toBeGreaterThanOrEqual(5);
    expect(screen.getByRole("button", { name: /Fonte non disponibile/ })).toBeInTheDocument();
    expect(screen.getByRole("tablist", { name: strings.shell.panelTabs })).toBeInTheDocument();
  });

  it("rilegge i tratti ogni minuto, una sola volta per tutti i componenti", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const { liveFlow } = shell();
      await screen.findByText("41,4");
      expect(liveFlow).toHaveBeenCalledTimes(1);
      await vi.advanceTimersByTimeAsync(60_000);
      await waitFor(() => expect(liveFlow).toHaveBeenCalledTimes(2));
      await vi.advanceTimersByTimeAsync(10_000); // un minuto non è ancora passato di nuovo
      expect(liveFlow).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("il chip della fonte sta a destra, a sinistra del selettore (design 02), non accanto al nome", async () => {
    shell("snapshot");
    const chip = await screen.findByRole("button", { name: copy.sourceChip(copy.source) });
    const selector = screen.getByRole("radiogroup", { name: strings.shell.modeLabel });
    const bar = chip.closest("header");
    expect(chip.closest("div[class*='justify-end']")).toBe(selector.parentElement);
    expect(bar?.firstElementChild).not.toContainElement(chip);
    // e subito prima del selettore
    expect(chip.parentElement?.nextElementSibling).toBe(selector);
  });

  it("«Analizza» in LIVE porta a SCENARIO: il run è una simulazione, i suoi risultati non stanno in LIVE", async () => {
    const { client } = shell();
    const createRun = vi.spyOn(client, "createRun");
    await screen.findByText(copy.cards.meanSpeed);
    const analyze = await screen.findByRole("button", { name: strings.events.analyze });
    await waitFor(() => expect(analyze).toBeEnabled()); // l'evento è caricato
    fireEvent.click(analyze);
    await waitFor(() => expect(createRun).toHaveBeenCalledTimes(1));
    // la vista passa a SCENARIO: cornice, banner, le card dell'analisi e non più quelle dei tratti
    expect(await screen.findByTestId("scenario-frame")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /SCENARIO/ })).toHaveAttribute("aria-checked", "true");
    // (la card passa da «in lettura» a «pronta» e si rimonta: si rilegge l'elemento a ogni tentativo)
    await waitFor(() =>
      expect(screen.getByText(strings.metrics.cards.vehicleHours)).toBeInTheDocument(),
    );
    expect(screen.queryByText(copy.cards.meanSpeed)).not.toBeInTheDocument();
  });

  it("una lettura che fallisce dopo che i tratti c'erano: gli ultimi dati diventano «parziali», col chip", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const { client } = shell();
      await screen.findByText(copy.panel.slowedTitle);
      expect(
        screen.queryByRole("button", { name: /Fonte non disponibile/ }),
      ).not.toBeInTheDocument();
      vi.spyOn(client, "liveFlow").mockRejectedValue(new Error("giù"));
      await vi.advanceTimersByTimeAsync(60_000);
      expect(await screen.findByText(copy.panel.partialTitle)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /Fonte non disponibile/ })).toBeInTheDocument();
      // gli ultimi numeri restano visibili (con la loro ora), non si cancellano
      expect(screen.getByText(copy.cards.meanSpeed)).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("in SCENARIO non si chiede mai nulla a LIVE e si vedono le card dell'analisi", async () => {
    const { liveFlow } = shell("fresh", "scenario");
    await screen.findByText(strings.metrics.cards.vehicleHours);
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 50));
    });
    expect(liveFlow).not.toHaveBeenCalled();
    expect(screen.queryByText(copy.cards.meanSpeed)).not.toBeInTheDocument();
  });
});
