import React from 'react';
import { Icon } from '../core/Icon.jsx';
import { Badge } from '../core/Badge.jsx';
import { ProvenanceTooltip } from './ProvenanceTooltip.jsx';
export function MetricCard({label,value,before,unit,delta,badge,loading=false,compact=false,provenance,showProvenance=false}){
  if(loading)return <div className="nuo-metric" aria-busy="true"><span className="nuo-loadbar" />
    <div className="nuo-skel" style={{width:130,height:20}} /><div className="nuo-skel" style={{width:160,height:40}} />
    <div className="nuo-metric__foot"><span className="nuo-metric__label">In caricamento…</span><div className="nuo-skel" style={{width:76,height:28}} /></div></div>;
  const hasBefore=before!=null;
  const b=badge===undefined?(hasBefore?'simulated':'real'):badge;
  const small=compact||hasBefore||String(value||'').length>=7;
  const d=delta||{};const tone=d.tone||'neutral';
  const dIcon=tone==='neutral'?'minus':d.direction==='down'?'arrow-down':'arrow-up';
  const card=<div className={'nuo-metric'+(small?' is-sm':'')} tabIndex={provenance?0:undefined}>
    <div className="nuo-metric__label">{label}</div>
    <div className="nuo-metric__value">{hasBefore&&<><span className="nuo-metric__before">{before}</span><Icon name="arrow-right" size={24} /></>}{value}{unit&&<span className="nuo-metric__unit">{unit}</span>}</div>
    <div className="nuo-metric__foot">
      {delta?<span className={'nuo-delta nuo-delta--'+tone}><Icon name={dIcon} size={16} />{d.text||'0,0%'}</span>:<span />}
      {b&&<Badge kind={b} />}
    </div>
  </div>;
  if(!provenance)return card;
  return <div className={'nuo-mc'+(showProvenance?' is-tip':'')}>{card}<ProvenanceTooltip floating title={provenance.title||label} badge={provenance.badge===undefined?b:provenance.badge} rows={provenance.rows} /></div>;
}
