import { Bot, Cog, Download, User, type LucideIcon } from "lucide-react";
import { useState } from "react";
import { isRunFinished, useDepartmentName, useRun } from "@/api/queries";
import { useApi } from "@/api/provider";
import type { Decision } from "@/api/types";
import { Button } from "@/components/Button";
import { FieldMessage } from "@/components/forms/TextField";
import { Icon } from "@/components/Icon";
import { Tag } from "@/components/Tag";
import { tail } from "@/features/metrics/cards";
import { actorLabel, runSignature } from "@/features/run/derive";
import { useDecisions } from "@/features/run/queries";
import { useShell } from "@/features/shell/ShellProvider";
import { DEPARTMENTS } from "@/lib/departments";
import { downloadText } from "@/lib/download";
import { formatClock } from "@/lib/format";
import { logTable } from "@/lib/logTable";
import { cn } from "@/lib/utils";
import { strings } from "@/i18n/it";

const copy = strings.panels.log;

const AGENTS = new Set(["event_demand", "traffic", "transit", "operations"]);

/** L'icona di chi ha scritto la riga: il sistema, un agente, un dipartimento, una persona. */
function actorIcon(actor: string): LucideIcon {
  if (actor === "user") return User;
  if (actor === "system" || actor === "orchestrator") return Cog;
  if (AGENTS.has(actor)) return Bot;
  return DEPARTMENTS[actor]?.icon ?? Cog;
}

function Refs({ refs }: { refs: Decision["refs"] }) {
  if (!refs || refs.length === 0) return null;
  return (
    <ul aria-label={copy.refs} className="mt-1 flex flex-wrap gap-1.5">
      {refs.map((ref) => (
        <Tag as="li" key={ref} title={ref} truncate>
          {ref.startsWith("m.") ? tail(ref) : ref}
        </Tag>
      ))}
    </ul>
  );
}

type Export = "json" | "metrics" | "critical_edges";

/** Il pannello Decisioni (07 6): il registro cronologico del run (ora, attore, decisione e motivo,
 * riferimenti) e l'esportazione: JSON del pacchetto del run, CSV delle metriche e degli archi critici. */
export function DecisionsPanel() {
  const api = useApi();
  const shell = useShell();
  const view = useRun(shell.runId).data;
  const run = view?.run;
  const decisions = useDecisions(run?.id, runSignature(view));
  const departmentName = useDepartmentName();
  const [exporting, setExporting] = useState<Export | undefined>(undefined);
  const [failed, setFailed] = useState(false);

  async function download(kind: Export) {
    if (!run) return;
    setExporting(kind);
    setFailed(false);
    try {
      if (kind === "json") {
        const pack = await api.exportRun(run.id);
        downloadText(`${run.id}.json`, "application/json", JSON.stringify(pack, null, 2));
      } else {
        const text = await api.exportRunCsv(run.id, kind);
        downloadText(`${run.id}_${kind}.csv`, "text/csv", text);
      }
    } catch {
      setFailed(true);
    } finally {
      setExporting(undefined);
    }
  }

  const rows = decisions.data ?? [];
  // un file preso a metà (senza metriche, con richieste ferme) sembrerebbe completo: si esporta a run finito
  const exportable = run !== undefined && isRunFinished(run.state);
  const exportButton = (kind: Export, label: string) => (
    <Button
      variant="stroke"
      icon={Download}
      loading={exporting === kind}
      disabled={!exportable || exporting !== undefined}
      onClick={() => void download(kind)}
      className="px-space-8"
    >
      {exporting === kind ? copy.exporting : label}
    </Button>
  );

  return (
    <div className="flex flex-col gap-space-16 p-space-16">
      <h2 className="text-xl">{copy.title}</h2>
      <div className="grid grid-cols-3 gap-space-8">
        {exportButton("json", copy.exportJson)}
        {exportButton("metrics", copy.exportMetrics)}
        {exportButton("critical_edges", copy.exportEdges)}
      </div>
      {run && !exportable && <p className="text-xs text-text-secondary">{copy.exportWhenDone}</p>}
      {failed && (
        <div role="alert">
          <FieldMessage error={copy.exportError} />
        </div>
      )}
      {!run ? (
        <p className="text-sm text-text-secondary">{copy.noRun}</p>
      ) : rows.length === 0 ? (
        <p className="text-sm text-text-secondary">{copy.empty}</p>
      ) : (
        <div className={logTable.frame}>
          <table className={logTable.table}>
            <thead>
              <tr className={logTable.headRow}>
                <th scope="col" className={cn(logTable.headCell, "w-16")}>
                  {copy.time}
                </th>
                <th scope="col" className={cn(logTable.headCell, "w-36")}>
                  {copy.actor}
                </th>
                <th scope="col" className={logTable.headCell}>
                  {copy.decision}
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.seq} className={cn(logTable.row, "align-top")}>
                  <td
                    data-number="clock"
                    className={cn(
                      logTable.firstCell,
                      "px-space-12 py-space-12 font-mono text-xs font-medium text-text-secondary",
                    )}
                  >
                    {formatClock(row.at)}
                  </td>
                  <td className="px-space-12 py-space-12">
                    <span className="flex items-start gap-space-8 text-xs font-semibold text-text-primary">
                      <Icon
                        icon={actorIcon(row.actor)}
                        size="inline"
                        className="mt-0.5 text-text-secondary"
                      />
                      {actorLabel(row.actor, departmentName)}
                    </span>
                  </td>
                  <td className="px-space-12 py-space-12">
                    <p className="font-semibold text-text-primary">{row.decision}</p>
                    <p className="text-xs text-text-secondary">{row.rationale}</p>
                    <Refs refs={row.refs} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
