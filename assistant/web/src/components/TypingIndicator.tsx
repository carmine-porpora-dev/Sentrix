import { strings } from "@/strings";

const DELAYS = ["0s", "0.2s", "0.4s"];

export function TypingIndicator() {
  return (
    <div
      role="status"
      aria-label={strings.conversation.typing}
      className="flex h-6 items-center gap-1.5"
    >
      {DELAYS.map((delay) => (
        <span
          key={delay}
          className="typing-dot size-2 animate-typing rounded-full bg-text-secondary"
          style={{ animationDelay: delay }}
        />
      ))}
    </div>
  );
}
