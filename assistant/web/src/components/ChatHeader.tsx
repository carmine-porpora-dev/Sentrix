import { RotateCcw } from "lucide-react";
import { Logo } from "@/components/Logo";
import { strings } from "@/strings";

export function ChatHeader({ onNewConversation }: { onNewConversation: () => void }) {
  return (
    <header className="relative z-[2] flex h-12 flex-none items-center justify-between px-4">
      <div className="flex min-w-0 items-center gap-2.5">
        <Logo width={16} height={24} />
        <h1 className="m-0 text-md font-semibold">{strings.header.title}</h1>
      </div>
      <button
        type="button"
        aria-label={strings.header.newConversation}
        title={strings.header.newConversation}
        onClick={onNewConversation}
        className="-mr-2 flex size-10 cursor-pointer items-center justify-center rounded-control border-0 bg-transparent p-0 text-text-secondary transition-colors hover:bg-surface-2 hover:text-text"
      >
        <RotateCcw aria-hidden="true" size={20} strokeWidth={1.5} />
      </button>
    </header>
  );
}
