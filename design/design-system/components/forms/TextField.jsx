import React from 'react';
import { Icon } from '../core/Icon.jsx';
export function TextField({label,value,onChange,placeholder,suffix,mono=false,error,disabled=false,hint,id,inputMode}){
  const fid=id||('f-'+(label||'x').replace(/\W/g,''));
  return <div className="nuo-field">
    {label&&<label className="nuo-field__label" htmlFor={fid}>{label}</label>}
    <div className={'nuo-input'+(mono?' nuo-input--mono':'')+(error?' is-error':'')+(disabled?' is-disabled':'')}>
      <input id={fid} value={value} placeholder={placeholder} disabled={disabled} inputMode={inputMode} aria-invalid={!!error} onChange={(e)=>onChange&&onChange(e.target.value)} />
      {suffix&&<span className="nuo-input__suffix">{suffix}</span>}
    </div>
    {error?<div className="nuo-field__msg"><Icon name="triangle-alert" size={16} />{error}</div>:hint?<div className="nuo-field__hint">{hint}</div>:null}
  </div>;
}
