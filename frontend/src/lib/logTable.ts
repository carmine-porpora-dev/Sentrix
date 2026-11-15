export const logTable = {
  frame: "overflow-x-auto rounded-card-inner bg-surface-2",
  table: "w-full border-collapse text-left text-sm",
  headRow: "border-b-hairline border-border-strong",
  headCell: "px-space-12 py-2.5 text-sm font-semibold text-text-secondary",
  row: "group border-b-hairline border-border transition-base last:border-b-0 hover:bg-row-hover",
  /** La prima cella di una riga del corpo: porta la linea di 2 px che si accende con il mouse. */
  firstCell:
    "relative before:absolute before:inset-y-0 before:left-0 before:w-0.5 before:bg-accent before:opacity-0 before:transition-opacity group-hover:before:opacity-100",
} as const;
