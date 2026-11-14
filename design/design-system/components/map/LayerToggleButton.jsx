import React from 'react';
import { Icon } from '../core/Icon.jsx';
export function LayerToggleButton({open=false,onToggle,className=''}){
  return <button type="button" className={'nuo-ltb'+(open?' is-open ':' ')+className} aria-expanded={open} aria-label="Livelli mappa" onClick={onToggle}><Icon name="layers" size={20} /></button>;
}
