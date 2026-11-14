import * as React from 'react';
export interface EventManagerHeaderProps{
  /** Chip "In corso" accanto al titolo */
  running?:boolean;
  /** Variante fissa senza chevron: pannello sempre aperto (schermate da compilare) */
  fixed?:boolean;
  onToggle?:()=>void;
}
export declare function EventManagerHeader(props:EventManagerHeaderProps):JSX.Element;
