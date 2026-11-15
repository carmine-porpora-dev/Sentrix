import { Plus, RotateCcw } from "lucide-react";
import { Button } from "@/components/Button";
import { SelectField } from "@/components/forms/SelectField";
import { FieldMessage } from "@/components/forms/TextField";
import { NEW_EVENT, useEventEditor } from "@/features/events/EventEditor";
import {
  AdvancedSection,
  AreaSection,
  AttendanceSection,
  BackgroundSection,
  ClosuresSection,
  DatesSection,
  DisruptionsSection,
  ExtrasSection,
  IdentitySection,
  ResourcesSection,
} from "@/features/events/sections";
import { strings } from "@/i18n/it";

const copy = strings.events;

/** Il chip «preset» degli eventi che arrivano dai file seed. */
function PresetChip() {
  return (
    <span className="rounded-tag border-hairline border-action px-2 text-xs font-semibold text-action">
      {copy.presetChip}
    </span>
  );
}

/** Il selettore degli eventi (con il badge «preset» per i seed), «Nuovo evento» e «Ripristina preset». */
function EventPicker() {
  const editor = useEventEditor();
  const selected = editor.events.find((item) => item.id === editor.selectedId);
  const options = [
    ...(editor.isNew ? [{ value: NEW_EVENT, label: copy.newEventTitle }] : []),
    ...editor.events.map((item) => ({
      value: item.id,
      label: item.name,
    })),
  ];
  return (
    <div className="flex flex-col gap-space-8 p-space-16">
      <SelectField
        id="ev-picker"
        label={copy.eventLabel}
        labelAside={selected?.is_seed ? <PresetChip /> : undefined}
        value={editor.selectedId ?? ""}
        options={options}
        onChange={editor.select}
        disabled={editor.events.length === 0 && !editor.isNew}
      />
      <div className="grid grid-cols-1 gap-space-8 compact:grid-cols-2">
        <Button variant="ghost" icon={Plus} onClick={editor.startNew}>
          {copy.newEvent}
        </Button>
        <Button
          variant="ghost"
          icon={RotateCcw}
          loading={editor.resetting}
          disabled={editor.isNew || !selected?.is_seed}
          onClick={editor.resetPreset}
        >
          {editor.resetting ? copy.resetting : copy.resetPreset}
        </Button>
      </div>
      {editor.dirty && <p className="text-xs text-text-secondary">{copy.unsaved}</p>}
    </div>
  );
}

/** Gli errori dell'API su campi che il form non mostra, in cima. */
function UnplacedErrors() {
  const { unplaced } = useEventEditor();
  if (unplaced.length === 0) return null;
  return (
    <div
      role="alert"
      className="mx-space-16 mb-space-12 flex flex-col gap-1.5 rounded-control border-hairline border-danger bg-state-fill-error p-space-12"
    >
      <p className="text-xs font-semibold text-text-primary">{copy.invalidTitle}</p>
      {unplaced.map((item) => (
        <FieldMessage
          key={`${item.path}:${item.message}`}
          error={`${item.path}: ${item.message}`}
        />
      ))}
    </div>
  );
}

/** L'Event Manager (07 4): un solo form per l'entità Evento, per qualunque evento. Tutto si scrive
 * nella bozza dell'editor; «Analizza» salva l'Evento (se è nuovo o modificato) e avvia il run. */
export function EventManager() {
  const editor = useEventEditor();

  let body;
  if (editor.eventsStatus === "error") {
    body = <FieldMessage error={copy.eventsError} />;
  } else if (editor.eventsStatus === "loading") {
    body = <p className="px-space-16 text-xs text-text-secondary">{copy.loadingEvents}</p>;
  } else if (editor.eventStatus === "error") {
    body = (
      <div className="px-space-16">
        <FieldMessage error={copy.eventError} />
      </div>
    );
  } else if (editor.eventStatus !== "ready") {
    body = <p className="px-space-16 text-xs text-text-secondary">{copy.loadingEvent}</p>;
  } else {
    body = (
      <>
        <UnplacedErrors />
        <IdentitySection />
        <DatesSection />
        <AreaSection />
        <AttendanceSection />
        <BackgroundSection />
        <ClosuresSection />
        <DisruptionsSection />
        <ResourcesSection />
        <ExtrasSection />
        <AdvancedSection />
      </>
    );
  }

  const busy = editor.analyzing || editor.runInProgress;
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto">
        <EventPicker />
        {body}
      </div>
      <footer className="flex flex-none flex-col gap-space-8 border-t-hairline border-border bg-surface-1 p-space-16">
        {editor.submitError && (
          <div role="alert">
            <FieldMessage error={editor.submitError} />
          </div>
        )}
        {editor.missing > 0 && editor.eventStatus === "ready" && !busy && (
          <p className="text-xs text-text-secondary">{copy.missing(editor.missing)}</p>
        )}
        <Button
          block
          loading={busy}
          disabled={!editor.canAnalyze}
          onClick={() => void editor.analyze()}
        >
          {busy ? copy.analyzing : copy.analyze}
        </Button>
      </footer>
    </div>
  );
}
