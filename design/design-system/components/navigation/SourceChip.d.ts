import * as React from 'react';
export interface SourceChipProps{
  /** Nomi delle fonti non disponibili. Vuoto = non renderizza */
  sources:string[];
  /** Parte con il popover aperto (300px). Clic lo apre, Esc lo chiude */
  defaultOpen?:boolean;
}
export declare function SourceChip(props:SourceChipProps):JSX.Element|null;
