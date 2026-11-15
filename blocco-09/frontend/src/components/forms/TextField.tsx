import { TriangleAlert } from "lucide-react";
import type { HTMLInputTypeAttribute, ReactNode } from "react";
import { Icon } from "@/components/Icon";
import { cn } from "@/lib/utils";

export interface TextFieldProps {
  id: string;
  label?: string;
  value: string;
  onChange: (value: string) => void;
  onBlur?: () => void;
  type?: HTMLInputTypeAttribute;
  placeholder?: string;
  /** L'unità, a destra del valore («persone», «%»). */
  suffix?: string;
  /** Cifre in carattere monospazio (numeri, orari, coordinate). */
  mono?: boolean;
  /** Il messaggio di errore del campo: lo disegna in rosso sotto il campo. */
  error?: string;
  hint?: string;
  disabled?: boolean;
  inputMode?: "text" | "numeric" | "decimal";
  /** L'etichetta c'è per le tecnologie assistive ma non si vede (campi dentro una riga che già la spiega). */
  labelHidden?: boolean;
  className?: string;
}

/** Il campo di testo del design system: etichetta sopra, bordo inferiore che dice lo stato (fuoco,
 * errore), unità a destra, messaggio sotto. L'errore è sempre testo, non solo colore. */
export function TextField({
  id,
  label,
  value,
  onChange,
  onBlur,
  type = "text",
  placeholder,
  suffix,
  mono = false,
  error,
  hint,
  disabled = false,
  inputMode,
  labelHidden = false,
  className,
}: TextFieldProps) {
  return (
    <div className={cn("flex min-w-0 flex-col gap-1.5", className)}>
      {label && (
        <label htmlFor={id} className={cn("text-xs text-text-secondary", labelHidden && "sr-only")}>
          {label}
        </label>
      )}
      <div
        className={cn(
          "flex h-size-control-height items-center gap-space-8 rounded-control border-control border-transparent border-b-text-muted bg-surface-2 px-space-12 transition-base hover:bg-surface-3 focus-within:bg-surface-2 focus-within:border-b-action",
          error && "border-b-danger focus-within:border-b-danger",
          disabled && "cursor-not-allowed bg-surface-1 hover:bg-surface-1",
        )}
      >
        <input
          id={id}
          type={type}
          value={value}
          placeholder={placeholder}
          disabled={disabled}
          inputMode={inputMode}
          aria-invalid={error ? true : undefined}
          aria-describedby={error || hint ? `${id}-msg` : undefined}
          onChange={(event) => onChange(event.target.value)}
          onBlur={onBlur}
          className={cn(
            "h-full min-w-0 flex-1 bg-transparent text-md text-text-primary outline-none placeholder:text-text-secondary disabled:cursor-not-allowed disabled:text-text-muted",
            mono && "font-mono tabular-nums",
          )}
        />
        {suffix && <span className="flex-none text-xs text-text-secondary">{suffix}</span>}
      </div>
      <FieldMessage id={`${id}-msg`} error={error} hint={hint} />
    </div>
  );
}

/** Il messaggio sotto un campo: l'errore (con icona) o, se non c'è, il suggerimento. */
export function FieldMessage({
  id,
  error,
  hint,
}: {
  id?: string;
  error?: string;
  hint?: ReactNode;
}) {
  if (error) {
    return (
      <div id={id} className="flex items-start gap-1.5 text-xs text-danger">
        <Icon icon={TriangleAlert} size="inline" className="mt-px" />
        <span>{error}</span>
      </div>
    );
  }
  return hint ? (
    <div id={id} className="text-xs text-text-secondary">
      {hint}
    </div>
  ) : null;
}
