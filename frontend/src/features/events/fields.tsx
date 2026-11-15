import { SelectField, type SelectOption } from "@/components/forms/SelectField";
import { TextField, type TextFieldProps } from "@/components/forms/TextField";
import { useEventEditor } from "@/features/events/EventEditor";
import type { EventDraft } from "@/features/events/draft";

type Shared = Pick<
  TextFieldProps,
  | "label"
  | "suffix"
  | "mono"
  | "hint"
  | "type"
  | "inputMode"
  | "placeholder"
  | "className"
  | "labelHidden"
  | "disabled"
>;

/** Il campo `id` di un percorso (unico nel form: i percorsi contengono gli indici). */
export const fieldId = (path: string): string => `ev-${path.replace(/\./g, "-")}`;

/** Un campo di testo del form: legge dalla bozza, scrive nella bozza, mostra l'errore del suo
 * percorso (dell'API o del form) e segna il campo come toccato quando si esce. Chi scrive un valore
 * toglie l'errore dell'API su quel campo: si sta correggendo. */
export function EditorText({
  path,
  get,
  set,
  ...rest
}: Shared & {
  path: string;
  get: (draft: EventDraft) => string;
  set: (draft: EventDraft, value: string) => EventDraft;
}) {
  const editor = useEventEditor();
  return (
    <TextField
      {...rest}
      id={fieldId(path)}
      value={get(editor.draft)}
      error={editor.errors.get(path)}
      onBlur={() => editor.touch(path)}
      onChange={(value) => editor.edit((draft) => set(draft, value), [path])}
    />
  );
}

export function EditorSelect({
  path,
  options,
  get,
  set,
  ...rest
}: {
  path: string;
  options: readonly SelectOption[];
  label?: string;
  labelHidden?: boolean;
  className?: string;
  get: (draft: EventDraft) => string;
  set: (draft: EventDraft, value: string) => EventDraft;
}) {
  const editor = useEventEditor();
  return (
    <SelectField
      {...rest}
      id={fieldId(path)}
      value={get(editor.draft)}
      options={options}
      error={editor.errors.get(path)}
      onChange={(value) => editor.edit((draft) => set(draft, value), [path])}
    />
  );
}

/** La lista senza l'elemento `index`. */
export const removeAt = <T,>(list: readonly T[], index: number): T[] =>
  list.filter((_, position) => position !== index);

/** La lista con l'elemento `index` cambiato. */
export const changeAt = <T,>(list: readonly T[], index: number, change: (item: T) => T): T[] =>
  list.map((item, position) => (position === index ? change(item) : item));
