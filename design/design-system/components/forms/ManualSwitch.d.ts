import * as React from 'react';
export interface ManualSwitchProps{
  checked?:boolean;
  onChange?:(v:boolean)=>void;
}
export declare function ManualSwitch(props:ManualSwitchProps):JSX.Element;
