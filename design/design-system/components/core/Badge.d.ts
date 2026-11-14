import * as React from 'react';
export interface BadgeProps{
  kind?:'real'|'estimate'|'simulated'|'unavailable'|'pending';
  /** Sovrascrive l'etichetta di default */
  children?:React.ReactNode;
}
export declare function Badge(props:BadgeProps):JSX.Element;
