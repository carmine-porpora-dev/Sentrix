import { Loader2, type LucideIcon } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Icon } from "@/components/Icon";
import { cn } from "@/lib/utils";

type Variant = "solid" | "stroke" | "ghost";

const VARIANTS: Record<Variant, string> = {
  solid: "bg-action text-bg hover:bg-action-hover disabled:bg-surface-1 disabled:text-text-muted",
  stroke:
    "border-action text-action hover:bg-action hover:text-bg disabled:border-text-muted disabled:bg-transparent disabled:text-text-muted disabled:hover:bg-transparent",
  ghost:
    "text-text-primary hover:bg-surface-2 active:bg-surface-3 disabled:bg-transparent disabled:text-text-muted disabled:hover:bg-transparent",
};

interface ButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "className"> {
  variant?: Variant;
  /** Largo quanto il contenitore. */
  block?: boolean;
  /** L'azione è in corso: il pulsante non risponde ai clic e lo dice con un indicatore. */
  loading?: boolean;
  icon?: LucideIcon;
  children?: ReactNode;
  className?: string;
}

/** Il pulsante del design system (`nuo-btn`): pieno, con bordo o senza; alto quanto un campo. */
export function Button({
  variant = "solid",
  block = false,
  loading = false,
  icon,
  children,
  className,
  disabled,
  type = "button",
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cn(
        "inline-flex h-size-control-height min-w-size-control-height items-center justify-center gap-space-8 whitespace-nowrap rounded-control border-control border-transparent px-[18px] text-sm font-semibold transition-base disabled:cursor-not-allowed",
        VARIANTS[variant],
        block && "w-full",
        loading && "pointer-events-none",
        className,
      )}
      {...rest}
    >
      {loading ? (
        <Icon icon={Loader2} className="motion-safe:animate-spin" />
      ) : (
        icon && <Icon icon={icon} />
      )}
      {children}
    </button>
  );
}
