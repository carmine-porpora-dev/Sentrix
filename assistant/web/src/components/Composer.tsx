import clsx from "clsx";
import { TriangleAlert } from "lucide-react";
import { useLayoutEffect, useRef, type KeyboardEvent } from "react";
import { SendButton } from "@/components/SendButton";
import { COMPOSER_MAX_HEIGHT, COMPOSER_MIN_HEIGHT, MAX_MESSAGE_LENGTH } from "@/config";
import { strings } from "@/strings";

interface ComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  /** Il testo si può inviare: non vuoto, entro il limite, nessuna risposta in attesa. */
  canSend: boolean;
  /** Telefono: Invio va a capo e si invia solo col pulsante. */
  compact: boolean;
}

/** Il campo di scrittura, identico nella home e nella conversazione. */
export function Composer({ value, onChange, onSend, canSend, compact }: ComposerProps) {
  const field = useRef<HTMLTextAreaElement>(null);
  const tooLong = value.length > MAX_MESSAGE_LENGTH;

  useLayoutEffect(() => {
    const element = field.current;
    if (!element) return;
    element.style.height = `${COMPOSER_MIN_HEIGHT}px`;
    element.style.height = `${Math.min(Math.max(element.scrollHeight, COMPOSER_MIN_HEIGHT), COMPOSER_MAX_HEIGHT)}px`;
  }, [value]);

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== "Enter" || event.shiftKey || compact || event.nativeEvent.isComposing) return;
    event.preventDefault();
    if (canSend) onSend();
  };

  const send = () => {
    onSend();
    field.current?.focus();
  };

  return (
    <div>
      <div
        className={clsx(
          "flex items-end gap-2 rounded-field border py-[5px] pl-4 pr-[5px] transition-[border-color,box-shadow]",
          tooLong
            ? "border-danger shadow-[0_0_0_1px_var(--color-danger)]"
            : "border-border-strong focus-within:border-accent focus-within:shadow-[0_0_0_1px_var(--color-accent)]",
        )}
      >
        <textarea
          ref={field}
          rows={1}
          value={value}
          placeholder={strings.composer.placeholder}
          aria-label={strings.composer.label}
          aria-invalid={tooLong}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={onKeyDown}
          className="no-scrollbar m-0 block min-h-10 max-h-28 min-w-0 flex-1 resize-none overflow-y-auto border-0 bg-transparent px-0 py-2 font-ui text-md text-text shadow-none outline-none placeholder:text-text-secondary placeholder:opacity-100"
        />
        <SendButton enabled={canSend} onClick={send} />
      </div>
      {tooLong && (
        <div role="alert" className="mt-2 flex items-center gap-2 text-xs text-danger">
          <TriangleAlert aria-hidden="true" size={16} strokeWidth={1.5} />
          {strings.composer.tooLong}
        </div>
      )}
    </div>
  );
}
