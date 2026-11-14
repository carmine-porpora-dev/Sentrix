import React from 'react';
export function IterationIndicator({current=1,total=3}){
  return <div className="nuo-iter"><span className="nuo-iter__label">Iterazione {current} di {total}</span>
    <span className="nuo-iter__ticks">{Array.from({length:total},(_,i)=><i key={i} className={'nuo-iter__tick'+(i<current?' is-on':'')} />)}</span></div>;
}
