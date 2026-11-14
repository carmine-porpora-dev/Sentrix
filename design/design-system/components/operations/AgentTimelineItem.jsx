import React from 'react';
import { Icon } from '../core/Icon.jsx';
const T={waiting:['var(--color-text-muted)','clock','In attesa'],running:['var(--color-accent)','loader-2','In esecuzione…'],done:['var(--color-success)','check','Completato'],fallback:['var(--color-warning)','check','Completato con testo di riserva'],error:['var(--color-danger)','triangle-alert','Errore']};
export function AgentTimelineItem({name,status='waiting',duration,note,last=false}){
  const t=T[status]||T.waiting;
  return <div className={'nuo-tl is-'+status+(last?' is-last':'')}>
    {!last&&<span className="nuo-tl__line" />}
    <span className="nuo-tl__node" style={{'--c':t[0]}}><Icon name={t[1]} size={16} spin={status==='running'} /></span>
    <div className="nuo-tl__body"><div className="nuo-tl__row"><span className="nuo-tl__name">{name}</span><span className="nuo-tl__dur">{duration||'—'}</span></div><div className="nuo-tl__desc">{note||t[2]}</div></div>
  </div>;
}
