import {
  Check,
  ChevronDown,
  Clock,
  Loader2,
  MapPin,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";
import { useMemo, useState } from "react";
import { useRun } from "@/api/queries";
import type { AgentSummary, Finding } from "@/api/types";
import { Callout } from "@/components/Callout";
import { Icon } from "@/components/Icon";
import { IconButton } from "@/components/IconButton";
import { RunStatus } from "@/components/RunStatus";
import { Tag } from "@/components/Tag";
import { runDisplay } from "@/features/run/derive";
import { EvidenceList } from "@/features/run/Evidence";
import { useEvidence } from "@/features/run/queries";
import { useShell } from "@/features/shell/ShellProvider";
import { cn } from "@/lib/utils";
import { strings } from "@/i18n/it";

const copy = strings.panels.agents;

const AGENTS = ["event_demand", "traffic", "transit", "operations"] as const;

const STATE_ICON: Record<
  AgentSummary["state"],
  { icon: LucideIcon; ring: string; spin?: boolean }
> = {
  waiting: { icon: Clock, ring: "border-border-strong text-text-muted" },
  running: { icon: Loader2, ring: "border-action text-action", spin: true },
  done: { icon: Check, ring: "border-status-accepted text-status-accepted" },
  done_fallback: { icon: Check, ring: "border-status-pending text-status-pending" },
  error: { icon: TriangleAlert, ring: "border-status-rejected text-status-rejected" },
};

const SEVERITY: Record<Finding["severity"], string> = {
  info: "bg-text-secondary",
  warning: "bg-status-pending",
  critical: "bg-status-rejected",
};

function FindingRow({
  finding,
  evidence,
  onShow,
}: {
  finding: Finding;
  evidence: ReturnType<typeof useEvidence>;
  onShow: (finding: Finding) => void;
}) {
  return (
    <li className="flex flex-col gap-1.5 rounded-control bg-surface-2 p-space-12">
      <div className="flex items-start gap-space-8">
        <span
          role="img"
          aria-label={copy.severity[finding.severity]}
          title={copy.severity[finding.severity]}
          className={cn("mt-1.5 size-2 flex-none rounded-full", SEVERITY[finding.severity])}
        />
        <p className="min-w-0 flex-1 text-sm text-text-primary">{finding.summary}</p>
        {finding.location && (
          <IconButton
            icon={MapPin}
            label={copy.showOnMap}
            tooltip
            onClick={() => onShow(finding)}
          />
        )}
      </div>
      <EvidenceList ids={finding.evidence_ids} evidence={evidence} />
    </li>
  );
}

function AgentItem({
  agent,
  summary,
  evidence,
  onShow,
}: {
  agent: (typeof AGENTS)[number];
  summary: AgentSummary | undefined;
  evidence: ReturnType<typeof useEvidence>;
  onShow: (finding: Finding) => void;
}) {
  const state = summary?.state ?? "waiting";
  const tools = summary?.tools_called ?? [];
  const findings = summary?.findings ?? [];
  const marker = STATE_ICON[state];
  const hasContent = Boolean(summary?.text) || findings.length > 0 || tools.length > 0;
  const [open, setOpen] = useState(true);
  const name = copy.names[agent];
  return (
    <li className="flex gap-space-12">
      <span
        className={cn(
          "grid size-8 flex-none place-items-center rounded-full border-control bg-surface-1",
          marker.ring,
        )}
      >
        <Icon
          icon={marker.icon}
          size="inline"
          className={marker.spin ? "motion-safe:animate-spin" : undefined}
        />
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-space-8">
        <button
          type="button"
          aria-expanded={hasContent ? open : undefined}
          disabled={!hasContent}
          onClick={() => setOpen(!open)}
          className="flex w-full items-center gap-space-8 text-left disabled:cursor-default"
        >
          <span className="flex min-w-0 flex-1 flex-col">
            <span className="text-sm font-semibold text-text-primary">{name}</span>
            <span className="text-xs text-text-secondary">{copy.states[state]}</span>
          </span>
          {hasContent && (
            <Icon
              icon={ChevronDown}
              className={cn("text-text-secondary transition-transform", !open && "-rotate-90")}
            />
          )}
        </button>
        {hasContent && open && summary && (
          <div className="flex flex-col gap-space-8">
            {summary.text && (
              <div className="flex flex-col gap-1.5">
                <p className="text-sm text-text-primary">{summary.text}</p>
                {summary.text_origin && (
                  <p className="text-xs text-text-secondary">
                    {copy.originLabel}:{" "}
                    <span className="font-semibold">
                      {(copy.textOrigin as Record<string, string>)[summary.text_origin] ??
                        summary.text_origin}
                    </span>
                  </p>
                )}
              </div>
            )}
            {tools.length > 0 && (
              <div className="flex flex-col gap-1">
                <p className="text-xs text-text-secondary">{copy.tools}</p>
                <ul className="flex flex-wrap gap-1.5">
                  {tools.map((tool) => (
                    <Tag as="li" key={tool}>
                      {tool}
                    </Tag>
                  ))}
                </ul>
              </div>
            )}
            {findings.length > 0 && (
              <div className="flex flex-col gap-1.5">
                <p className="text-xs text-text-secondary">{copy.findings}</p>
                <ul className="flex flex-col gap-space-8">
                  {findings.map((finding, index) => (
                    <FindingRow
                      key={`${index}-${finding.summary}`}
                      finding={finding}
                      evidence={evidence}
                      onShow={onShow}
                    />
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>
    </li>
  );
}

/** Il pannello Agenti (07 6): lo stato del run, i quattro agenti con strumenti, testo e origine del
 * testo, e le evidenze di ogni affermazione con il loro numero e la loro provenienza. Un'evidenza con
 * un luogo si mostra sulla mappa. */
export function AgentsPanel() {
  const shell = useShell();
  const view = useRun(shell.runId).data;
  const run = view?.run;
  const ids = useMemo(
    () =>
      (view?.agents ?? []).flatMap((agent) =>
        (agent.findings ?? []).flatMap((f) => f.evidence_ids),
      ),
    [view?.agents],
  );
  const evidence = useEvidence(run?.id, ids);
  const status = run ? runDisplay(run, view?.plan ?? []) : undefined;
  const sources = copy.sources as Record<string, string>;
  const showFinding = (finding: Finding) => {
    if (finding.location) shell.focusOn(finding.location);
  };

  return (
    <div className="flex flex-col gap-space-16 p-space-16">
      <h2 className="text-xl">{copy.title}</h2>
      {run && status ? (
        <RunStatus state={status.display} step={status.step} />
      ) : (
        <p className="text-sm text-text-secondary">{copy.noRun}</p>
      )}
      {view && view.degraded.length > 0 && (
        <Callout tone="info" title={copy.degradedTitle}>
          <p>{copy.degradedHint}</p>
          <ul className="mt-1 list-inside list-disc">
            {view.degraded.map((source) => (
              <li key={source}>{sources[source] ?? source}</li>
            ))}
          </ul>
        </Callout>
      )}
      <ol aria-label={copy.title} className="flex flex-col gap-space-16">
        {AGENTS.map((agent) => (
          <AgentItem
            key={agent}
            agent={agent}
            summary={view?.agents.find((item) => item.agent === agent)}
            evidence={evidence}
            onShow={showFinding}
          />
        ))}
      </ol>
      {run?.state === "ERROR" && (
        <Callout tone="error" title={copy.errorTitle}>
          {run.error && <p className="text-text-primary">{run.error}</p>}
          <p>{copy.errorHint}</p>
        </Callout>
      )}
    </div>
  );
}
