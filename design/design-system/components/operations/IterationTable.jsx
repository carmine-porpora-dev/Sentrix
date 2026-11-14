import React from 'react';
import { Badge } from '../core/Badge.jsx';
export function IterationTable({columns=['Iter. 1','Iter. 2','Iter. 3'],rows=[],hoverRow=-1}){
  return <div className="nuo-log"><div className="nuo-logrow nuo-logrow--compare is-head"><span>Metrica</span>{columns.map((c)=><span key={c}>{c}</span>)}</div>
    {rows.map((r,i)=><div key={r.metric} className={'nuo-logrow nuo-logrow--compare'+(hoverRow===i?' is-hover':'')}>
      <span className="nuo-cmp__metric"><span className="nuo-cmp__name">{r.metric}</span>{r.badge&&<Badge kind={r.badge} />}</span>
      {r.values.map((v,k)=><span className="nuo-cmp__val" key={k}>{v}</span>)}</div>)}
  </div>;
}
