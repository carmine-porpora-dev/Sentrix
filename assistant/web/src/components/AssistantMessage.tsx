import { useMemo } from "react";
import { EntityChip } from "@/components/EntityChip";
import { GhostButton } from "@/components/GhostButton";
import { Sources } from "@/components/Sources";
import type { Source } from "@/api/chat";
import { parseAnswer, type Segment } from "@/lib/answer";
import { strings } from "@/strings";

function Segments({ segments }: { segments: Segment[] }) {
  return (
    <>
      {segments.map((segment, index) => {
        if (segment.type === "chip") {
          return <EntityChip key={index} kind={segment.kind} label={segment.label} />;
        }
        if (segment.type === "number") {
          return (
            <span key={index} className="whitespace-nowrap font-mono font-semibold tabular-nums">
              {segment.value}
            </span>
          );
        }
        return <span key={index}>{segment.value}</span>;
      })}
    </>
  );
}

interface AssistantMessageProps {
  text: string;
  sources: Source[];
  choices: string[];
  /** Le scelte rapide si mostrano solo sull'ultima risposta e finché non ne arriva un'altra. */
  showChoices: boolean;
  disabled: boolean;
  onChoose: (choice: string) => void;
}

/** La risposta dell'assistente: testo semplice senza bolla, passi numerati, numeri in monospazio,
 * chip di entità; sotto, le fonti con la natura di ogni dato. */
export function AssistantMessage({
  text,
  sources,
  choices,
  showChoices,
  disabled,
  onChoose,
}: AssistantMessageProps) {
  const blocks = useMemo(() => parseAnswer(text), [text]);
  return (
    <div className="max-w-[95%]">
      <div className="flex flex-col gap-3 [overflow-wrap:anywhere]">
        {blocks.map((block, index) =>
          block.type === "paragraph" ? (
            <p key={index} className="m-0 whitespace-pre-wrap">
              <Segments segments={block.segments} />
            </p>
          ) : (
            <ol key={index} role="list" className="m-0 flex list-none flex-col gap-2.5 p-0">
              {block.items.map((item, step) => (
                <li key={step} className="flex gap-3">
                  <span className="size-6 flex-none rounded-full bg-surface-3 text-center text-[13px] font-semibold leading-6 tabular-nums text-text-secondary">
                    {step + 1}
                  </span>
                  <div className="min-w-0 flex-1 whitespace-pre-wrap">
                    <Segments segments={item} />
                  </div>
                </li>
              ))}
            </ol>
          ),
        )}
      </div>
      <Sources sources={sources} />
      {showChoices && choices.length > 0 && (
        <div
          role="group"
          aria-label={strings.conversation.quickChoices}
          className="mt-3 flex flex-wrap gap-2"
        >
          {choices.map((choice) => (
            <GhostButton key={choice} disabled={disabled} onClick={() => onChoose(choice)}>
              {choice}
            </GhostButton>
          ))}
        </div>
      )}
    </div>
  );
}
