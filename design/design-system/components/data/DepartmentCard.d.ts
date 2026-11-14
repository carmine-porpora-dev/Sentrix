import * as React from 'react';
export interface DepartmentCardProps{
  dept?:'traffic'|'police'|'transport'|'comms';
  remaining:number;
  total:number;
}
export declare function DepartmentCard(props:DepartmentCardProps):JSX.Element;
