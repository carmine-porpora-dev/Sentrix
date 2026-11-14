import * as React from 'react';
export interface EventManagerRailProps{
  /** Run attivo: chip "In corso" + barra scorrevole in alto */
  running?:boolean;
  /** Stato del pannello (aria-expanded); chevron-down per aprire */
  open?:boolean;
  onToggle?:()=>void;
  /** Per specimen: is-hover, is-focus */
  className?:string;
}
export declare function EventManagerRail(props:EventManagerRailProps):JSX.Element;
