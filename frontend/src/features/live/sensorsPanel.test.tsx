import { render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ApiClient } from "@/api/client";
import { ApiError } from "@/api/errors";
import { createMockClient, type MockLiveMode } from "@/api/mock";
import { ApiProvider } from "@/api/provider";
import { DataSources } from "@/features/live/DataSources";
import { LiveOperations } from "@/features/live/LiveOperations";
import { AppShell } from "@/features/shell/AppShell";
import { ShellProvider } from "@/features/shell/ShellProvider";
import { strings } from "@/i18n/it";

// Il riquadro «Fonti dati» della scheda Operations in LIVE (spech 11.5): TomTom attivo (REALE), i
// sensori propri previsti (nessun badge, nessun numero). In SCENARIO nulla cambia.

const copy = strings.live;

function client(mode: MockLiveMode = "fresh", failSensors = false): ApiClient {
  const base = createMockClient({ authenticated: true, liveMode: mode });
  if (failSensors) {
    base.listSensors = () =>
      Promise.reject(new ApiError(503, { code: "DATA_UNAVAILABLE", message: "non disponibile" }));
  }
  return base;
}

const show = (node: React.ReactNode, api: ApiClient = client()) =>
  render(<ApiProvider client={api}>{node}</ApiProvider>);

const sourceBox = () => screen.getByRole("region", { name: copy.sources.title });
const row = (name: string) => {
  const found = [...sourceBox().querySelectorAll("li")].find((li) =>
    li.textContent?.includes(name),
  );
  if (!found) throw new Error(`riga non trovata: ${name}`);
  return found as HTMLElement;
};

describe("DataSources: il riquadro «Fonti dati»", () => {
  it("TomTom è attivo (REALE); sonde GPS, tornelli, contapersone e sensori Tangenziale sono previsti", async () => {
    show(<DataSources />);
    await waitFor(() => expect(row(copy.sensors.types.ramp_counter)).toBeInTheDocument());
    expect(screen.getByRole("heading", { name: copy.sources.title })).toBeInTheDocument();

    // l'elenco dei sensori e i tratti TomTom arrivano da due letture: si aspettano tutte e due
    const tomtom = row(copy.source);
    expect(await within(tomtom).findByText(copy.sources.tomtom.ok)).toBeInTheDocument();
    expect(within(tomtom).getByText(strings.metrics.badges.real)).toBeInTheDocument();

    for (const label of Object.values(copy.sensors.types)) {
      const planned = row(label);
      expect(within(planned).getByText(copy.sources.planned)).toBeInTheDocument();
      // un sensore che non c'è non produce dati: nessun badge REALE/STIMA/SIMULATO
      for (const badge of ["real", "estimate", "simulated"] as const) {
        expect(within(planned).queryByText(strings.metrics.badges[badge])).not.toBeInTheDocument();
      }
    }
    // l'ordine è quello di 11.2: TomTom, sonde GPS, tornelli, contapersone, sensori Tangenziale
    expect(
      [...sourceBox().querySelectorAll("li")].map((li) => li.getAttribute("data-source")),
    ).toEqual(["tomtom", "gps_probe", "turnstile", "people_counter", "ramp_counter"]);
    expect(screen.getByText(copy.sources.hint)).toBeInTheDocument();
  });

  it("nessun numero: né conteggi dei sensori né valori", async () => {
    show(<DataSources />);
    await waitFor(() => expect(row(copy.sensors.types.gps_probe)).toBeInTheDocument());
    expect(sourceBox().querySelector("[data-measured]")).toBeNull();
    expect(sourceBox().textContent).not.toMatch(/\d/);
  });

  it("con lo snapshot TomTom è «ultimo dato disponibile» (08 4), sempre REALE", async () => {
    show(<DataSources />, client("snapshot"));
    await waitFor(() =>
      expect(within(row(copy.source)).getByText(copy.sources.tomtom.partial)).toBeInTheDocument(),
    );
    expect(within(row(copy.source)).getByText(strings.metrics.badges.real)).toBeInTheDocument();
  });

  it("senza nessun dato TomTom è «non disponibile», senza badge", async () => {
    show(<DataSources />, client("unavailable"));
    await waitFor(() =>
      expect(within(row(copy.source)).getByText(copy.sources.tomtom.none)).toBeInTheDocument(),
    );
    expect(within(row(copy.source)).queryByText(strings.metrics.badges.real)).toBeNull();
  });

  it("mentre legge non dice né «attivo» né «non disponibile»", () => {
    show(<DataSources />);
    expect(within(row(copy.source)).getByText(copy.sources.loading)).toBeInTheDocument();
    expect(screen.queryByText(copy.sources.tomtom.ok)).not.toBeInTheDocument();
  });

  it("se l'elenco dei sensori non si legge restano TomTom e una nota: LIVE non si rompe", async () => {
    show(<DataSources />, client("fresh", true));
    await screen.findByText(copy.sources.sensorsUnavailable);
    expect(await within(row(copy.source)).findByText(copy.sources.tomtom.ok)).toBeInTheDocument();
    expect(sourceBox().querySelectorAll("li")).toHaveLength(1);
    expect(screen.queryByText(copy.sources.hint)).not.toBeInTheDocument();
  });
});

describe("LiveOperations: lo stato dei tratti e, sotto, le fonti", () => {
  it("il pannello dei tratti c'è com'era e il riquadro sta dopo", async () => {
    show(<LiveOperations />);
    await screen.findByText(strings.live.panel.slowedTitle);
    const heading = screen.getByRole("heading", { name: strings.live.panel.slowedTitle });
    const sources = sourceBox();
    // il riquadro viene dopo l'elenco dei tratti rallentati
    expect(
      heading.compareDocumentPosition(sources) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("anche senza dati (messaggio «Nessun dato») il riquadro c'è", async () => {
    show(<LiveOperations />, client("unavailable"));
    await screen.findByText(strings.live.panel.noneTitle);
    expect(sourceBox()).toBeInTheDocument();
  });
});

describe("nel guscio: solo in LIVE", () => {
  it("in LIVE la scheda Operations ha «Fonti dati» e l'elenco si legge una volta", async () => {
    const api = client();
    const listSensors = vi.spyOn(api, "listSensors");
    show(
      <ShellProvider initial={{ mode: "live", tab: "operations" }}>
        <AppShell />
      </ShellProvider>,
      api,
    );
    expect(await screen.findByRole("region", { name: copy.sources.title })).toBeInTheDocument();
    await waitFor(() => expect(listSensors).toHaveBeenCalled());
    expect(listSensors).toHaveBeenCalledTimes(1); // riquadro e mappa leggono la stessa cache
  });

  it("in SCENARIO non c'è il riquadro e non si chiede l'elenco dei sensori", async () => {
    const api = client();
    const listSensors = vi.spyOn(api, "listSensors");
    show(
      <ShellProvider initial={{ mode: "scenario", tab: "operations" }}>
        <AppShell />
      </ShellProvider>,
      api,
    );
    await screen.findByRole("tab", { name: strings.shell.tabs.operations });
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(screen.queryByRole("region", { name: copy.sources.title })).not.toBeInTheDocument();
    expect(screen.queryByText(copy.sensors.layer)).not.toBeInTheDocument();
    expect(listSensors).not.toHaveBeenCalled();
  });
});
