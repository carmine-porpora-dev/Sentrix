import React from 'react';
export function Tabs({items=[],active,onChange}){
  return <div className="nuo-tabs" role="tablist">{items.map((t)=><button key={t.id} type="button" role="tab" aria-selected={active===t.id} className={'nuo-tab'+(active===t.id?' is-active':'')} onClick={()=>onChange&&onChange(t.id)}>{t.label}</button>)}</div>;
}
