import React from 'react';
import { Icon } from '../core/Icon.jsx';
import { Tooltip } from '../core/Tooltip.jsx';
const STEPS=['INTAKE','ANALYZE','RECONCILE','PLAN','DISPATCH','AWAIT','REPLAN','VERIFY','DONE'];
const S={INTAKE:['Acquisizione'],ANALYZE:['Analisi'],RECONCILE:['Riconciliazione'],PLAN:['Pianificazione'],DISPATCH:['Invio richieste'],AWAIT:['In attesa risposte','warn','clock'],REPLAN:['Ripianificazione'],VERIFY:['Verifica'],DONE:['Completato','done','check'],ERRORE:['Errore','error','triangle-alert'],DECISIONE:['Decisione richiesta','warn','user']};
const KIND={run:['var(--color-accent)','var(--color-state-fill-running)'],warn:['var(--color-warning)','var(--color-state-fill-waiting)'],done:['var(--color-data-real)','var(--color-state-fill-done)'],error:['var(--color-danger)','var(--color-state-fill-error)']};
export function RunStatus({state='INTAKE',step=0}){
  const s=S[state]||S.INTAKE;const kind=s[1]||'run';const [c,f]=KIND[kind];
  const cur=STEPS.indexOf(state)>=0?STEPS.indexOf(state):step;
  return <div className="nuo-run">
    <Tooltip content={<span style={{fontFamily:'var(--font-mono)'}}>{state==='DECISIONE'?'DECISIONE UMANA RICHIESTA':state}</span>} placement="bottom">
      <span className="nuo-chip" style={{'--c':c,'--f':f}}>{s[2]?<Icon name={s[2]} size={16} />:<span className="nuo-dot nuo-dot--pulse" />}{s[0]}</span>
    </Tooltip>
    <div className={'nuo-steps'+(state==='DONE'?' nuo-steps--done':'')}>{STEPS.map((k,i)=><i key={k} className={'nuo-step'+(i<cur||state==='DONE'?' is-done':'')+(i===cur&&state!=='DONE'?' is-current':'')+(i===cur&&state==='ERRORE'?' is-error':'')+(i===cur&&(kind==='warn')?' is-warn':'')} />)}</div>
  </div>;
}
