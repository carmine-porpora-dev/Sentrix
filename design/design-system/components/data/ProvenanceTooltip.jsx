import React from 'react';
import { Badge } from '../core/Badge.jsx';
export function ProvenanceTooltip({title,badge='real',rows=[],floating=false}){
  return <div className={'nuo-prov'+(floating?' nuo-prov--float':'')} role="tooltip">
    <div className="nuo-prov__head"><span className="nuo-prov__title">{title}</span>{badge&&<Badge kind={badge} />}</div>
    {rows.map((r)=><div className="nuo-prov__row" key={r[0]}><span className="nuo-prov__k">{r[0]}</span><span className="nuo-prov__v">{[].concat(r[1]).map((l,i)=><span key={i}>{l}</span>)}</span></div>)}
  </div>;
}
