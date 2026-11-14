import React from 'react';
import { Icon } from '../core/Icon.jsx';
import { Button } from '../core/Button.jsx';
import { TextField } from '../forms/TextField.jsx';
const PRESETS=[50000,150000,300000];
const fmt=(n)=>new Intl.NumberFormat('it-IT',{useGrouping:'always'}).format(n);
function List({icon,items,onRemove,hint}){
  return <div className="nuo-em__list">{items.map((s,i)=><div className="nuo-em__row" key={s+i}><Icon name={icon} size={16} /><span>{s}</span><button type="button" className="nuo-em__rm" aria-label={'Rimuovi '+s} onClick={()=>onRemove&&onRemove(i)}><Icon name="x" size={16} /></button></div>)}<div className="nuo-field__hint">{hint}</div></div>;
}
export function EventManager({attendance='',onAttendanceChange,closures=[],stops=[],onRemoveClosure,onRemoveStop,onAnalyze,analyzing=false}){
  const n=parseInt(String(attendance).replace(/\D/g,''),10);
  const invalid=attendance!==''&&!/^[\d.]+$/.test(attendance);
  const disabled=attendance===''||invalid||!n;
  return <div className="nuo-card nuo-em">
    <div className="nuo-field"><span className="nuo-field__label">Affluenza prevista</span>
      <div className="nuo-em__presets">{PRESETS.map((p)=><button key={p} type="button" className={'nuo-preset'+(n===p?' is-on':'')} onClick={()=>onAttendanceChange&&onAttendanceChange(fmt(p))}>{fmt(p)}</button>)}</div>
      <TextField value={attendance} onChange={onAttendanceChange} placeholder="es. 150.000" suffix="persone" mono inputMode="numeric" error={invalid?'Inserisci un numero valido':undefined} id="em-attendance" /></div>
    <div className="nuo-field"><span className="nuo-field__label">Chiusure strada</span><List icon="ban" items={closures} onRemove={onRemoveClosure} hint="Clicca una strada sulla mappa per chiuderla" /></div>
    <div className="nuo-field"><span className="nuo-field__label">Interruzioni fermata</span><List icon="bus" items={stops} onRemove={onRemoveStop} hint="Clicca una fermata sulla mappa" /></div>
    <Button block loading={analyzing} disabled={disabled} onClick={onAnalyze}>Analizza</Button>
  </div>;
}
