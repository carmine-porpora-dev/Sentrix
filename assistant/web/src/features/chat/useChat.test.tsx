import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ChatError, type ChatClient, type ChatResponse } from "@/api/chat";
import { useChat } from "@/features/chat/useChat";

const reply = (text: string, extra: Partial<ChatResponse> = {}): ChatResponse => ({
  conversation_id: "c1",
  text,
  sources: [],
  needs: null,
  choices: [],
  ...extra,
});

function deferred() {
  let resolve!: (value: ChatResponse) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<ChatResponse>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe("useChat", () => {
  it("manda la domanda e aggiunge la risposta", async () => {
    const client = vi.fn<ChatClient>().mockResolvedValue(reply("Vai dritto"));
    const { result } = renderHook(() => useChat(client));
    act(() => result.current.send("  Come arrivo?  "));
    expect(result.current.waiting).toBe(true);
    expect(result.current.messages).toMatchObject([{ role: "user", text: "Come arrivo?" }]);
    await waitFor(() => expect(result.current.waiting).toBe(false));
    expect(result.current.messages.map((m) => m.role)).toEqual(["user", "assistant"]);
    expect(client.mock.calls[0][0]).toMatchObject({ message: "Come arrivo?" });
    expect(client.mock.calls[0][0].conversationId).toBeUndefined();
  });

  it("riusa l'identificativo di conversazione nelle domande successive", async () => {
    const client = vi.fn<ChatClient>().mockResolvedValue(reply("ok"));
    const { result } = renderHook(() => useChat(client));
    act(() => result.current.send("uno"));
    await waitFor(() => expect(result.current.waiting).toBe(false));
    act(() => result.current.send("due"));
    await waitFor(() => expect(result.current.waiting).toBe(false));
    expect(client.mock.calls[1][0].conversationId).toBe("c1");
  });

  it("ignora testo vuoto, troppo lungo e un secondo invio mentre aspetta", async () => {
    const pending = deferred();
    const client = vi.fn<ChatClient>().mockReturnValue(pending.promise);
    const { result } = renderHook(() => useChat(client));
    act(() => result.current.send("   "));
    act(() => result.current.send("a".repeat(501)));
    expect(client).not.toHaveBeenCalled();
    act(() => result.current.send("uno"));
    act(() => result.current.send("due"));
    expect(client).toHaveBeenCalledTimes(1);
    expect(result.current.messages).toHaveLength(1);
    await act(async () => pending.resolve(reply("ok")));
  });

  it("un errore diventa un messaggio di errore con il suo tipo", async () => {
    const client = vi.fn<ChatClient>().mockRejectedValue(new ChatError("rate_limit"));
    const { result } = renderHook(() => useChat(client));
    act(() => result.current.send("ciao"));
    await waitFor(() => expect(result.current.waiting).toBe(false));
    expect(result.current.messages[1]).toMatchObject({ role: "error", kind: "rate_limit" });
  });

  it("un errore qualunque è «unavailable»", async () => {
    const client = vi.fn<ChatClient>().mockRejectedValue(new Error("boom"));
    const { result } = renderHook(() => useChat(client));
    act(() => result.current.send("ciao"));
    await waitFor(() => expect(result.current.waiting).toBe(false));
    expect(result.current.messages[1]).toMatchObject({ role: "error", kind: "unavailable" });
  });

  it("«Riprova» toglie l'errore e rimanda la stessa domanda senza una seconda bolla", async () => {
    const client = vi
      .fn<ChatClient>()
      .mockRejectedValueOnce(new ChatError("offline"))
      .mockResolvedValueOnce(reply("Eccomi"));
    const { result } = renderHook(() => useChat(client));
    act(() => result.current.send("ciao"));
    await waitFor(() => expect(result.current.waiting).toBe(false));
    act(() => result.current.retry());
    await waitFor(() => expect(result.current.waiting).toBe(false));
    expect(result.current.messages.map((m) => m.role)).toEqual(["user", "assistant"]);
    expect(client.mock.calls[1][0].message).toBe("ciao");
  });

  it("«Nuova conversazione» azzera tutto e una risposta in ritardo non riappare", async () => {
    const pending = deferred();
    const client = vi
      .fn<ChatClient>()
      .mockReturnValueOnce(pending.promise)
      .mockResolvedValueOnce(reply("nuova"));
    const { result } = renderHook(() => useChat(client));
    act(() => result.current.send("vecchia"));
    act(() => result.current.reset());
    expect(result.current.messages).toEqual([]);
    expect(result.current.waiting).toBe(false);
    expect(client.mock.calls[0][0].signal?.aborted).toBe(true);
    await act(async () => pending.resolve(reply("in ritardo", { conversation_id: "vecchia" })));
    expect(result.current.messages).toEqual([]);
    act(() => result.current.send("nuova"));
    await waitFor(() => expect(result.current.waiting).toBe(false));
    expect(client.mock.calls[1][0].conversationId).toBeUndefined();
    expect(result.current.messages).toHaveLength(2);
  });

  it("tiene fonti e scelte rapide della risposta", async () => {
    const sources = [{ label: "Tempo", kind: "simulated" as const, as_of: "x" }];
    const client = vi
      .fn<ChatClient>()
      .mockResolvedValue(reply("Quale?", { sources, choices: ["A", "B"], needs: "place_choice" }));
    const { result } = renderHook(() => useChat(client));
    act(() => result.current.send("ciao"));
    await waitFor(() => expect(result.current.waiting).toBe(false));
    expect(result.current.messages[1]).toMatchObject({ sources, choices: ["A", "B"] });
  });
});
