import { CHAT_PATH, REQUEST_TIMEOUT_MS } from "@/config";

export type SourceKind = "real" | "estimate" | "simulated";
export type Needs = "time" | "place_choice" | null;

export interface Source {
  label: string;
  kind: SourceKind;
  as_of: string;
  value?: string | number | null;
}

/** La risposta di `POST /assistente/api/chat` (10 §5.3). La mappa non è prevista (decisione del
 * proprietario, 15/11): il campo `route` non si legge. */
export interface ChatResponse {
  conversation_id: string;
  text: string;
  sources: Source[];
  needs: Needs;
  choices: string[];
}

export interface ChatRequest {
  conversationId?: string;
  message: string;
  signal?: AbortSignal;
}

export type ChatClient = (request: ChatRequest) => Promise<ChatResponse>;

export type ChatErrorKind = "offline" | "rate_limit" | "auth" | "unavailable";

export class ChatError extends Error {
  readonly kind: ChatErrorKind;
  constructor(kind: ChatErrorKind) {
    super(kind);
    this.name = "ChatError";
    this.kind = kind;
  }
}

const KINDS: readonly string[] = ["real", "estimate", "simulated"];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseSource(value: unknown): Source | null {
  if (!isRecord(value)) return null;
  const { label, kind, as_of: asOf, value: shown } = value;
  if (typeof label !== "string" || typeof kind !== "string" || !KINDS.includes(kind)) return null;
  const source: Source = {
    label,
    kind: kind as SourceKind,
    as_of: typeof asOf === "string" ? asOf : "",
  };
  if (typeof shown === "string" || typeof shown === "number") source.value = shown;
  return source;
}

/** Controlla la forma della risposta: una risposta storta diventa un errore, non un'interfaccia rotta. */
export function parseChatResponse(body: unknown): ChatResponse {
  if (
    !isRecord(body) ||
    typeof body.text !== "string" ||
    typeof body.conversation_id !== "string"
  ) {
    throw new ChatError("unavailable");
  }
  const sources = Array.isArray(body.sources)
    ? body.sources.map(parseSource).filter((item): item is Source => item !== null)
    : [];
  const needs = body.needs === "time" || body.needs === "place_choice" ? body.needs : null;
  const choices = Array.isArray(body.choices)
    ? body.choices.filter((item): item is string => typeof item === "string" && item.trim() !== "")
    : [];
  return { conversation_id: body.conversation_id, text: body.text, sources, needs, choices };
}

function errorKindFor(status: number): ChatErrorKind {
  if (status === 401 || status === 403) return "auth";
  if (status === 429) return "rate_limit";
  return "unavailable";
}

export function chatUrl(): string {
  return `${import.meta.env.BASE_URL}${CHAT_PATH}`;
}

/** Il client vero: `POST /assistente/api/chat` con la sessione di Sentrix (stesso dominio). */
export const sendChat: ChatClient = async ({ conversationId, message, signal }) => {
  const timeout = new AbortController();
  const timer = setTimeout(() => timeout.abort(), REQUEST_TIMEOUT_MS);
  const onAbort = () => timeout.abort();
  signal?.addEventListener("abort", onAbort);
  try {
    let response: Response;
    try {
      response = await fetch(chatUrl(), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ conversation_id: conversationId, message }),
        signal: timeout.signal,
      });
    } catch (error) {
      if (signal?.aborted) throw error;
      throw new ChatError(timeout.signal.aborted ? "unavailable" : "offline");
    }
    if (!response.ok) throw new ChatError(errorKindFor(response.status));
    let body: unknown;
    try {
      body = await response.json();
    } catch {
      throw new ChatError("unavailable");
    }
    return parseChatResponse(body);
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onAbort);
  }
};
