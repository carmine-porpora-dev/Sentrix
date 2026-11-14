import React from 'react';
import { Icon, DEPARTMENTS } from '../core/Icon.jsx';
const R={CREATED:['Creata','var(--color-status-pending)','plus'],SENT:['Inviata','var(--color-status-pending)','send'],RECEIVED:['Ricevuta','var(--color-status-pending)','mail'],ACCEPTED:['Accettata','var(--color-status-accepted)','check'],REJECTED:['Rifiutata','var(--color-status-rejected)','x'],IN_PROGRESS:['In corso','var(--color-status-pending)',null],COMPLETED:['Completata','var(--color-status-accepted)','check-check']};
const FILL={'var(--color-status-pending)':'var(--color-state-fill-waiting)','var(--color-status-accepted)':'var(--color-state-fill-done)','var(--color-status-rejected)':'var(--color-state-fill-error)'};
export function RequestCard({dept='traffic',code,status='CREATED',measure,rejection,alternativeTo}){
  const r=R[status]||R.CREATED;
  return <div className={'nuo-req'+(alternativeTo?' nuo-req--alt':'')}>
    {alternativeTo&&<div className="nuo-req__alt"><Icon name="corner-up-left" size={16} />Alternativa a {alternativeTo}</div>}
    <div className="nuo-req__head"><div><div className="nuo-req__dept">{DEPARTMENTS[dept].name}</div><div className="nuo-req__code">{code}</div></div>
      <span className="nuo-chip nuo-chip--sm" style={{'--c':r[1],'--f':FILL[r[1]]}}>{r[2]?<Icon name={r[2]} size={16} />:<span className="nuo-dot nuo-dot--pulse" />}{r[0]}</span></div>
    <div className="nuo-req__measure">{measure}</div>
    {status==='REJECTED'&&rejection&&<div className="nuo-req__rej"><b>{rejection.code}</b>{rejection.reason}</div>}
  </div>;
}
