import * as React from 'react';
export interface MapToggleProps{
  after?:boolean;
  onAfterChange?:(v:boolean)=>void;
  iteration?:number;
  onIterationChange?:(n:number)=>void;
  iterations?:number;
}
export declare function MapToggle(props:MapToggleProps):JSX.Element;
