import React from 'react';
import { Icon, DEPARTMENTS } from '../core/Icon.jsx';
export function DepartmentCard({dept='traffic',remaining=0,total=0}){
  const d=DEPARTMENTS[dept];
  return <div className="nuo-dept">
    <div className="nuo-dept__head"><span className="nuo-dept__icon"><Icon name={d.icon} /></span><span className="nuo-dept__name">{d.name}</span></div>
    <div><div><span className={'nuo-dept__num'+(remaining===0?' is-zero':'')}>{remaining}</span><span className="nuo-dept__of"> / {total}</span></div><div className="nuo-dept__unit">{d.unit}</div></div>
    <div className="nuo-bar"><i style={{width:(total?remaining/total*100:0)+'%'}} /></div>
  </div>;
}
