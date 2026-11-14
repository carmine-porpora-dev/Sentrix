(function(){
const {RunStatus,IterationIndicator,AgentTimelineItem,DepartmentCard,RequestCard,RequestGroup,DecisionCallout,EmptyState,Tabs,ManualSwitch,Button,Card,DecisionLogRow,MetricCard}=window.DesignSystem_1776e0;
const AG=[['Traffic Agent',1,2,'3,2 s'],['Transit Agent',1,2,'2,8 s'],['Planner',3,4,'6,0 s'],['Verifier',7,7,'1,6 s']];
function agentStatus(a,stage){if(stage<0||stage<a[1])return'waiting';if(stage<=a[2])return'running';return a[0]==='Planner'?'fallback':'done'}
const DEPT=[['traffic',8,12],['police',6,10],['transport',5,6],['comms',3,4]];
function Metrics({after,mode,loading}){
  const b=after?(mode==='scenario'?'simulated':'estimate'):'real';
  const v=after?['9.340','31','6.120','3','11,2']:['12.480','24','9.870','7','15,6'];
  const d=after?[{tone:'better',direction:'down',text:'−25,2%'},{tone:'better',direction:'up',text:'+29,2%'},{tone:'better',direction:'down',text:'−38,0%'},{tone:'better',direction:'down',text:'−4'},{tone:'better',direction:'down',text:'−28,2%'}]:Array(5).fill({tone:'neutral',text:'0,0%'});
  const B=['12.480','24','9.870','7','15,6'];
  const PR=[['Fonte','Modello di traffico'],['Metodo','Ore × veicoli in ritardo'],['Unità','h'],['Ora del dato','21:04']];
  const L=['Ore-veicolo perse','Velocità media','Persone in area','Fermate sovraccariche','Attesa media'],U=['h','km/h','','','min'];
  return <div style={{display:'grid',gridTemplateColumns:'repeat(5,minmax(0,1fr))',gap:16}}>{L.map((l,i)=><MetricCard key={l} label={l} value={v[i]} before={after?B[i]:undefined} unit={U[i]||undefined} delta={d[i]} badge={b} loading={loading} compact={i!==0} provenance={{rows:PR}} />)}</div>;
}
function RightPanel({stage,waiting,requests,manual,onManual,onResolve,after,iteration,log=[]}){
  const [tab,setTab]=React.useState('agents');
  React.useEffect(()=>{if(waiting)setTab('ops')},[waiting]);
  const state=waiting?'DECISIONE':stage<0?'DONE':['INTAKE','ANALYZE','RECONCILE','PLAN','DISPATCH','AWAIT','REPLAN','VERIFY','DONE'][stage];
  const idle=stage<0;
  const acc=requests.filter(r=>r.status==='ACCEPTED'||r.status==='COMPLETED').map(r=>r.dept);
  const rem=(d,n)=>Math.max(0,n-(acc.includes(d)?(d==='police'?2:1):0));
  const originals=requests.filter(r=>!r.alternativeTo);
  return <div style={{display:'flex',flexDirection:'column',gap:16,minHeight:0}}>
    <Tabs active={tab} onChange={setTab} items={[{id:'agents',label:'Agenti'},{id:'ops',label:'Operations'},{id:'log',label:'Decisioni'}]} />
    {tab==='agents'&&<Card><div style={{display:'flex',justifyContent:'space-between',alignItems:'flex-start',gap:12,flexWrap:'wrap'}}>
      <div><div className="t-lg" style={{marginBottom:10}}>Stato del run</div>{idle?<div className="t-xs" style={{color:'var(--color-text-secondary)'}}>Nessun run in corso. Imposta l'evento e premi Analizza.</div>:<RunStatus state={state} step={5} />}</div>
      <IterationIndicator current={after?iteration:Math.min(1,iteration)} total={3} /></div>
      {!idle&&<div style={{marginTop:16}}>{AG.map((a,i)=><AgentTimelineItem key={a[0]} name={a[0]} status={agentStatus(a,stage)} duration={agentStatus(a,stage)==='waiting'?undefined:(agentStatus(a,stage)==='running'?'…':a[3])} note={agentStatus(a,stage)==='fallback'?'Completato con testo di riserva: risposta non valida':undefined} last={i===AG.length-1} />)}</div>}
    </Card>}
    {tab==='ops'&&<>
      {waiting&&<DecisionCallout measure="Presidio incroci Corso Umberto I"><div style={{display:'flex',gap:8,marginTop:12}}><Button icon="check" onClick={()=>onResolve(true)}>Accetta misura</Button><Button variant="stroke" icon="x" onClick={()=>onResolve(false)}>Rifiuta misura</Button></div></DecisionCallout>}
      <Card><div className="t-lg" style={{marginBottom:12}}>Dipartimenti</div>
        <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:10}}>{DEPT.map(d=><DepartmentCard key={d[0]} dept={d[0]} remaining={rem(d[0],d[1])} total={d[2]} />)}</div></Card>
      <Card><div className="t-lg" style={{marginBottom:12}}>Richieste operative</div>
        <div style={{marginBottom:16}}><ManualSwitch checked={manual} onChange={onManual} /></div>
        {requests.length===0&&<EmptyState icon="send" title="Nessuna richiesta inviata" />}
        {originals.map(r=>{const alts=requests.filter(x=>x.alternativeTo===r.code);return <RequestGroup key={r.code} request={r} alternatives={alts} unread={alts.length>0} />})}
      </Card></>}
    {tab==='log'&&<Card><div className="t-lg" style={{marginBottom:12}}>Registro decisioni</div>
      {log.length===0?<EmptyState icon="scroll-text" title="Nessuna decisione registrata" />:<div className="nuo-log"><DecisionLogRow head variant="log" />{log.map((r,i)=><DecisionLogRow key={i} variant="log" {...r} />)}</div>}</Card>}
  </div>;
}
function LogScreen({log}){
  return <div style={{padding:16,overflow:'auto',minHeight:0}}><div className="t-2xl" style={{marginBottom:16}}>Registro decisioni</div>
    <div className="nuo-log" style={{maxWidth:960}}><DecisionLogRow head />{log.map((r,i)=><DecisionLogRow key={i} {...r} />)}</div></div>;
}
function RequestsScreen({requests}){
  return <div style={{padding:16,overflow:'auto',minHeight:0}}><div className="t-2xl" style={{marginBottom:16}}>Richieste e dipartimenti</div>
    <div style={{display:'grid',gridTemplateColumns:'repeat(4,minmax(0,1fr))',gap:16,marginBottom:24}}>{DEPT.map(d=><DepartmentCard key={d[0]} dept={d[0]} remaining={d[1]} total={d[2]} />)}</div>
    <div style={{maxWidth:640}}>{requests.length?requests.map(r=><RequestCard key={r.code} {...r} />):<div className="t-sm" style={{color:'var(--color-text-secondary)'}}>Nessuna richiesta: avvia un'analisi dalla Plancia.</div>}</div></div>;
}
Object.assign(window,{Metrics,RightPanel,LogScreen,RequestsScreen});
})();
