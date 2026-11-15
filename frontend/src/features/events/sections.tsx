import { Ban, Bus, MapPin, Plus, X } from "lucide-react";
import type { ReactNode } from "react";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { FormSection } from "@/components/forms/FormSection";
import { FieldMessage, TextField } from "@/components/forms/TextField";
import { Icon } from "@/components/Icon";
import { IconButton } from "@/components/IconButton";
import { useEventEditor, type MapMode } from "@/features/events/EventEditor";
import { ZONE_TYPES } from "@/features/events/draft";
import { EditorSelect, EditorText, changeAt, fieldId, removeAt } from "@/features/events/fields";
import { RESOURCE_FIELDS, WINDOWS, paths } from "@/features/events/paths";
import { RADIUS_SLIDER } from "@/features/map/config";
import { cn } from "@/lib/utils";
import { strings } from "@/i18n/it";

const copy = strings.events;
const LEVELS = ["low", "mid", "high"] as const;

/** Il pulsante che accende o spegne un modo di scelta sulla mappa (centro, strade, fermate). */
function MapModeButton({
  mode,
  idle,
  active,
}: {
  mode: Exclude<MapMode, "idle">;
  idle: string;
  active: string;
}) {
  const editor = useEventEditor();
  const on = editor.mapMode === mode;
  return (
    <Button
      variant={on ? "solid" : "stroke"}
      icon={MapPin}
      aria-pressed={on}
      onClick={() => editor.toggleMapMode(mode)}
      block
    >
      {on ? active : idle}
    </Button>
  );
}

function RemoveButton({ what, onClick }: { what: string; onClick: () => void }) {
  return <IconButton icon={X} label={copy.remove(what)} on="surface-2" onClick={onClick} />;
}

/** Nome, identificativo (solo per un Evento nuovo) e descrizione. */
export function IdentitySection() {
  const editor = useEventEditor();
  return (
    <div className="flex flex-col gap-space-12 px-space-16 pb-space-16">
      <TextField
        id={fieldId(paths.name)}
        label={copy.name}
        value={editor.draft.name}
        error={editor.errors.get(paths.name)}
        onBlur={() => editor.touch(paths.name)}
        onChange={editor.setName}
      />
      {editor.isNew && (
        <TextField
          id={fieldId(paths.id)}
          label={copy.id}
          mono
          hint={copy.idHint}
          value={editor.draft.id}
          error={editor.errors.get(paths.id)}
          onBlur={() => editor.touch(paths.id)}
          onChange={editor.setId}
        />
      )}
      <EditorText
        path={paths.description}
        label={copy.description}
        get={(d) => d.description}
        set={(d, v) => ({ ...d, description: v })}
      />
    </div>
  );
}

/** La data e le due finestre (inizio, fine, picco). */
export function DatesSection() {
  return (
    <FormSection title={copy.dateWindows}>
      <EditorText
        path={paths.date}
        label={copy.date}
        type="date"
        mono
        get={(d) => d.date}
        set={(d, v) => ({ ...d, date: v })}
      />
      {WINDOWS.map((window) => (
        <fieldset key={window} className="flex flex-col gap-space-8">
          <legend className="mb-1.5 text-xs font-semibold text-text-primary">{copy[window]}</legend>
          <div className="grid grid-cols-3 gap-space-8">
            {(["start", "end", "peak"] as const).map((field) => (
              <EditorText
                key={field}
                path={paths.window(window, field)}
                label={`${copy[field]} ${copy[window].toLowerCase()}`}
                labelHidden
                placeholder={copy.timeFormat}
                mono
                inputMode="numeric"
                get={(d) => d[window][field]}
                set={(d, v) => ({ ...d, [window]: { ...d[window], [field]: v } })}
              />
            ))}
          </div>
          <div className="grid grid-cols-3 gap-space-8 text-xs text-text-secondary" aria-hidden>
            <span>{copy.start}</span>
            <span>{copy.end}</span>
            <span>{copy.peak}</span>
          </div>
        </fieldset>
      ))}
    </FormSection>
  );
}

/** Centro (con un clic sulla mappa) e raggio dell'area evento. */
export function AreaSection() {
  const editor = useEventEditor();
  const radius = Number.parseInt(editor.draft.radius, 10);
  const position = Number.isNaN(radius) ? RADIUS_SLIDER.min : radius;
  // quanta parte del cursore è riempita (in %): `.nuo-range` la legge da `--fill`
  const fill =
    (Math.min(Math.max(position, RADIUS_SLIDER.min), RADIUS_SLIDER.max) - RADIUS_SLIDER.min) /
    (RADIUS_SLIDER.max - RADIUS_SLIDER.min);
  return (
    <FormSection title={copy.area}>
      <MapModeButton mode="area" idle={copy.pickCenter} active={copy.pickingCenter} />
      <div className="grid grid-cols-2 gap-space-8">
        <EditorText
          path={paths.centerLat}
          label={copy.lat}
          mono
          inputMode="decimal"
          get={(d) => d.centerLat}
          set={(d, v) => ({ ...d, centerLat: v })}
        />
        <EditorText
          path={paths.centerLon}
          label={copy.lon}
          mono
          inputMode="decimal"
          get={(d) => d.centerLon}
          set={(d, v) => ({ ...d, centerLon: v })}
        />
      </div>
      <EditorText
        path={paths.centerLabel}
        label={copy.place}
        get={(d) => d.centerLabel}
        set={(d, v) => ({ ...d, centerLabel: v })}
      />
      <EditorText
        path={paths.radius}
        label={copy.radius}
        suffix={copy.meters}
        mono
        inputMode="numeric"
        get={(d) => d.radius}
        set={(d, v) => ({ ...d, radius: v })}
      />
      <input
        type="range"
        aria-label={copy.radiusSlider}
        min={RADIUS_SLIDER.min}
        max={RADIUS_SLIDER.max}
        step={RADIUS_SLIDER.step}
        value={position}
        onChange={(event) =>
          editor.edit((d) => ({ ...d, radius: event.target.value }), [paths.radius])
        }
        className="nuo-range"
        style={{ "--fill": `${fill * 100}%` } as React.CSSProperties}
      />
    </FormSection>
  );
}

/** I tre livelli di affluenza, quale usa l'analisi e il numero del livello scelto. */
export function AttendanceSection() {
  const editor = useEventEditor();
  const { draft, level } = editor;
  const names = copy.levels;
  const others = LEVELS.filter((l) => l !== level).flatMap((l) => {
    const message = editor.errors.get(paths.attendance(l));
    return message ? [{ level: l, message }] : [];
  });
  return (
    <FormSection title={copy.attendance} aside={<Badge kind="simulated" />}>
      <div role="radiogroup" aria-label={copy.levelLabel} className="flex gap-space-8">
        {LEVELS.map((l) => {
          const active = l === level;
          return (
            <button
              key={l}
              type="button"
              role="radio"
              aria-checked={active}
              onClick={() => editor.setLevel(l)}
              className={cn(
                "flex h-14 flex-1 flex-col items-center justify-center rounded-control border-control border-border text-text-secondary transition-base hover:bg-surface-2",
                active && "border-action bg-state-fill-running text-text-primary",
              )}
            >
              <span className="text-xs">{names[l]}</span>
              <span data-number="input" className="font-mono text-xs font-semibold tabular-nums">
                {draft.attendance[l] === "" ? "—" : draft.attendance[l]}
              </span>
            </button>
          );
        })}
      </div>
      <EditorText
        path={paths.attendance(level)}
        label={`${copy.attendance} · ${names[level].toLowerCase()}`}
        suffix={copy.people}
        mono
        inputMode="numeric"
        get={(d) => d.attendance[level]}
        set={(d, v) => ({ ...d, attendance: { ...d.attendance, [level]: v } })}
      />
      {others.map((item) => (
        <FieldMessage key={item.level} error={`${names[item.level]}: ${item.message}`} />
      ))}
      <EditorText
        path={paths.attendance("source_ref")}
        label={copy.attendanceSource}
        hint={copy.attendanceSourceHint}
        get={(d) => d.attendance.source}
        set={(d, v) => ({ ...d, attendance: { ...d.attendance, source: v } })}
      />
    </FormSection>
  );
}

/** Quota di capacità già occupata dal traffico di fondo nella fascia di picco, per finestra. */
export function BackgroundSection() {
  return (
    <FormSection title={copy.background} aside={<Badge kind="simulated" />}>
      <p className="text-xs text-text-secondary">{copy.backgroundHint}</p>
      <div className="grid grid-cols-2 gap-space-8">
        {WINDOWS.map((window) => (
          <EditorText
            key={window}
            path={paths.background(window)}
            label={copy[window]}
            suffix={copy.percent}
            mono
            inputMode="decimal"
            get={(d) => d.background[window]}
            set={(d, v) => ({ ...d, background: { ...d.background, [window]: v } })}
          />
        ))}
      </div>
    </FormSection>
  );
}

function Row({ icon, children }: { icon: typeof Ban; children: ReactNode }) {
  return (
    <li className="flex flex-col gap-space-8 rounded-control bg-surface-2 p-space-8">
      <div className="flex items-start gap-space-8">
        <Icon icon={icon} className="mt-3 text-text-secondary" />
        <div className="flex min-w-0 flex-1 flex-col gap-space-8">{children}</div>
      </div>
    </li>
  );
}

/** Le chiusure: una riga per strada (etichetta, fonte, quanti archi), scelte con un clic sulla mappa. */
export function ClosuresSection() {
  const editor = useEventEditor();
  const { closures } = editor.draft;
  return (
    <FormSection title={copy.closures} aside={<Badge kind="simulated" />}>
      <MapModeButton mode="closures" idle={copy.pickStreets} active={copy.pickingStreets} />
      {closures.length === 0 && <p className="text-xs text-text-secondary">{copy.closuresHint}</p>}
      <ul className="flex flex-col gap-space-8">
        {closures.map((closure, index) => (
          <Row key={`${closure.label}-${index}`} icon={Ban}>
            <div className="flex items-start gap-space-8">
              <EditorText
                className="flex-1"
                path={paths.closure(index, "label")}
                label={`${copy.closureLabel} ${index + 1}`}
                labelHidden
                get={(d) => d.closures[index]?.label ?? ""}
                set={(d, v) => ({
                  ...d,
                  closures: changeAt(d.closures, index, (c) => ({ ...c, label: v })),
                })}
              />
              <RemoveButton
                what={closure.label || `${strings.events.closures} ${index + 1}`}
                onClick={() =>
                  editor.edit((d) => ({ ...d, closures: removeAt(d.closures, index) }))
                }
              />
            </div>
            <p className="text-xs text-text-secondary">
              {copy.arcs((closure.edge_keys ?? []).length)}
              {closure.mode === "capacity_reduction" &&
                ` · ${copy.capacityReduced(Math.round(closure.capacity_factor * 100))}`}
            </p>
            <EditorText
              path={paths.closure(index, "source_ref")}
              label={`${copy.source} ${copy.closureLabel.toLowerCase()} ${index + 1}`}
              labelHidden
              placeholder={copy.source}
              get={(d) => d.closures[index]?.source_ref ?? ""}
              set={(d, v) => ({
                ...d,
                closures: changeAt(d.closures, index, (c) => ({
                  ...c,
                  source_ref: v.trim() === "" ? null : v,
                })),
              })}
            />
          </Row>
        ))}
      </ul>
    </FormSection>
  );
}

/** Le interruzioni del trasporto pubblico: una riga per fermata (etichetta, finestra, fonte). */
export function DisruptionsSection() {
  const editor = useEventEditor();
  const { disruptions } = editor.draft;
  const options = (["arrival", "departure", "both"] as const).map((value) => ({
    value,
    label: copy.windowOptions[value],
  }));
  return (
    <FormSection title={copy.disruptions} aside={<Badge kind="simulated" />}>
      <MapModeButton mode="stops" idle={copy.pickStops} active={copy.pickingStops} />
      {disruptions.length === 0 && (
        <p className="text-xs text-text-secondary">{copy.disruptionsHint}</p>
      )}
      <ul className="flex flex-col gap-space-8">
        {disruptions.map((item, index) => (
          <Row key={`${item.stop_name}-${index}`} icon={Bus}>
            <div className="flex items-start gap-space-8">
              <EditorText
                className="flex-1"
                path={paths.disruption(index, "label")}
                label={`${copy.closureLabel} ${item.stop_name}`}
                labelHidden
                get={(d) => d.disruptions[index]?.label ?? ""}
                set={(d, v) => ({
                  ...d,
                  disruptions: changeAt(d.disruptions, index, (x) => ({ ...x, label: v })),
                })}
              />
              <RemoveButton
                what={item.label || item.stop_name}
                onClick={() =>
                  editor.edit((d) => ({ ...d, disruptions: removeAt(d.disruptions, index) }))
                }
              />
            </div>
            <p className="text-xs text-text-secondary">
              {copy.stops((item.stop_ids ?? []).length)}
            </p>
            <EditorSelect
              path={paths.disruption(index, "window")}
              label={`${copy.window} ${item.stop_name}`}
              labelHidden
              options={options}
              get={(d) => d.disruptions[index]?.window ?? "both"}
              set={(d, v) => ({
                ...d,
                disruptions: changeAt(d.disruptions, index, (x) => ({
                  ...x,
                  window: v as "arrival" | "departure" | "both",
                })),
              })}
            />
            <EditorText
              path={paths.disruption(index, "source_ref")}
              label={`${copy.source} ${item.stop_name}`}
              labelHidden
              placeholder={copy.source}
              get={(d) => d.disruptions[index]?.source_ref ?? ""}
              set={(d, v) => ({
                ...d,
                disruptions: changeAt(d.disruptions, index, (x) => ({
                  ...x,
                  source_ref: v.trim() === "" ? null : v,
                })),
              })}
            />
          </Row>
        ))}
      </ul>
    </FormSection>
  );
}

/** Le risorse dei dipartimenti virtuali, una serie di numeri per finestra (D19). */
export function ResourcesSection() {
  const editor = useEventEditor();
  return (
    <FormSection title={copy.resources} defaultOpen={false}>
      {editor.draft.resources.map((item, index) => (
        <fieldset key={item.window} className="flex flex-col gap-space-8">
          <legend className="mb-1.5 text-xs font-semibold text-text-primary">
            {copy[item.window]}
          </legend>
          <div className="grid grid-cols-2 gap-space-8">
            {RESOURCE_FIELDS.map((field) => (
              <EditorText
                key={field}
                path={paths.resource(index, field)}
                label={`${copy.resourceFields[field]} · ${copy[item.window].toLowerCase()}`}
                mono
                inputMode="numeric"
                get={(d) => d.resources[index]?.values[field] ?? ""}
                set={(d, v) => ({
                  ...d,
                  resources: changeAt(d.resources, index, (r) => ({
                    ...r,
                    values: { ...r.values, [field]: v },
                  })),
                })}
              />
            ))}
          </div>
        </fieldset>
      ))}
    </FormSection>
  );
}

/** Misure adottate nella realtà (per il confronto) e fonti dell'Evento. */
export function ExtrasSection() {
  const editor = useEventEditor();
  const { realMeasures, sources } = editor.draft;
  return (
    <FormSection title={copy.extras} defaultOpen={false}>
      <h4 className="text-xs font-semibold text-text-primary">{copy.realMeasures}</h4>
      <ul className="flex flex-col gap-space-8">
        {realMeasures.map((measure, index) => (
          <li
            key={index}
            className="flex flex-col gap-space-8 rounded-control bg-surface-2 p-space-8"
          >
            <div className="flex items-start gap-space-8">
              <EditorText
                className="flex-1"
                path={paths.realMeasure(index, "label")}
                label={`${copy.measureLabel} ${index + 1}`}
                get={(d) => d.realMeasures[index]?.label ?? ""}
                set={(d, v) => ({
                  ...d,
                  realMeasures: changeAt(d.realMeasures, index, (m) => ({ ...m, label: v })),
                })}
              />
              <RemoveButton
                what={measure.label || `${copy.measureLabel} ${index + 1}`}
                onClick={() =>
                  editor.edit((d) => ({ ...d, realMeasures: removeAt(d.realMeasures, index) }))
                }
              />
            </div>
            {(
              [
                ["measure_type", copy.measureType],
                ["target", copy.measureTarget],
                ["source_ref", copy.source],
              ] as const
            ).map(([field, label]) => (
              <EditorText
                key={field}
                path={paths.realMeasure(index, field)}
                label={`${label} ${index + 1}`}
                get={(d) => d.realMeasures[index]?.[field] ?? ""}
                set={(d, v) => ({
                  ...d,
                  realMeasures: changeAt(d.realMeasures, index, (m) => ({ ...m, [field]: v })),
                })}
              />
            ))}
          </li>
        ))}
      </ul>
      <Button
        variant="ghost"
        icon={Plus}
        onClick={() =>
          editor.edit((d) => ({
            ...d,
            realMeasures: [
              ...d.realMeasures,
              { label: "", measure_type: "", target: "", source_ref: "" },
            ],
          }))
        }
      >
        {copy.addMeasure}
      </Button>

      <h4 className="text-xs font-semibold text-text-primary">{copy.sources}</h4>
      <ul className="flex flex-col gap-space-8">
        {sources.map((_, index) => (
          <li key={index} className="flex items-start gap-space-8">
            <EditorText
              className="flex-1"
              path={paths.source(index)}
              label={`${copy.source} ${index + 1}`}
              labelHidden
              get={(d) => d.sources[index] ?? ""}
              set={(d, v) => ({ ...d, sources: changeAt(d.sources, index, () => v) })}
            />
            <RemoveButton
              what={`${copy.source} ${index + 1}`}
              onClick={() => editor.edit((d) => ({ ...d, sources: removeAt(d.sources, index) }))}
            />
          </li>
        ))}
      </ul>
      <Button
        variant="ghost"
        icon={Plus}
        onClick={() => editor.edit((d) => ({ ...d, sources: [...d.sources, ""] }))}
      >
        {copy.addSource}
      </Button>
    </FormSection>
  );
}

/** Occupazione auto e ripartizione modale per tipo di zona: se vuoti valgono i predefiniti del modello. */
export function AdvancedSection() {
  const editor = useEventEditor();
  const { draft } = editor;
  return (
    <FormSection title={copy.advanced} defaultOpen={false}>
      <EditorText
        path={paths.carOccupancy}
        label={copy.carOccupancy}
        suffix={copy.carOccupancyUnit}
        hint={copy.carOccupancyHint}
        mono
        inputMode="decimal"
        get={(d) => d.carOccupancy}
        set={(d, v) => ({ ...d, carOccupancy: v })}
      />
      <h4 className="text-xs font-semibold text-text-primary">{copy.modalSplit}</h4>
      <p className="text-xs text-text-secondary">{copy.modalSplitHint}</p>
      {ZONE_TYPES.map((type) => (
        <fieldset key={type} className="flex flex-col gap-space-8">
          <legend className="mb-1.5 text-xs text-text-secondary">{copy.zoneTypes[type]}</legend>
          <div className="grid grid-cols-3 gap-space-8">
            {(["car", "transit", "walk"] as const).map((field) => (
              <EditorText
                key={field}
                path={paths.modalSplit(type, field)}
                label={`${copy.zoneTypes[type]} · ${copy[field]}`}
                labelHidden
                placeholder={copy[field]}
                suffix={copy.percent}
                mono
                inputMode="decimal"
                get={(d) => d.modalSplit[type]?.[field] ?? ""}
                set={(d, v) => ({
                  ...d,
                  modalSplit: { ...d.modalSplit, [type]: { ...d.modalSplit[type]!, [field]: v } },
                })}
              />
            ))}
          </div>
          <div className="grid grid-cols-3 gap-space-8 text-xs text-text-secondary" aria-hidden>
            <span>{copy.car}</span>
            <span>{copy.transit}</span>
            <span>{copy.walk}</span>
          </div>
        </fieldset>
      ))}
      {draft.zonesOverride && (
        <p className="text-xs text-text-secondary">{copy.ownZones(draft.zonesOverride.length)}</p>
      )}
      {draft.carDestinations && (
        <p className="text-xs text-text-secondary">
          {copy.ownDestinations(draft.carDestinations.length)}
        </p>
      )}
    </FormSection>
  );
}
