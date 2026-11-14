import React from 'react';
import { Icon } from '../core/Icon.jsx';
export function SimulationBanner({absolute=false}){
  return <span className={'nuo-simbanner'+(absolute?' nuo-simbanner--abs':'')}><Icon name="flask-conical" size={20} stroke={2} />SIMULAZIONE</span>;
}
