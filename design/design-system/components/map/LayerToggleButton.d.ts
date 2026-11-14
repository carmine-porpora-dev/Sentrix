import * as React from 'react';
export interface LayerToggleButtonProps{
  open?:boolean;
  onToggle?:()=>void;
  /** Per specimen: is-hover, is-focus */
  className?:string;
}
export declare function LayerToggleButton(props:LayerToggleButtonProps):JSX.Element;
