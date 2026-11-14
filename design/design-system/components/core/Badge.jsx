import React from 'react';
import { Icon } from './Icon.jsx';
const KINDS={real:['REALE','activity'],estimate:['STIMA','waves'],simulated:['SIMULATO','flask-conical'],unavailable:['Non disponibile','minus'],pending:['In attesa','clock']};
export function Badge({kind='real',children}){
  const k=KINDS[kind]||KINDS.real;
  return <span className={'nuo-badge nuo-badge--'+kind}><Icon name={k[1]} size={14} />{children||k[0]}</span>;
}
