import { ChevronDown, Clock, Replace, Ban, User, Check, X, type LucideIcon } from "lucide-react";
import { Fragment, useMemo, useState, type ReactNode } from "react";
import { useDepartmentName, useRun } from "@/api/queries";
import type { MetricsResponse, Notification, PlanItem, RequestView } from "@/api/types";
import { Badge, type BadgeKind } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Callout } from "@/components/Callout";
import { ManualSwitch } from "@/components/forms/ManualSwitch";
import { Icon } from "@/components/Icon";
import { MeasuredValue } from "@/components/MeasuredValue";
import { StateChip, type ChipTone } from "@/components/StateChip";
import { useEvent } from "@/features/metrics/queries";
import { comparisonRows } from "@/features/run/comparison";
import {
  awaitsPerson,
  departmentCards,
  groupRequests,
  operationsOrder,
  producedIterations,
  runSignature,
  type OperationsBlock,
  type DepartmentCard,
} from "@/features/run/derive";
import { BulletinCard } from "@/features/run/EmergencyBulletins";
import { EvidenceList } from "@/features/run/Evidence";
import { measureEffects } from "@/features/run/effects";
import { isKnownMeasure, measureLabel, RequestCard } from "@/features/run/RequestCard";
import {
  useAcceptAll,
  useEmergencyBulletins,
  useEvidence,
  useIterationMetrics,
  useVdeptRegistry,
  useWhatsAppNotification,
} from "@/features/run/queries";
import { iterationNumber } from "@/features/shell/run";
import { useShell } from "@/features/shell/ShellProvider";
import { DEPARTMENTS } from "@/lib/departments";
import { displayUnit, formatClock, isShortUnit } from "@/lib/format";
import { logTable } from "@/lib/logTable";
import { cn } from "@/lib/utils";
import { strings } from "@/i18n/it";

const copy = strings.panels.ops;

const PLAN_STATUS: Record<PlanItem["status"], { tone: ChipTone; icon: LucideIcon }> = {
  proposed: { tone: "pending", icon: Clock },
  accepted: { tone: "accepted", icon: Check },
  rejected: { tone: "rejected", icon: X },
  replaced: { tone: "neutral", icon: Replace },
  human_decision_required: { tone: "pending", icon: User },
  discarded: { tone: "neutral", icon: Ban },
};

function Section({
  title,
  aside,
  children,
}: {
  title: string;
  aside?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section aria-label={title} className="flex flex-col gap-space-12">
      <div className="flex items-center justify-between gap-space-8">
        <h3 className="text-lg">{title}</h3>
        {aside}
      </div>
      {children}
    </section>
  );
}

/** L'esito del messaggio WhatsApp di fine run (spech 12.4): una riga di stato, senza anteprima del
 * testo e senza pulsanti. Il numero è quello mascherato dal server. */
function WhatsAppLine({ row }: { row: Notification }) {
  const text = copy.whatsapp;
  const sent = row.state === "SENT";
  const reason = text.reasons[row.error_code ?? ""] ?? text.unknownReason;
  return (
    <p
      data-state={row.state}
      className={cn(
        "rounded-control bg-surface-2 p-space-12 text-sm",
        row.state === "FAILED" ? "text-status-rejected" : "text-text-primary",
      )}
    >
      {text.label} ·{" "}
      {sent
        ? text.sent(row.recipient_label ?? "", formatClock(row.created_at))
        : text.notSent(reason)}
    </p>
  );
}

function PlanRow({ item, evidence }: { item: PlanItem; evidence: ReturnType<typeof useEvidence> }) {
  const { recommendation: measure } = item;
  const status = PLAN_STATUS[item.status];
  const department = DEPARTMENTS[measure.department];
  const departmentName = useDepartmentName();
  return (
    <li className="flex flex-col gap-space-8 rounded-control bg-surface-2 p-space-12">
      <div className="flex items-start gap-space-12">
        <span
          data-number="ordinal"
          className="grid size-6 flex-none place-items-center rounded-full bg-surface-3 font-mono text-xs font-bold text-text-primary"
        >
          {item.seq}
        </span>
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <p className="text-sm text-text-primary">{measure.rationale}</p>
          <p className="flex flex-wrap items-center gap-x-space-8 text-xs text-text-secondary">
            <span>{measureLabel(measure.measure_type)}</span>
            <span aria-hidden>·</span>
            <span className="flex items-center gap-1">
              {department && <Icon icon={department.icon} size="inline" />}
              {departmentName(measure.department)}
            </span>
            <span aria-hidden>·</span>
            <span>{strings.metrics.windows[measure.window]}</span>
          </p>
          {item.status === "replaced" &&
            item.replaced_by !== null &&
            item.replaced_by !== undefined && (
              <p className="text-xs text-text-secondary">{copy.replacedBy(item.replaced_by)}</p>
            )}
          {item.note && <p className="text-xs text-text-secondary">{item.note}</p>}
        </div>
        <StateChip tone={status.tone} icon={status.icon} label={copy.planStatus[item.status]} />
      </div>
      <EvidenceList ids={measure.evidence_ids} evidence={evidence} />
    </li>
  );
}

function DepartmentCardView({ card }: { card: DepartmentCard }) {
  const department = DEPARTMENTS[card.id];
  const labels = copy.resources as Record<string, string>;
  return (
    <li className="flex flex-col gap-space-12 rounded-card bg-surface-2 p-space-16">
      <span className="flex items-center gap-space-8 text-sm font-semibold text-text-primary">
        {department && <Icon icon={department.icon} className="text-text-secondary" />}
        {card.name}
      </span>
      {card.resources.length === 0 ? (
        <p className="text-xs text-text-secondary">{copy.noResources}</p>
      ) : (
        card.resources.map((line) => (
          <div key={line.resource} className="flex flex-col gap-1.5">
            <p data-number="resource" className="flex items-baseline gap-1.5">
              <span
                className={cn(
                  "font-mono text-2xl font-semibold tabular-nums",
                  line.remaining === 0 && "text-status-rejected",
                )}
              >
                {line.remaining}
              </span>
              <span className="text-xs text-text-secondary">
                {copy.of} <span className="font-mono">{line.total}</span>
              </span>
            </p>
            <p className="text-xs text-text-secondary">{labels[line.resource] ?? line.resource}</p>
            <div aria-hidden className="h-1 rounded-sm bg-surface-3">
              <div
                className="h-full rounded-sm bg-action"
                style={{ width: `${line.total > 0 ? (line.remaining / line.total) * 100 : 0}%` }}
              />
            </div>
          </div>
        ))
      )}
    </li>
  );
}

function Alternatives({
  group,
  render,
}: {
  group: ReturnType<typeof groupRequests>[number];
  render: (item: RequestView, alternativeTo?: string) => React.ReactNode;
}) {
  const [open, setOpen] = useState(true);
  return (
    <li className="flex flex-col gap-space-8">
      {render(group.primary)}
      {group.alternatives.length > 0 && (
        <div className="flex flex-col gap-space-8 pl-space-12">
          <button
            type="button"
            aria-expanded={open}
            onClick={() => setOpen(!open)}
            className="flex h-10 items-center gap-space-8 rounded-control border-hairline border-border bg-surface-1 px-space-12 text-left text-sm text-text-primary"
          >
            <span className="flex-1">{copy.alternatives(group.alternatives.length)}</span>
            <Icon
              icon={ChevronDown}
              className={cn("text-text-secondary transition-transform", !open && "-rotate-90")}
            />
          </button>
          {open && (
            <ul className="flex flex-col gap-space-8 border-l-control border-action pl-space-12">
              {group.alternatives.map((alt) => (
                <li key={alt.request.action_id}>
                  {render(alt, alt.request.alternative_of ?? group.primary.request.action_id)}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </li>
  );
}

/** La natura del dato di una riga (REALE · STIMA · SIMULATO): quella della prima cella che c'è. */
const kindOf = (row: ReturnType<typeof comparisonRows>[number]): string | undefined =>
  row.cells.find((cell) => cell !== undefined)?.kind;

/** L'unità di una riga: quella della prima cella che c'è (stessa metrica, stessa unità). */
const unitOf = (row: ReturnType<typeof comparisonRows>[number]): string =>
  row.cells.find((cell) => cell !== undefined)?.unit ?? "";

/** Il confronto tra iterazioni (design, schermata 08): le metriche del motore una colonna per
 * iterazione e la variazione dell'ultima rispetto alla precedente, già calcolata dal backend. */
function ComparisonTable({ responses }: { responses: (MetricsResponse | undefined)[] }) {
  const shell = useShell();
  const rows = comparisonRows(shell.window, responses);
  const columns = responses.map((_, n) =>
    n === 0 ? copy.before : copy.iteration(iterationNumber(n)),
  );
  return (
    <div className={logTable.frame}>
      <table className={logTable.table}>
        <thead>
          <tr className={logTable.headRow}>
            <th scope="col" className={logTable.headCell}>
              {copy.comparisonMetric}
            </th>
            {columns.map((name) => (
              <th key={name} scope="col" className={logTable.headCell}>
                {name}
              </th>
            ))}
            <th scope="col" className={logTable.headCell}>
              {copy.comparisonDelta}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.metric} className={logTable.row}>
              <th
                scope="row"
                className={cn(
                  logTable.firstCell,
                  "px-space-12 py-space-12 font-normal text-text-primary",
                )}
              >
                {row.label}
                {!isShortUnit(unitOf(row)) && displayUnit(unitOf(row)) !== "" && (
                  <span className="block text-xs text-text-secondary">
                    {displayUnit(unitOf(row))}
                  </span>
                )}
                {kindOf(row) && (
                  <span className="mt-1.5 block">
                    <Badge kind={kindOf(row) as BadgeKind} />
                  </span>
                )}
              </th>
              {row.cells.map((cell, index) => (
                <td key={columns[index]} className="px-space-8 py-space-12">
                  {cell ? (
                    <MeasuredValue
                      measured={cell}
                      label={row.label}
                      showUnit={isShortUnit(unitOf(row))}
                      className="font-mono text-xs"
                    />
                  ) : (
                    <span className="text-text-secondary">—</span>
                  )}
                </td>
              ))}
              <td className="px-space-8 py-space-12">
                {row.delta ? (
                  <MeasuredValue
                    measured={row.delta}
                    label={row.label}
                    variant="delta"
                    better={row.better}
                    showUnit={isShortUnit(row.delta.unit === "rapporto" ? "pp" : unitOf(row))}
                  />
                ) : (
                  <span className="text-text-secondary">—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Il pannello Operations (07 6): il piano con lo stato di ogni misura, le risorse dei quattro
 * dipartimenti, le richieste (con le alternative dopo un rifiuto, e Accetta / Rifiuta se la risposta è
 * manuale), il confronto tra le iterazioni e, se serve, la decisione che aspetta una persona. */
export function OperationsPanel() {
  const shell = useShell();
  const view = useRun(shell.runId).data;
  const run = view?.run;
  const plan = useMemo(() => view?.plan ?? [], [view?.plan]);
  const requests = view?.requests ?? [];
  const event = useEvent(run?.event_id);
  const registry = useVdeptRegistry(run?.id, runSignature(view));
  const responses = producedIterations(useIterationMetrics(run));
  const effects = measureEffects(responses);
  const planIds = useMemo(() => plan.flatMap((item) => item.recommendation.evidence_ids), [plan]);
  const evidence = useEvidence(run?.id, planIds);
  const whatsapp = useWhatsAppNotification(run);
  const bulletins = useEmergencyBulletins(run);

  const pending = plan.filter((item) => item.status === "human_decision_required");
  const cards = departmentCards(registry.data, shell.window);
  // le scartate (fuori dal tetto, o da RECONCILE) si vedono ma non sono nel piano: non si contano nel titolo
  const inPlan = plan.filter((item) => item.status !== "discarded").length;
  const groups = groupRequests(requests);
  const acceptAll = useAcceptAll(run?.id);
  // Le richieste accettate in blocco restano `RECEIVED` per l'interfaccia fino alla prossima lettura
  // del run: intanto non hanno più pulsanti (un secondo clic arriverebbe a richieste già decise).
  const [accepted, setAccepted] = useState<ReadonlySet<string>>(new Set());
  const isOpen = (item: RequestView) =>
    awaitsPerson(item, shell.runManual) && !accepted.has(item.request.action_id);
  const waitingForMe = requests.filter(isOpen);
  const realMeasures = event.data?.real_measures ?? [];
  const showRequest = (item: RequestView) => {
    if (item.request.target_geo) shell.focusOn(item.request.target_geo);
  };

  const blocks: Record<OperationsBlock, ReactNode> = {
    plan: (
      <>
        {run && (
          <Section title={copy.plan(inPlan)} aside={<Badge kind="simulated" />}>
            {plan.length === 0 ? (
              <p className="text-sm text-text-secondary">{copy.noPlan}</p>
            ) : (
              <ol className="flex flex-col gap-space-8">
                {plan.map((item) => (
                  <PlanRow key={item.seq} item={item} evidence={evidence} />
                ))}
              </ol>
            )}
          </Section>
        )}
        {realMeasures.length > 0 && (
          <Section title={copy.realMeasures} aside={<Badge kind="real" />}>
            <ol className="flex flex-col gap-space-8">
              {realMeasures.map((measure, index) => (
                <li
                  key={`${index}-${measure.label}`}
                  className="flex flex-col gap-1 rounded-control bg-surface-2 p-space-12"
                >
                  <p className="text-sm text-text-primary">{measure.label}</p>
                  <p className="text-xs text-text-secondary">
                    {isKnownMeasure(measure.measure_type) &&
                      `${measureLabel(measure.measure_type)} · `}
                    {measure.target} · {measure.source_ref}
                  </p>
                  {!isKnownMeasure(measure.measure_type) && (
                    <p className="text-xs text-text-secondary">{copy.realNotModelled}</p>
                  )}
                </li>
              ))}
            </ol>
          </Section>
        )}
      </>
    ),
    departments:
      run && cards.length > 0 ? (
        <Section title={copy.departments} aside={<Badge kind="simulated" />}>
          <ul className="grid grid-cols-2 gap-space-12">
            {cards.map((card) => (
              <DepartmentCardView key={card.id} card={card} />
            ))}
          </ul>
        </Section>
      ) : null,
    requests: (
      <Section title={copy.requests}>
        <ManualSwitch
          checked={shell.manualResponse}
          onChange={shell.setManualResponse}
          label={copy.manualSwitch}
          stateLabels={{ on: "On", off: "Off" }}
          hint={`${shell.manualResponse ? copy.manualOn : copy.manualOff}${shell.runId ? ` ${copy.manualNextRun}` : ""}`}
        />
        {(waitingForMe.length > 1 || (acceptAll.data?.length ?? 0) > 0) && (
          <div className="flex flex-col gap-space-8">
            {waitingForMe.length > 1 && (
              <Button
                variant="stroke"
                icon={Check}
                loading={acceptAll.isPending}
                onClick={() => {
                  const items = waitingForMe.map((item) => ({
                    deptId: item.request.department,
                    actionId: item.request.action_id,
                  }));
                  acceptAll.mutate(items, {
                    onSuccess: (failed) =>
                      setAccepted(
                        (before) =>
                          new Set([
                            ...before,
                            ...items.map((i) => i.actionId).filter((id) => !failed.includes(id)),
                          ]),
                      ),
                  });
                }}
              >
                {copy.acceptAll(waitingForMe.length)}
              </Button>
            )}
            {acceptAll.data && acceptAll.data.length > 0 && (
              <p role="alert" className="text-sm text-text-secondary">
                {copy.acceptAllFailed(acceptAll.data.length)}
              </p>
            )}
          </div>
        )}
        {groups.length === 0 ? (
          <p className="text-sm text-text-secondary">{copy.noRequests}</p>
        ) : (
          <ul className="flex flex-col gap-space-12">
            {groups.map((group) => (
              <Alternatives
                key={group.primary.request.action_id}
                group={group}
                render={(item, alternativeTo) => (
                  <RequestCard
                    item={item}
                    alternativeTo={alternativeTo}
                    effect={effects.get(item.request.action_id)}
                    answerRun={run && isOpen(item) ? run.id : undefined}
                    onShow={showRequest}
                  />
                )}
              />
            ))}
          </ul>
        )}
      </Section>
    ),
    comparison:
      responses.filter(Boolean).length > 1 ? (
        <Section title={copy.comparison}>
          <ComparisonTable responses={responses} />
        </Section>
      ) : null,
  };

  return (
    <div className="flex flex-col gap-space-24 p-space-16">
      {pending.length > 0 && (
        <Callout tone="warning" title={copy.decisionTitle}>
          {pending.map((item) => (
            <p key={item.seq} className="text-text-primary">
              {item.note ?? item.recommendation.rationale}
            </p>
          ))}
        </Callout>
      )}
      {operationsOrder(run?.state, pending.length > 0).map((block) => (
        <Fragment key={block}>{blocks[block]}</Fragment>
      ))}
      {run && bulletins.length > 0 && (
        <Section title={copy.emergency.title} aside={<Badge kind="simulated" />}>
          <p className="text-sm text-text-secondary">{copy.emergency.note}</p>
          <ul className="flex flex-col gap-space-12">
            {bulletins.map((bulletin) => (
              <li key={bulletin.id}>
                <BulletinCard bulletin={bulletin} runId={run.id} />
              </li>
            ))}
          </ul>
        </Section>
      )}
      {whatsapp && (
        <Section title={copy.communications}>
          <WhatsAppLine row={whatsapp} />
        </Section>
      )}
    </div>
  );
}
