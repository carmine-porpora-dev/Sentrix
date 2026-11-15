import { useCallback, useEffect, useRef, useState } from "react";
import { ChatError, sendChat, type ChatClient, type ChatErrorKind, type Source } from "@/api/chat";
import { MAX_MESSAGE_LENGTH } from "@/config";

export type Message =
  | { id: number; role: "user"; text: string }
  | { id: number; role: "assistant"; text: string; sources: Source[]; choices: string[] }
  | { id: number; role: "error"; kind: ChatErrorKind };

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

/** Lo stato della conversazione: messaggi, attesa, invio, nuovo tentativo e «Nuova conversazione». */
export function useChat(client: ChatClient = sendChat) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [waiting, setWaiting] = useState(false);

  const nextId = useRef(1);
  const conversationId = useRef<string | undefined>(undefined);
  const busy = useRef(false);
  const generation = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const lastQuestion = useRef("");

  const ask = useCallback(
    async (text: string) => {
      busy.current = true;
      setWaiting(true);
      const mine = generation.current;
      const abort = new AbortController();
      controller.current = abort;
      lastQuestion.current = text;
      try {
        const reply = await client({
          conversationId: conversationId.current,
          message: text,
          signal: abort.signal,
        });
        if (mine !== generation.current) return;
        conversationId.current = reply.conversation_id;
        setMessages((current) => [
          ...current,
          {
            id: nextId.current++,
            role: "assistant",
            text: reply.text,
            sources: reply.sources,
            choices: reply.choices,
          },
        ]);
      } catch (error) {
        if (mine !== generation.current || isAbort(error)) return;
        const kind = error instanceof ChatError ? error.kind : "unavailable";
        setMessages((current) => [...current, { id: nextId.current++, role: "error", kind }]);
      } finally {
        if (mine === generation.current) {
          busy.current = false;
          setWaiting(false);
        }
      }
    },
    [client],
  );

  const send = useCallback(
    (raw: string) => {
      const text = raw.trim();
      if (!text || text.length > MAX_MESSAGE_LENGTH || busy.current) return;
      setMessages((current) => [...current, { id: nextId.current++, role: "user", text }]);
      void ask(text);
    },
    [ask],
  );

  const retry = useCallback(() => {
    if (busy.current || !lastQuestion.current) return;
    setMessages((current) =>
      current.length > 0 && current[current.length - 1].role === "error"
        ? current.slice(0, -1)
        : current,
    );
    void ask(lastQuestion.current);
  }, [ask]);

  const reset = useCallback(() => {
    generation.current += 1;
    controller.current?.abort();
    controller.current = null;
    busy.current = false;
    conversationId.current = undefined;
    lastQuestion.current = "";
    setMessages([]);
    setWaiting(false);
  }, []);

  useEffect(() => () => controller.current?.abort(), []);

  return { messages, waiting, send, retry, reset };
}
