import clsx from "clsx";
import { strings } from "@/strings";

/** L'aeroplanino di carta (Tabler `paper-plane`): mai una freccia verso l'alto. */
function PaperPlane() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="22"
      height="22"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M10 14l11 -11" />
      <path d="M21 3l-6.5 18a.55.55 0 0 1 -1 0l-3.5 -7l-7 -3.5a.55.55 0 0 1 0 -1l18 -6.5" />
    </svg>
  );
}

export function SendButton({ enabled, onClick }: { enabled: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-label={strings.composer.send}
      disabled={!enabled}
      onClick={onClick}
      className={clsx(
        "flex size-10 flex-none items-center justify-center rounded-control border-0 p-0 transition-colors",
        enabled
          ? "cursor-pointer bg-accent text-bg hover:bg-accent-hover"
          : "cursor-not-allowed bg-transparent text-text-muted",
      )}
    >
      <PaperPlane />
    </button>
  );
}
