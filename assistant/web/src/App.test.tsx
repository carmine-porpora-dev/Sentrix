import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ChatError, type ChatClient, type ChatResponse } from "@/api/chat";
import { App } from "@/App";
import { setCompact } from "@/test/setup";

const ANSWER: ChatResponse = {
  conversation_id: "c1",
  text: "Da [[luogo:Piazza Garibaldi]] servono circa 10,2 min.\n\n1. Percorri [[strada:Via Nuova Marina]].\n2. Arrivi su [[strada:Via Tasso]].",
  sources: [
    {
      label: "Tempo del percorso",
      kind: "simulated",
      as_of: "2026-09-26T13:30:00+02:00",
      value: "10,2 min",
    },
  ],
  needs: null,
  choices: [],
};

const field = () => screen.getByLabelText("Scrivi all'Assistente");
const send = () => screen.getByRole("button", { name: "Invia" });

function ask(text: string) {
  fireEvent.change(field(), { target: { value: text } });
  fireEvent.click(send());
}

describe("App", () => {
  it("parte dalla vista iniziale: benvenuto, campo e riga dello scenario simulato", () => {
    render(<App client={vi.fn()} />);
    expect(screen.getByRole("main")).toHaveAttribute("data-view", "home");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Ciao!Dove vuoi andare?");
    expect(
      screen.getByText("Dimmi da dove parti e dove vai: ti trovo il percorso migliore."),
    ).toBeInTheDocument();
    expect(screen.getByText("SIMULAZIONE")).toBeInTheDocument();
    expect(
      screen.getByText("Scenario simulato: Regate preliminari — sabato 26/09/2026"),
    ).toBeInTheDocument();
    expect(send()).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Nuova conversazione" })).not.toBeInTheDocument();
    expect(screen.queryByRole("log")).not.toBeInTheDocument();
  });

  it("al primo messaggio passa alla conversazione: bolla, attesa, risposta con chip e fonti", async () => {
    let resolve!: (value: ChatResponse) => void;
    const client = vi.fn<ChatClient>().mockReturnValue(new Promise((res) => (resolve = res)));
    render(<App client={client} />);
    ask("Da piazza Garibaldi a via Tasso alle 13:30");

    expect(screen.getByRole("main")).toHaveAttribute("data-view", "conversation");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Assistente");
    const log = screen.getByRole("log");
    expect(within(log).getByText("Da piazza Garibaldi a via Tasso alle 13:30")).toBeInTheDocument();
    expect(screen.getByRole("status", { name: "Sto scrivendo" })).toBeInTheDocument();
    expect(field()).toHaveValue("");
    expect(send()).toBeDisabled();
    // la riga dello scenario resta sempre visibile
    expect(screen.getByText("SIMULAZIONE")).toBeInTheDocument();

    resolve(ANSWER);
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    expect(document.querySelectorAll("[data-chip]")).toHaveLength(3);
    // il numero compare nel testo e nel valore della fonte, entrambi in monospazio
    expect(within(log).getAllByText("10,2 min", { selector: "span.font-mono" })).toHaveLength(2);
    const sources = screen.getByRole("region", { name: "Fonti" });
    expect(sources).toHaveTextContent("SIMULATO");
    expect(sources).toHaveTextContent("Tempo del percorso");
    expect(client.mock.calls[0][0]).toMatchObject({
      message: "Da piazza Garibaldi a via Tasso alle 13:30",
    });
  });

  it("su schermo largo Invio invia; su telefono no", () => {
    const client = vi.fn<ChatClient>().mockReturnValue(new Promise(() => {}));
    const { unmount } = render(<App client={client} />);
    fireEvent.change(field(), { target: { value: "Ciao" } });
    fireEvent.keyDown(field(), { key: "Enter" });
    expect(client).toHaveBeenCalledTimes(1);
    unmount();

    setCompact(true);
    const phoneClient = vi.fn<ChatClient>();
    render(<App client={phoneClient} />);
    fireEvent.change(field(), { target: { value: "Ciao" } });
    fireEvent.keyDown(field(), { key: "Enter" });
    expect(phoneClient).not.toHaveBeenCalled();
    expect(send()).toBeEnabled();
  });

  it("«Nuova conversazione» torna alla vista iniziale e svuota il campo", async () => {
    const client = vi.fn<ChatClient>().mockResolvedValue(ANSWER);
    render(<App client={client} />);
    ask("Ciao");
    await waitFor(() => expect(screen.getByRole("region", { name: "Fonti" })).toBeInTheDocument());
    fireEvent.change(field(), { target: { value: "bozza" } });
    fireEvent.click(screen.getByRole("button", { name: "Nuova conversazione" }));
    expect(screen.getByRole("main")).toHaveAttribute("data-view", "home");
    expect(field()).toHaveValue("");
    expect(screen.queryByRole("log")).not.toBeInTheDocument();
  });

  it("senza risposta mostra l'errore e «Riprova» rimanda la stessa domanda", async () => {
    const client = vi
      .fn<ChatClient>()
      .mockRejectedValueOnce(new ChatError("unavailable"))
      .mockResolvedValueOnce(ANSWER);
    render(<App client={client} />);
    ask("Ciao");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Non sono riuscito a rispondere. Riprova tra poco.",
    );
    fireEvent.click(screen.getByRole("button", { name: "Riprova" }));
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    expect(await screen.findByRole("region", { name: "Fonti" })).toBeInTheDocument();
    expect(client).toHaveBeenCalledTimes(2);
    expect(within(screen.getByRole("log")).getAllByText("Ciao")).toHaveLength(1);
  });

  it.each([
    ["offline", "L'Assistente non è disponibile senza connessione."],
    ["rate_limit", "Troppe domande in poco tempo. Attendi qualche secondo."],
  ] as const)("l'errore «%s» ha il suo messaggio", async (kind, message) => {
    render(<App client={vi.fn<ChatClient>().mockRejectedValue(new ChatError(kind))} />);
    ask("Ciao");
    expect(await screen.findByRole("alert")).toHaveTextContent(message);
  });

  it("senza sessione rimanda all'accesso di Sentrix", async () => {
    render(<App client={vi.fn<ChatClient>().mockRejectedValue(new ChatError("auth"))} />);
    ask("Ciao");
    await screen.findByRole("alert");
    expect(screen.getByRole("link", { name: "Accedi a Sentrix" })).toHaveAttribute("href", "/");
    expect(screen.queryByRole("button", { name: "Riprova" })).not.toBeInTheDocument();
  });

  it("le scelte rapide inviano la scelta come nuovo messaggio", async () => {
    const client = vi
      .fn<ChatClient>()
      .mockResolvedValueOnce({
        ...ANSWER,
        text: "Quale intendi?",
        sources: [],
        needs: "place_choice",
        choices: ["Via Tasso", "Via Foria"],
      })
      .mockResolvedValueOnce(ANSWER);
    render(<App client={client} />);
    ask("via");
    fireEvent.click(await screen.findByRole("button", { name: "Via Tasso" }));
    await waitFor(() => expect(client).toHaveBeenCalledTimes(2));
    expect(client.mock.calls[1][0]).toMatchObject({ message: "Via Tasso", conversationId: "c1" });
    await waitFor(() =>
      expect(screen.queryByRole("group", { name: "Scelte rapide" })).not.toBeInTheDocument(),
    );
  });

  it("l'area dei messaggi è un log accessibile", async () => {
    render(<App client={vi.fn<ChatClient>().mockResolvedValue(ANSWER)} />);
    ask("Ciao");
    const log = await screen.findByRole("log");
    expect(log).toHaveAttribute("aria-live", "polite");
  });
});
