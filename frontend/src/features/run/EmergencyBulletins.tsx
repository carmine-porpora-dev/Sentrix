import { Check, CheckCheck, ChevronDown, Send, type LucideIcon } from "lucide-react";
import { useState } from "react";
import { ApiError } from "@/api/errors";
import type { Notification } from "@/api/types";
import { Button } from "@/components/Button";
import { Icon } from "@/components/Icon";
import { StateChip, type ChipTone } from "@/components/StateChip";
import { useAcknowledge } from "@/features/run/queries";
import { formatClock } from "@/lib/format";
import { cn } from "@/lib/utils";
import { strings } from "@/i18n/it";

const copy = strings.panels.ops.emergency;

const STATE: Record<string, { tone: ChipTone; icon: LucideIcon }> = {
  SENT: { tone: "pending", icon: Send },
  DELIVERED: { tone: "neutral", icon: Check },
  ACKNOWLEDGED: { tone: "accepted", icon: CheckCheck },
};

/** Una scheda (un gruppo, non un `article`: quelli della scheda Operations sono le richieste) per destinatario del bollettino viabilità (spech 12.3): chi lo riceve, in che stato è,
 * il testo (chiuso finché non lo si apre: è lungo e lo stesso per tutti) e «Conferma ricezione». È
 * una simulazione: nessun invio a enti reali, lo dicono il badge della sezione e la riga di nota. */
export function BulletinCard({ bulletin, runId }: { bulletin: Notification; runId: string }) {
  const [open, setOpen] = useState(false);
  const acknowledge = useAcknowledge(runId);
  const name = bulletin.recipient_label ?? bulletin.recipient_id;
  const state = STATE[bulletin.state];
  const confirmed = bulletin.state === "ACKNOWLEDGED";
  // 409: già confermato (da un'altra scheda aperta): la lista si rilegge e il pulsante sparisce
  const failed =
    acknowledge.isError &&
    !(acknowledge.error instanceof ApiError && acknowledge.error.status === 409);
  return (
    <div
      role="group"
      aria-label={name}
      className="flex flex-col gap-space-8 rounded-card bg-surface-2 p-space-16"
    >
      <div className="flex items-start gap-space-12">
        <div className="flex min-w-0 flex-1 flex-col">
          <span className="text-sm font-semibold text-text-primary">{name}</span>
          <span className="text-xs text-text-secondary">
            {copy.sentAt(formatClock(bulletin.created_at))}
          </span>
        </div>
        {state && (
          <StateChip tone={state.tone} icon={state.icon} label={copy.state[bulletin.state]} />
        )}
      </div>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="flex w-fit items-center gap-1.5 rounded-control text-xs text-text-secondary transition-base hover:text-text-primary"
      >
        <Icon
          icon={ChevronDown}
          size="inline"
          className={cn("transition-base", open && "rotate-180")}
        />
        {open ? copy.hideText : copy.showText}
      </button>
      {open && (
        <p className="whitespace-pre-line rounded-control bg-surface-1 p-space-12 text-sm text-text-primary">
          {bulletin.text}
        </p>
      )}
      {!confirmed && (
        <div className="flex flex-col gap-space-8">
          <Button
            variant="stroke"
            icon={CheckCheck}
            loading={acknowledge.isPending}
            onClick={() => acknowledge.mutate(bulletin.id)}
          >
            {copy.acknowledge}
          </Button>
          {failed && (
            <p role="alert" className="text-sm text-status-rejected">
              {copy.acknowledgeFailed}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
