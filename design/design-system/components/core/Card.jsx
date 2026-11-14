import React from 'react';
export function Card({variant='default',padding=16,clickable=false,onClick,className='',style,children}){
  const cls=['nuo-card',variant==='nested'?'nuo-card--nested':'',padding===20?'nuo-card--p20':'',clickable?'nuo-card--clickable':'',className].join(' ');
  return <div className={cls} style={style} onClick={onClick} role={clickable?'button':undefined} tabIndex={clickable?0:undefined}>{children}</div>;
}
