import * as React from 'react';
export interface FieldHeaderProps{
  label:string;
  /** Badge dato a destra, es. 'estimate' su Affluenza prevista e Ripartizione modale */
  badge?:'real'|'estimate'|'simulated'|'unavailable'|null;
}
export declare function FieldHeader(props:FieldHeaderProps):JSX.Element;
