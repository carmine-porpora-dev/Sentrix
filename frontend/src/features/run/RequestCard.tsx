import {
  Check,
  CheckCheck,
  Inbox,
  MapPin,
  Play,
  Plus,
  Send,
  X,
  type LucideIcon,
} from "lucide-react";
import { useState } from "react";
import { ApiError } from "@/api/errors";
import { useDepartmentName } from "@/api/queries";
import type { RequestView } from "@/api/types";
import { Button } from "@/components/Button";
import { SelectField } from "@/components/forms/SelectField";
import { FieldMessage, TextField } from "@/components/forms/TextField";
import { Icon } from "@/components/Icon";
import { MeasuredValue } from "@/components/MeasuredValue";
import { StateChip, type ChipTone } from "@/components/StateChip";
import { REJECT_CODES } from "@/features/run/derive";
import type { MeasureEffect } from "@/features/run/effects";
import { useManualResponse } from "@/features/run/queries";
import { DEPARTMENTS } from "@/lib/departments";
import { strings } from "@/i18n/it";

const copy = strings.panels.ops;

const STATE: Record<RequestView["request"]["state"], { tone: ChipTone; icon: LucideIcon }> = {
  CREATED: { tone: "pending", icon: Plus },
  SENT: { tone: "pending", icon: Send },
  RECEIVED: { tone: "pending", icon: Inbox },
  ACCEPTED: { tone: "accepted", icon: Check },
  REJECTED: { tone: "rejected", icon: X },
  IN_PROGRESS: { tone: "pending", icon: Play },
  COMPLETED: { tone: "accepted", icon: CheckCheck },
};

/** Il nome di un tipo di misura del catalogo; uno sconosciuto resta com'è. */
export const measureLabel = (type: string): string =>
  (copy.measureTypes as Record<string, string>)[type] ?? type;

/** Se il sistema conosce il tipo di misura (ha un nome per lui). Le misure reali di un Evento hanno un
 * tipo libero (01 2): uno sconosciuto non ha un nome da mostrare, e il motore non lo modella. */
export const isKnownMeasure = (type: string): boolean => Object.hasOwn(copy.measureTypes, type);

/** Accetta / Rifiuta (con codice e motivo) per una richiesta ferma in `RECEIVED` (04 5). */
function ManualControls({ item, runId }: { item: RequestView; runId: string }) {
  const { request } = item;
  const respond = useManualResponse(runId);
  const [rejecting, setRejecting] = useState(false);
  const codes = REJECT_CODES[request.department] ?? [];
  const [code, setCode] = useState(codes[0] ?? "");
  const [reason, setReason] = useState("");
  const [touched, setTouched] = useState(false);
  const missing = touched && reason.trim() === "";
  // Dopo una risposta riuscita i pulsanti restano spenti finché il run non rilegge lo stato della
  // richiesta (ogni secondo): un secondo clic arriverebbe a una richiesta già decisa (409).
  const answered = respond.isPending || respond.isSuccess;
  const send = (body: Parameters<typeof respond.mutate>[0]["body"]) =>
    respond.mutate({ deptId: request.department, actionId: request.action_id, body });
  const error =
    respond.error instanceof ApiError || respond.error instanceof Error
      ? respond.error.message
      : undefined;

  return (
    <div className="flex flex-col gap-space-8 border-t-hairline border-border pt-space-12">
      {!rejecting ? (
        <div className="flex gap-space-8">
          <Button
            variant="stroke"
            icon={Check}
            loading={respond.isPending}
            disabled={answered}
            onClick={() => send({ decision: "accept" })}
          >
            {copy.accept}
          </Button>
          <Button variant="ghost" icon={X} disabled={answered} onClick={() => setRejecting(true)}>
            {copy.reject}
          </Button>
        </div>
      ) : (
        <div className="flex flex-col gap-space-8">
          <SelectField
            id={`reject-code-${request.action_id}`}
            label={copy.rejectCode}
            value={code}
            options={codes.map((c) => ({ value: c, label: c }))}
            onChange={setCode}
          />
          <TextField
            id={`reject-reason-${request.action_id}`}
            label={copy.rejectReason}
            value={reason}
            onChange={setReason}
            onBlur={() => setTouched(true)}
            error={missing ? copy.rejectReasonRequired : undefined}
          />
          <div className="flex gap-space-8">
            <Button
              variant="solid"
              loading={respond.isPending}
              disabled={answered}
              onClick={() => {
                setTouched(true);
                if (reason.trim() === "") return;
                send({ decision: "reject", reject_code: code, reject_reason: reason.trim() });
              }}
            >
              {copy.confirmReject}
            </Button>
            <Button variant="ghost" disabled={answered} onClick={() => setRejecting(false)}>
              {copy.cancel}
            </Button>
          </div>
        </div>
      )}
      {error && (
        <div role="alert">
          <FieldMessage error={`${copy.responseError}: ${error}`} />
        </div>
      )}
    </div>
  );
}

/** «Effetto locale»: il massimo carico sugli archi che la misura tocca, prima → dopo. Il numero è del
 * motore (SIMULATO, con il suo tooltip): sale o scende, e lo si dice con il colore del design. */
function EffectRow({ effect }: { effect: MeasureEffect }) {
  const copy = strings.panels.ops.effect;
  const down = Number(effect.after.value) < Number(effect.before.value);
  const up = Number(effect.after.value) > Number(effect.before.value);
  return (
    <p className="flex flex-wrap items-center gap-x-space-8 text-xs text-text-secondary">
      <span className="font-semibold text-text-primary">{copy.label}</span>
      <span>{copy.what}</span>
      <span className="inline-flex items-center gap-1.5 font-mono text-sm font-semibold">
        <MeasuredValue
          measured={effect.before}
          label={`${copy.what}: ${copy.before.toLowerCase()}`}
          showUnit={false}
          className="text-text-secondary"
        />
        <span aria-hidden>→</span>
        <MeasuredValue
          measured={effect.after}
          label={`${copy.what}: ${copy.after.toLowerCase()}`}
          className={down ? "text-delta-better" : up ? "text-delta-worse" : "text-text-primary"}
          unitClassName="text-xs"
        />
      </span>
    </p>
  );
}

/** Una richiesta ai dipartimenti: chi, che cosa, a che punto è, il motivo se è stata rifiutata, e se il
 * run è manuale i pulsanti per rispondere. `onShow` porta la mappa sul luogo della richiesta. */
export function RequestCard({
  item,
  alternativeTo,
  effect,
  answerRun,
  onShow,
}: {
  item: RequestView;
  alternativeTo?: string;
  /** L'effetto locale della misura, se il motore lo dice (misura stradale in vigore). */
  effect?: MeasureEffect;
  /** L'id del run, se questa richiesta aspetta la risposta di una persona (altrimenti non c'è). */
  answerRun?: string;
  onShow: (item: RequestView) => void;
}) {
  const { request } = item;
  const state = STATE[request.state];
  const department = DEPARTMENTS[request.department];
  const departmentName = useDepartmentName();
  return (
    <article
      aria-label={`${request.action_id}`}
      className="flex flex-col gap-space-8 rounded-card bg-surface-2 p-space-16"
    >
      {alternativeTo && (
        <p className="text-xs text-text-secondary">{copy.alternativeTo(alternativeTo)}</p>
      )}
      <div className="flex items-start gap-space-12">
        <div className="flex min-w-0 flex-1 flex-col">
          <span className="flex items-center gap-space-8 text-sm font-semibold text-text-primary">
            {department && (
              <Icon icon={department.icon} size="inline" className="text-text-secondary" />
            )}
            {departmentName(request.department)}
          </span>
          <span className="font-mono text-xs text-text-secondary">{request.action_id}</span>
        </div>
        <StateChip tone={state.tone} icon={state.icon} label={copy.state[request.state]} />
      </div>
      <p className="text-sm text-text-primary">
        {[...new Set([measureLabel(request.type), request.target_label])].join(" — ")}
        {" · "}
        {strings.metrics.windows[request.window]}
      </p>
      {effect && <EffectRow effect={effect} />}
      {request.state === "REJECTED" && (request.reject_code || request.reject_reason) && (
        <p className="border-t-hairline border-border pt-space-8 text-sm text-text-secondary">
          {request.reject_code && (
            <span className="mr-2 font-mono text-xs font-bold text-status-rejected">
              {request.reject_code}
            </span>
          )}
          {request.reject_reason}
        </p>
      )}
      {request.target_geo && (
        <button
          type="button"
          onClick={() => onShow(item)}
          className="flex w-fit items-center gap-1.5 rounded-control text-xs text-text-secondary transition-base hover:text-text-primary"
        >
          <Icon icon={MapPin} size="inline" />
          {copy.showOnMap}
        </button>
      )}
      {answerRun && <ManualControls item={item} runId={answerRun} />}
    </article>
  );
}
