import clsx from "clsx";
import { useState } from "react";
import type { ChatClient } from "@/api/chat";
import { ChatHeader } from "@/components/ChatHeader";
import { Composer } from "@/components/Composer";
import { ConversationLog } from "@/components/ConversationLog";
import { SimulationBanner } from "@/components/SimulationBanner";
import { Welcome } from "@/components/Welcome";
import { COMPACT_QUERY, MAX_MESSAGE_LENGTH } from "@/config";
import { useChat } from "@/features/chat/useChat";
import { useMediaQuery, useViewportHeight } from "@/lib/hooks";

export function App({ client }: { client?: ChatClient }) {
  const chat = useChat(client);
  const compact = useMediaQuery(COMPACT_QUERY);
  useViewportHeight();
  const [draft, setDraft] = useState("");

  const home = chat.messages.length === 0 && !chat.waiting;
  const canSend = draft.trim().length > 0 && draft.length <= MAX_MESSAGE_LENGTH && !chat.waiting;

  const submit = () => {
    if (!canSend) return;
    chat.send(draft);
    setDraft("");
  };

  const newConversation = () => {
    chat.reset();
    setDraft("");
  };

  return (
    <div className="flex h-[var(--app-height,100dvh)] items-center justify-center bg-bg sm:p-6">
      <main
        data-view={home ? "home" : "conversation"}
        className={clsx(
          "relative flex h-full min-h-0 w-full flex-col overflow-hidden bg-bg pt-[env(safe-area-inset-top)]",
          "sm:rounded-card sm:border sm:border-border-card sm:pt-0",
          home
            ? "sm:h-[min(540px,100%)] sm:w-[min(560px,100%)]"
            : "sm:h-[min(680px,100%)] sm:w-[min(420px,100%)]",
        )}
      >
        {home ? (
          <>
            <SimulationBanner />
            <Welcome />
          </>
        ) : (
          <>
            <ChatHeader onNewConversation={newConversation} />
            <SimulationBanner />
            <ConversationLog
              messages={chat.messages}
              waiting={chat.waiting}
              onChoose={chat.send}
              onRetry={chat.retry}
            />
          </>
        )}
        <div
          className={clsx(
            "relative z-[2] flex-none px-4 pb-6 pt-4",
            compact && "pb-[calc(24px+env(safe-area-inset-bottom))]",
            !home && "border-t border-border-strong",
          )}
        >
          <Composer
            value={draft}
            onChange={setDraft}
            onSend={submit}
            canSend={canSend}
            compact={compact}
          />
        </div>
      </main>
    </div>
  );
}
