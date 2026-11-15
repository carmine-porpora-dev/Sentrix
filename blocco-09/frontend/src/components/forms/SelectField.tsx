import { ChevronDown } from "lucide-react";
import type { ReactNode } from "react";
import { Icon } from "@/components/Icon";
import { FieldMessage } from "@/components/forms/TextField";
import { cn } from "@/lib/utils";

export interface SelectOption {
  value: string;
  label: string;
}

/** Un elenco a tendina con l'aspetto di un campo del design system (il menu è quello del browser:
 * si usa con la tastiera e funziona con le tecnologie assistive). */
export function SelectField({
  id,
  label,
  value,
  options,
  onChange,
  error,
  disabled = false,
  labelHidden = false,
  labelAside,
  className,
}: {
  id: string;
  label?: string;
  value: string;
  options: readonly SelectOption[];
  onChange: (value: string) => void;
  error?: string;
  disabled?: boolean;
  labelHidden?: boolean;
  /** Qualcosa a destra dell'etichetta (un chip). */
  labelAside?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex min-w-0 flex-col gap-1.5", className)}>
      {label && (
        <div className="flex items-center justify-between gap-space-8">
          <label
            htmlFor={id}
            className={cn("text-xs text-text-secondary", labelHidden && "sr-only")}
          >
            {label}
          </label>
          {labelAside}
        </div>
      )}
      <div
        className={cn(
          "relative flex h-size-control-height items-center rounded-control border-control border-transparent border-b-text-muted bg-surface-2 transition-base hover:bg-surface-3 focus-within:border-b-action",
          error && "border-b-danger focus-within:border-b-danger",
          disabled && "cursor-not-allowed bg-surface-1 hover:bg-surface-1",
        )}
      >
        <select
          id={id}
          value={value}
          disabled={disabled}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? `${id}-msg` : undefined}
          onChange={(event) => onChange(event.target.value)}
          className="h-full w-full min-w-0 appearance-none truncate bg-transparent pl-space-12 pr-9 text-md text-text-primary outline-none disabled:cursor-not-allowed disabled:text-text-muted"
        >
          {options.map((option) => (
            <option key={option.value} value={option.value} className="bg-surface-2">
              {option.label}
            </option>
          ))}
        </select>
        <Icon
          icon={ChevronDown}
          className="pointer-events-none absolute right-space-12 text-text-secondary"
        />
      </div>
      <FieldMessage id={`${id}-msg`} error={error} />
    </div>
  );
}
