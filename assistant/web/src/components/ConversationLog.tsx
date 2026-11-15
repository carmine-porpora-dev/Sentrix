import { useEffect, useRef } from "react";
import { AssistantMessage } from "@/components/AssistantMessage";
import { ErrorNotice } from "@/components/ErrorNotice";
import { TypingIndicator } from "@/components/TypingIndicator";
import type { Message } from "@/features/chat/useChat";
import { strings } from "@/strings";

interface ConversationLogProps {
  messages: Message[];
  waiting: boolean;
  onChoose: (choice: string) => void;
  onRetry: () => void;
}

/** I messaggi della conversazione, in un'area che scorre senza barra e resta sull'ultimo messaggio. */
export function ConversationLog({ messages, waiting, onChoose, onRetry }: ConversationLogProps) {
  const log = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const element = log.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [messages, waiting]);

  return (
    <div
      ref={log}
      role="log"
      aria-live="polite"
      aria-label={strings.conversation.log}
      className="no-scrollbar relative z-[1] flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-4 pb-4 pt-2"
    >
      {messages.map((message, index) => {
        const last = index === messages.length - 1;
        if (message.role === "user") {
          return (
            <div
              key={message.id}
              className="max-w-[85%] self-end whitespace-pre-wrap rounded-card bg-chat-user-fill px-3.5 py-2.5 [overflow-wrap:anywhere]"
            >
              {message.text}
            </div>
          );
        }
        if (message.role === "error") {
          return (
            <ErrorNotice
              key={message.id}
              kind={message.kind}
              canRetry={last && !waiting}
              onRetry={onRetry}
            />
          );
        }
        return (
          <AssistantMessage
            key={message.id}
            text={message.text}
            sources={message.sources}
            choices={message.choices}
            showChoices={last && !waiting}
            disabled={waiting}
            onChoose={onChoose}
          />
        );
      })}
      {waiting && <TypingIndicator />}
    </div>
  );
}
