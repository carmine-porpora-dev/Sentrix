import React from 'react';
export function ManualSwitch({checked=false,onChange}){
  return <div className="nuo-switchbox">
    <button type="button" role="switch" aria-checked={checked} className={'nuo-switch'+(checked?' is-on':'')} onClick={()=>onChange&&onChange(!checked)}>
      <span className={'nuo-track'+(checked?' is-on':'')} />Risposta manuale<span className="nuo-switch__state">{checked?'On':'Off'}</span>
    </button>
    <div className="nuo-field__hint">{checked?'Accetti o rifiuti tu le richieste dei dipartimenti.':'I dipartimenti rispondono in automatico.'}</div>
  </div>;
}
