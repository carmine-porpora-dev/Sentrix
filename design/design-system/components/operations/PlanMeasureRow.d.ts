import * as React from 'react';
export interface PlanMeasureRowProps{
  n:number;
  text:string;
  dept:'traffic'|'police'|'transport'|'comms';
}
export declare function PlanMeasureRow(props:PlanMeasureRowProps):JSX.Element;
