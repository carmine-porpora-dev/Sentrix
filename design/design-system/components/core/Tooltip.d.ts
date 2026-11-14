import * as React from 'react';
export interface TooltipProps{
  content:React.ReactNode;
  placement?:'top'|'bottom';
  /** Forza apertura (per specimen) */
  open?:boolean;
  children:React.ReactNode;
}
export declare function Tooltip(props:TooltipProps):JSX.Element;
