import { TriangleAlert } from "lucide-react";
import type { ChatErrorKind } from "@/api/chat";
import { GhostButton } from "@/components/GhostButton";
import { LOGIN_URL } from "@/config";
import { strings } from "@/strings";

const TEXT: Record<ChatErrorKind, string> = {
  unavailable: strings.errors.unavailable,
  offline: strings.errors.offline,
  rate_limit: strings.errors.rateLimit,
  auth: strings.errors.auth,
};

interface ErrorNoticeProps {
  kind: ChatErrorKind;
  /** «Riprova» solo sull'ultimo errore e quando non si sta già aspettando una risposta. */
  canRetry: boolean;
  onRetry: () => void;
}

export function ErrorNotice({ kind, canRetry, onRetry }: ErrorNoticeProps) {
  return (
    <div className="flex flex-col items-start gap-2">
      <div role="alert" className="flex items-start gap-2 text-xs text-danger">
        <TriangleAlert
          aria-hidden="true"
          size={16}
          strokeWidth={1.5}
          className="mt-0.5 flex-none"
        />
        {TEXT[kind]}
      </div>
      {kind === "auth" ? (
        <a href={LOGIN_URL} className="text-md">
          {strings.errors.login}
        </a>
      ) : (
        canRetry && <GhostButton onClick={onRetry}>{strings.errors.retry}</GhostButton>
      )}
    </div>
  );
}
