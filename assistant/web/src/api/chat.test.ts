import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ChatError, chatUrl, parseChatResponse, sendChat } from "@/api/chat";

const VALID = {
  conversation_id: "c1",
  text: "Ciao",
  sources: [
    { label: "Tempo", kind: "simulated", as_of: "2026-09-26T13:30:00+02:00", value: "8,0 min" },
  ],
  needs: null,
};

function respond(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

async function kindOf(promise: Promise<unknown>): Promise<string> {
  try {
    await promise;
  } catch (error) {
    if (error instanceof ChatError) return error.kind;
    throw error;
  }
  return "nessun errore";
}

describe("parseChatResponse", () => {
  it("accetta una risposta valida e normalizza i campi mancanti", () => {
    const parsed = parseChatResponse(VALID);
    expect(parsed.text).toBe("Ciao");
    expect(parsed.choices).toEqual([]);
    expect(parsed.needs).toBeNull();
    expect(parsed.sources).toEqual([
      { label: "Tempo", kind: "simulated", as_of: "2026-09-26T13:30:00+02:00", value: "8,0 min" },
    ]);
  });

  it("scarta le fonti con una natura sconosciuta", () => {
    const parsed = parseChatResponse({
      ...VALID,
      sources: [
        { label: "Buona", kind: "real", as_of: "x" },
        { label: "Strana", kind: "certificato", as_of: "x" },
        "non un oggetto",
      ],
    });
    expect(parsed.sources.map((source) => source.label)).toEqual(["Buona"]);
  });

  it("legge le scelte rapide e il bisogno", () => {
    const parsed = parseChatResponse({
      ...VALID,
      needs: "place_choice",
      choices: ["Via Tasso", "", 3, "Via Foria"],
    });
    expect(parsed.needs).toBe("place_choice");
    expect(parsed.choices).toEqual(["Via Tasso", "Via Foria"]);
  });

  it.each([null, "testo", [], {}, { text: "x" }, { conversation_id: "c", text: 4 }])(
    "una risposta storta (%j) è un errore",
    (body) => {
      expect(() => parseChatResponse(body)).toThrow(ChatError);
    },
  );
});

describe("sendChat", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
    vi.useRealTimers();
  });

  it("chiama POST /assistente/api/chat con la conversazione e il messaggio", async () => {
    vi.stubEnv("BASE_URL", "/assistente/");
    vi.mocked(fetch).mockResolvedValue(respond(200, VALID));
    const reply = await sendChat({ conversationId: "c0", message: "Da dove parto?" });
    expect(reply.text).toBe("Ciao");
    expect(chatUrl()).toBe("/assistente/api/chat");
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe("/assistente/api/chat");
    expect(init?.method).toBe("POST");
    expect(init?.credentials).toBe("same-origin");
    expect(JSON.parse(String(init?.body))).toEqual({
      conversation_id: "c0",
      message: "Da dove parto?",
    });
  });

  it("alla prima domanda non manda un identificativo di conversazione", async () => {
    vi.mocked(fetch).mockResolvedValue(respond(200, VALID));
    await sendChat({ message: "Ciao" });
    expect(JSON.parse(String(vi.mocked(fetch).mock.calls[0][1]?.body))).toEqual({
      message: "Ciao",
    });
  });

  it.each([
    [429, "rate_limit"],
    [401, "auth"],
    [403, "auth"],
    [500, "unavailable"],
    [503, "unavailable"],
  ])("lo stato %i diventa %s", async (status, kind) => {
    vi.mocked(fetch).mockResolvedValue(respond(status, { detail: "x" }));
    expect(await kindOf(sendChat({ message: "Ciao" }))).toBe(kind);
  });

  it("senza rete l'errore è «offline»", async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError("Failed to fetch"));
    expect(await kindOf(sendChat({ message: "Ciao" }))).toBe("offline");
  });

  it("un corpo che non è JSON è «unavailable»", async () => {
    vi.mocked(fetch).mockResolvedValue(new Response("<html>", { status: 200 }));
    expect(await kindOf(sendChat({ message: "Ciao" }))).toBe("unavailable");
  });

  it("l'annullamento del chiamante non è un errore dell'assistente", async () => {
    const controller = new AbortController();
    vi.mocked(fetch).mockImplementation(
      (_url, init) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () =>
            reject(new DOMException("annullata", "AbortError")),
          );
        }),
    );
    const pending = sendChat({ message: "Ciao", signal: controller.signal });
    controller.abort();
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
  });

  it("dopo il tempo massimo la richiesta cade con «unavailable»", async () => {
    vi.useFakeTimers();
    vi.mocked(fetch).mockImplementation(
      (_url, init) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () =>
            reject(new DOMException("scaduta", "AbortError")),
          );
        }),
    );
    const outcome = kindOf(sendChat({ message: "Ciao" }));
    await vi.advanceTimersByTimeAsync(36_000);
    expect(await outcome).toBe("unavailable");
  });
});
