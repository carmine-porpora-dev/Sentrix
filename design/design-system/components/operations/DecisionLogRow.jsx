import React from 'react';
import { Icon, DEPARTMENTS } from '../core/Icon.jsx';
const A={system:['cpu','Sistema'],agent:['bot','Agente'],user:['user','Utente']};
export function DecisionLogRow({time,actor='system',actorLabel,decision,reason,head=false,variant='wide',hover=false}){
  const vc=variant==='log'?' nuo-logrow--log':'';
  if(head)return <div className={'nuo-logrow is-head'+vc}><span>Ora</span><span>Attore</span><span>Decisione e motivo</span></div>;
  const a=DEPARTMENTS[actor]?[DEPARTMENTS[actor].icon,DEPARTMENTS[actor].name]:(A[actor]||A.system);
  return <div className={'nuo-logrow'+vc+(hover?' is-hover':'')}><span className="nuo-logrow__time">{time}</span>
    <span className="nuo-logrow__actor"><Icon name={a[0]} size={16} />{actorLabel||a[1]}</span>
    <span><div className="nuo-logrow__dec">{decision}</div>{reason&&<div className="nuo-logrow__why">{reason}</div>}</span></div>;
}
