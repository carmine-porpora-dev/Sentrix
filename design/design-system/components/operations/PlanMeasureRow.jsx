import React from 'react';
import { Icon, DEPARTMENTS } from '../core/Icon.jsx';
export function PlanMeasureRow({n,text,dept='traffic'}){
  const d=DEPARTMENTS[dept];
  return <div className="nuo-meas"><span className="nuo-meas__n">{n}</span><div className="nuo-meas__body"><div className="nuo-meas__text">{text}</div>
    <div className="nuo-meas__dept"><Icon name="arrow-right" size={16} /><Icon name={d.icon} size={16} />{d.name}</div></div></div>;
}
