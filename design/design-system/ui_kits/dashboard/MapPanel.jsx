(function(){
const {MapToggle,LayerToggleButton,LayerPanel,MapMarker,MapLegend,MapAttribution,Icon}=window.DesignSystem_1776e0;
const CLS=['','--color-map-congestion-1','--color-map-congestion-2','--color-map-congestion-3','--color-map-congestion-4'];
const CNAME=['','Scorrevole','Rallentata','Intensa','Satura'];
const ROADS=[
 {id:'Via Marina',d:'M40 560L300 520L560 540L960 500',c:[4,3,3,2],at:[300,520]},
 {id:'Corso Umberto I',d:'M120 120L330 260L520 330L760 420',c:[3,2,2,1],at:[425,295]},
 {id:'Via Toledo',d:'M520 40L520 330L500 540',c:[2,2,1,1],at:[520,330]},
 {id:'Via Caracciolo',d:'M60 400L360 380L700 250L940 180',c:[1,1,1,1],at:[360,380]},
 {id:'Circumvallazione',d:'M780 60L800 300L760 420L780 640',c:[3,2,2,2],at:[800,300]}];
const STOPS=[{id:'Fermata Garibaldi',x:300,y:520,l:[0,0]},{id:'Fermata Municipio',x:520,y:540,l:[1,1]},{id:'Fermata Duomo',x:780,y:300,l:[2,1]},{id:'Fermata Mergellina',x:360,y:380,l:[0,0]}];
const SR=[6,9,13],SC=['--color-map-stop-low','--color-map-stop-mid','--color-map-stop-over'];
const pc=(x,y)=>({left:(x/10)+'%',top:(y/7)+'%'});
function MapPanel({after,onAfter,iteration,onIteration,layers,onLayer,closures,onCloseRoad,onStop,requests,hasRun}){
  const [tip,setTip]=React.useState(null);
  const [lp,setLp]=React.useState(false);
  const on=(id)=>layers.find(l=>l.id===id).on;
  const sel=!after?0:iteration===1?1:2;
  const stateOf=(d)=>{const r=requests.filter(x=>x.dept===d).slice(-1)[0];return r?(r.status==='ACCEPTED'||r.status==='COMPLETED'?'accepted':r.status==='REJECTED'?'rejected':'normal'):'normal'};
  const mv=(e,text)=>{const b=e.currentTarget.closest('[data-map]').getBoundingClientRect();setTip({x:e.clientX-b.left+12,y:e.clientY-b.top+12,text})};
  const closed=(id)=>after&&closures.includes(id);
  return <div data-map="1" style={{position:'relative',height:'100%',minHeight:0,overflow:'hidden',borderRadius:10,background:'#0E0D0B',border:'1px solid var(--color-border-card)'}}>
    <svg viewBox="0 0 1000 700" preserveAspectRatio="none" style={{position:'absolute',inset:0,width:'100%',height:'100%'}}>
      {on('e')&&<polygon points="560,90 770,90 770,230 560,230" fill="var(--color-map-event-area)" fillOpacity=".12" stroke="var(--color-map-event-area)" strokeWidth="2" vectorEffect="non-scaling-stroke" onMouseMove={(e)=>mv(e,'Area evento')} onMouseLeave={()=>setTip(null)} />}
      {on('c')&&ROADS.map(r=>{const cls=r.c[sel];return <path key={r.id} d={r.d} fill="none" stroke={'var('+CLS[cls]+')'} strokeWidth="6" strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" style={{opacity:.4,cursor:'pointer',transition:'opacity 150ms ease-out'}} onMouseEnter={(e)=>{e.currentTarget.style.opacity=1}} onMouseMove={(e)=>mv(e,r.id+' · '+CNAME[cls])} onMouseLeave={(e)=>{e.currentTarget.style.opacity=.4;setTip(null)}} onClick={()=>onCloseRoad(r.id)} />})}
      {on('x')&&ROADS.filter(r=>closed(r.id)).map(r=><path key={r.id} d={r.d} fill="none" stroke="var(--color-map-closure)" strokeWidth="4" strokeDasharray="10 8" vectorEffect="non-scaling-stroke" pointerEvents="none" />)}
      {on('d')&&closed('Corso Umberto I')&&<g><path d="M330 262L300 330L430 420L580 380L520 332" fill="none" stroke="var(--color-map-detour)" strokeWidth="4" strokeDasharray="6 6" strokeLinecap="butt" strokeLinejoin="round" vectorEffect="non-scaling-stroke" /><circle cx="330" cy="262" r="5" fill="var(--color-map-detour)" /><path d="M510 320L535 334L508 344Z" fill="var(--color-map-detour)" /></g>}
      {on('f')&&STOPS.map(s=><circle key={s.id} cx={s.x} cy={s.y} r={SR[s.l[after?1:0]]} fill={'var('+SC[s.l[after?1:0]]+')'} stroke="var(--color-bg)" strokeWidth="2" vectorEffect="non-scaling-stroke" style={{cursor:'pointer'}} onMouseMove={(e)=>mv(e,s.id)} onMouseLeave={()=>setTip(null)} onClick={()=>onStop(s.id)} />)}
    </svg>
    {on('x')&&ROADS.filter(r=>closed(r.id)).map(r=><span key={r.id} style={{position:'absolute',...pc(r.at[0],r.at[1]),transform:'translate(-50%,-50%)',width:24,height:24,borderRadius:'50%',background:'var(--color-bg)',border:'2px solid var(--color-map-closure)',color:'var(--color-map-closure)',display:'grid',placeItems:'center',pointerEvents:'none'}}><Icon name="ban" size={16} stroke={2} /></span>)}
    {on('r')&&requests.length>0&&[['traffic',330,260],['police',520,330],['transport',780,300],['comms',520,170]].filter(m=>requests.some(r=>r.dept===m[0])||m[0]==='traffic'&&hasRun).map(m=><span key={m[0]} style={{position:'absolute',...pc(m[1],m[2]),transform:'translate(-22px,-52px)'}}><MapMarker dept={m[0]} state={stateOf(m[0])} /></span>)}
    <div style={{position:'absolute',top:16,left:16}}><MapToggle after={after} onAfterChange={onAfter} iteration={iteration} onIterationChange={onIteration} /></div>
    <div style={{position:'absolute',top:16,right:16,display:'flex',flexDirection:'column',alignItems:'flex-end',gap:8}}><LayerToggleButton open={lp} onToggle={()=>setLp(!lp)} />{lp&&<LayerPanel layers={layers} onToggle={onLayer} />}</div>
    <div style={{position:'absolute',bottom:16,left:16}}><MapLegend /></div>
    <div style={{position:'absolute',bottom:16,right:16}}><MapAttribution /></div>
    <div style={{position:'absolute',left:'50%',bottom:70,transform:'translateX(-50%)',font:'500 14px/20px var(--font-ui)',color:'var(--color-text-muted)',pointerEvents:'none'}}></div>
    {tip&&<div style={{position:'absolute',left:tip.x,top:tip.y,padding:'8px 10px',background:'var(--color-surface-2)',border:'1px solid var(--color-border-tooltip)',borderRadius:4,font:'500 14px/20px var(--font-ui)',pointerEvents:'none',whiteSpace:'nowrap'}}>{tip.text}</div>}
  </div>;
}
window.MapPanel=MapPanel;window.MAP_STOP_NAMES=STOPS.map(s=>s.id);
})();
