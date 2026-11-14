import * as React from 'react';
export interface ModeSelectorProps{
  value?:'live'|'scenario';
  onChange?:(v:'live'|'scenario')=>void;
}
export declare function ModeSelector(props:ModeSelectorProps):JSX.Element;
