/* CiO Claim Builder — engine.
   Three parts: (1) the form and its state, (2) the drafting engine that writes the
   eight sections in the house style from the state, (3) a WordprocessingML writer
   that exports the document to .docx in the house format. Standard browser JS;
   JSZip is the only dependency (vendored). */
(function(){
'use strict';
const D=DATA, L=D.claims, STYLE=D.style||{};
const el=id=>document.getElementById(id);
const esc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const MONTHS=['January','February','March','April','May','June','July','August','September','October','November','December'];
const pad=n=>String(n).padStart(2,'0');
const parse=s=>{if(!s||!/^\d{4}-\d{2}-\d{2}$/.test(s))return null;const [y,m,d]=s.split('-').map(Number);return new Date(Date.UTC(y,m-1,d));};
const iso=d=>d.getUTCFullYear()+'-'+pad(d.getUTCMonth()+1)+'-'+pad(d.getUTCDate());
const addDays=(d,n)=>new Date(d.getTime()+n*864e5);
const long=s=>{const d=s instanceof Date?s:parse(s);return d?pad(d.getUTCDate())+' '+MONTHS[d.getUTCMonth()]+' '+d.getUTCFullYear():'[date TO CONFIRM]';};
const between=(a,b)=>Math.round((parse(b)-parse(a))/864e5);
const fmt=(n,dp=2)=>(Number(n)||0).toLocaleString('en-GB',{minimumFractionDigits:dp,maximumFractionDigits:dp});
const m=D.manifest||{};if(m.n_months)el('vint').textContent='panel v'+(m.panel_version||'')+' · claims library';

// ---------- theme
const root=document.documentElement, tb=el('theme');
function applyTheme(v){if(v==='light'||v==='dark')root.setAttribute('data-theme',v);else root.removeAttribute('data-theme');tb.querySelectorAll('button').forEach(b=>b.classList.toggle('on',b.dataset.v===v));}
let th='auto';try{th=localStorage.getItem('cio-theme')||'auto'}catch(e){}applyTheme(th);
tb.addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;applyTheme(b.dataset.v);try{localStorage.setItem('cio-theme',b.dataset.v)}catch(err){}});

// ---------- number words
const ONES=['','One','Two','Three','Four','Five','Six','Seven','Eight','Nine','Ten','Eleven','Twelve','Thirteen','Fourteen','Fifteen','Sixteen','Seventeen','Eighteen','Nineteen'];
const TENS=['','','Twenty','Thirty','Forty','Fifty','Sixty','Seventy','Eighty','Ninety'];
function words(n){n=Math.floor(Math.abs(n));if(n===0)return 'Zero';const parts=[];const scale=[[1e9,'Billion'],[1e6,'Million'],[1e3,'Thousand'],[1,'']];
  for(const [v,name] of scale){if(n>=v){const q=Math.floor(n/v);n%=v;parts.push(sub(q)+(name?' '+name:''));}}return parts.join(' ');
  function sub(x){let s='';if(x>=100){s+=ONES[Math.floor(x/100)]+' Hundred';x%=100;if(x)s+=' ';}if(x>=20){s+=TENS[Math.floor(x/10)];if(x%10)s+='-'+ONES[x%10];}else if(x>0)s+=ONES[x];return s;}}
const CUR={EUR:['Euro','Euros','Cent','Cents'],USD:['United States Dollar','United States Dollars','Cent','Cents'],GBP:['Pound Sterling','Pounds Sterling','Penny','Pence'],UGX:['Uganda Shilling','Uganda Shillings','Cent','Cents'],KES:['Kenya Shilling','Kenya Shillings','Cent','Cents'],TZS:['Tanzania Shilling','Tanzania Shillings','Cent','Cents'],RWF:['Rwandan Franc','Rwandan Francs','Centime','Centimes'],ZAR:['Rand','Rand','Cent','Cents']};
function money(cur,n,withWords){const v=Number(n)||0;const s=cur+' '+fmt(v);if(!withWords)return s;const c=CUR[cur]||[cur,cur,'Cent','Cents'];const whole=Math.floor(v),cents=Math.round((v-whole)*100);
  let w=words(whole)+' '+(whole===1?c[0]:c[1]);if(cents)w+=' and '+words(cents)+' '+(cents===1?c[2]:c[3]);return s+' ('+w+')';}
function daysWords(n){return n+' calendar days';}

// ---------- state
const MIT=[
  ['identify','Proactive identification of the problem','Surveys, inspections or submissions made before the programme date so the Employer or Engineer had what it needed in time.'],
  ['followup','Persistent follow-up and escalation','Reminders, meetings and escalation letters, each dated and referenced.'],
  ['resequence','Re-sequencing or partial commencement','Starting on the parts that could proceed, or re-ordering the Works to reduce the effect.'],
  ['records','Monthly programme updates and contemporary records','Updated programmes, site diaries, photographs, resource returns and Notes for Record.'],
  ['readiness','Mobilisation and readiness of resources','Teams, plant and materials mobilised in accordance with the Programme and held ready.'],
  ['engagement','Engagement with the Engineer\u2019s requests','Breakdowns, clarifications and revised submissions provided when asked.'],
  ['other','Other measures','Anything else that reduced the effect of the delay.'],
];
const CATS={A:'Disruption costs',B:'Prolongation costs: extension of contractual requirements',C:'Prolongation costs: direct costs'};
function fresh(){return {project:{title:'',number:'1',contractor:'',employer:'',engineer:'',form:'red2017',projectName:'',contractNo:'',signed:'',currency:'EUR',price:'',commence:'',tfc:'',cutoff:'',scope:'',location:'',programmeDate:'',programmeRef:'',programmeAcceptDate:'',programmeAcceptRef:'',access:''},
  event:{cause:'drawings',title:'',clauses:[],facts:'',procedure:'',sections:'',status:''},
  notice:{date:'',ref:'',aware:'',advance:''},chronology:[],register:[],
  mitigation:MIT.map(x=>({id:x[0],on:false,detail:''})),
  legal:{props:{},prevention:false,objections:[],authorities:[]},
  delay:{method:'tia',baseline:'',from:'',to:'',critical:'',eot:'',float:'',driver:'',concurrency:'none',windows:'',notes:''},
  quantum:{currency:'EUR',from:'',oh:'',profit:'',fx:'',cats:{A:[],B:[],C:[]}},
  overrides:{},step:0,savedAt:0};}
let S=fresh();
function load(){try{const s=JSON.parse(localStorage.getItem('cio-claim')||'null');if(s){const f=fresh();for(const k in f){if(s[k]==null)continue;if(typeof f[k]==='object'&&!Array.isArray(f[k]))S[k]=Object.assign(f[k],s[k]);else S[k]=s[k];}
  if(!Array.isArray(S.mitigation)||S.mitigation.length!==MIT.length)S.mitigation=f.mitigation;S.quantum.cats=Object.assign({A:[],B:[],C:[]},S.quantum.cats||{});}}catch(e){}}
load();
function save(){S.savedAt=Date.now();try{localStorage.setItem('cio-claim',JSON.stringify(S));el('savedNote').textContent='Saved on this device';}catch(e){el('savedNote').textContent='Could not save (storage full or blocked)';}}
function get(path){return path.split('.').reduce((o,k)=>o==null?undefined:o[k],S);}
function set(path,v){const ks=path.split('.');let o=S;for(let i=0;i<ks.length-1;i++){o=o[ks[i]]=o[ks[i]]||{};}o[ks[ks.length-1]]=v;}
const form=()=>L.forms.find(f=>f.id===S.project.form)||L.forms[0];
const cause=()=>L.causes.find(c=>c.id===S.event.cause)||L.causes[0];
const clauseByRef=r=>L.clauses.find(c=>c.ref===r);
// The library is keyed by Red Book 2017 references; each entry maps its equivalent in the other books.
function formRef(c){const f=form();if(!c)return null;if(f.id==='red2017')return c.ref;const short=f.short;const eq=(c.equiv||[]);
  let e=eq.find(x=>x.form.includes(short))||(short.startsWith('MDB')||f.family==='1999'?eq.find(x=>/MDB|1999/.test(x.form)):null)||eq.find(x=>x.form.includes(short.split(' ')[0]));
  if(!e)return c.ref;return e.ref&&e.ref!=='\u2014'&&e.ref!=='—'?e.ref:null;}
const libRef=r=>{const c=L.clauses.find(c=>formRef(c)===r);return c?c.ref:null;};
const showRef=r=>{const c=clauseByRef(r);const fr=formRef(c);return fr||('no equivalent of 2017 '+r);};

// ---------- steps
const STEPS=[['Contract','parties and particulars'],['Event','what happened'],['Chronology','the dated record'],['Mitigation','what was done'],['Legal basis','clauses and objections'],['Delay','method and days'],['Quantum','the money'],['Review','preview and export']];
function renderSteps(){el('steps').innerHTML=STEPS.map((s,i)=>`<button class="stepb${i===S.step?' on':''}${stepDone(i)?' done':''}" data-i="${i}"><span class="n">${stepDone(i)&&i!==S.step?'✓':i+1}</span><span>${s[0]}<small>${s[1]}</small></span></button>`).join('');
  document.querySelectorAll('.step').forEach(s=>s.classList.toggle('on',+s.dataset.s===S.step));}
function stepDone(i){const p=S.project;return [!!(p.contractor&&p.employer&&p.commence&&p.tfc),!!(S.event.facts&&S.event.clauses.length),S.chronology.length>0,S.mitigation.some(x=>x.on),Object.keys(S.legal.props).length>0,!!(S.delay.eot),Object.values(S.quantum.cats).some(a=>a.length),false][i];}
function go(i){S.step=Math.max(0,Math.min(7,i));save();renderSteps();if(S.step===7)renderReview();window.scrollTo({top:0,behavior:'smooth'});}
el('steps').addEventListener('click',e=>{const b=e.target.closest('button');if(b)go(+b.dataset.i);});
document.addEventListener('click',e=>{const b=e.target.closest('[data-go]');if(b)go(+b.dataset.go);});
if(location.hash==='#chronology')S.step=2;

// ---------- bind simple fields
function bindAll(){document.querySelectorAll('[data-k]').forEach(inp=>{const k=inp.dataset.k;const v=get(k);
  if(inp.type==='checkbox')inp.checked=!!v;else inp.value=v==null?'':v;
  inp.addEventListener(inp.tagName==='SELECT'||inp.type==='date'||inp.type==='checkbox'?'change':'input',()=>{set(k,inp.type==='checkbox'?inp.checked:inp.value);save();derived(k);});});}
el('formSel').innerHTML=L.forms.map(f=>`<option value="${f.id}">${esc(f.name)}</option>`).join('');
el('causeSel').innerHTML=L.causes.map(c=>`<option value="${c.id}">${esc(c.name)} · ${esc(c.clause)}</option>`).join('');
el('methodSel').innerHTML=L.methods.map(mm=>`<option value="${mm.id}">${esc(mm.name)}</option>`).join('');
bindAll();
function derived(k){
  const p=S.project;
  el('priceWords').textContent=p.price?money(p.currency,p.price,true):'';
  el('completionAuto').textContent=(p.commence&&p.tfc)?'Date for Completion: '+long(addDays(parse(p.commence),+p.tfc)):'';
  const eot=+S.delay.eot||0;el('revisedAuto').textContent=(p.commence&&p.tfc&&eot)?'Revised Date for Completion: '+long(addDays(parse(p.commence),+p.tfc+eot)):'';
  el('causeHint').textContent=cause().note||'';
  el('methodHint').textContent=(L.methods.find(x=>x.id===S.delay.method)||{}).summary||'';
  if(k==='event.cause'){S.event.clauses=defaultClauses();save();}
  if(k==='project.currency'&&!S.quantum.currency){S.quantum.currency=p.currency;}
  if(k==='project.form'||k==='event.cause'||k==='event.clauses')renderProps();
  renderChips();renderSteps();
}
function defaultClauses(){const c=cause();const refs=[];const primary=c.clause.split(/[\/,]/).map(s=>s.trim().replace(/\s*\(.*$/,'').replace(/ second paragraph/,'')).filter(Boolean);
  for(const r of primary){const k=r.match(/\d+\.\d+/);if(k&&clauseByRef(k[0]))refs.push(k[0]);}
  return refs;}
if(!S.event.clauses.length)S.event.clauses=defaultClauses();
function renderChips(){el('clauseChips').innerHTML=L.clauses.filter(c=>formRef(c)).map(c=>`<button class="pill${S.event.clauses.includes(c.ref)?' acc':''}" data-c="${c.ref}" style="cursor:pointer;padding:3px 10px;font-size:12px" title="${esc(c.title)}">${formRef(c)} ${esc(c.title)}</button>`).join('');}
el('clauseChips').addEventListener('click',e=>{const b=e.target.closest('[data-c]');if(!b)return;const r=b.dataset.c;const i=S.event.clauses.indexOf(r);if(i>=0)S.event.clauses.splice(i,1);else S.event.clauses.push(r);S.event.clauses.sort((a,b)=>parseFloat(a)-parseFloat(b));save();derived('event.clauses');});

// ---------- chronology
function renderChron(){const t=el('chronTable');
  if(!S.chronology.length){t.innerHTML='<tbody><tr><td class="muted">No events yet. Send the chronology from the evidence desk, or add rows here.</td></tr></tbody>';}
  else t.innerHTML='<thead><tr><th>Date</th><th>Event</th><th>From</th><th>Reference</th><th>Annex</th><th></th></tr></thead><tbody>'+S.chronology.map((r,i)=>`<tr><td style="width:150px"><input type="date" value="${r.date||''}" data-i="${i}" data-f="date" style="font-family:var(--mono)"></td><td style="min-width:280px"><input value="${esc(r.event)}" data-i="${i}" data-f="event"></td><td style="width:120px"><select data-i="${i}" data-f="party">${['Contractor','Engineer','Employer','Other'].map(p=>`<option${(r.party||'Other')===p?' selected':''}>${p}</option>`).join('')}</select></td><td style="width:180px"><input value="${esc(r.ref||'')}" data-i="${i}" data-f="ref"></td><td style="width:80px"><input value="${esc(r.annex||'')}" data-i="${i}" data-f="annex"></td><td class="act"><button class="x" data-del="${i}">×</button></td></tr>`).join('')+'</tbody>';
  const n=S.register?S.register.length:0;el('pullEvidence').hidden=!!S.chronology.length;el('pullText').textContent='Read the letters first: the evidence desk builds this table and numbers the annexes for you.';}
el('chronTable').addEventListener('change',e=>{const t=e.target;if(!t.dataset.f)return;S.chronology[+t.dataset.i][t.dataset.f]=t.value;save();});
el('chronTable').addEventListener('click',e=>{const b=e.target.closest('[data-del]');if(b){S.chronology.splice(+b.dataset.del,1);save();renderChron();}});
el('addChron').onclick=()=>{S.chronology.push({date:'',event:'',party:'Contractor',ref:'',annex:''});save();renderChron();};
el('sortChron').onclick=()=>{S.chronology.sort((a,b)=>(a.date||'9999').localeCompare(b.date||'9999'));save();renderChron();};

// ---------- mitigation
function renderMit(){el('mitList').innerHTML=MIT.map((x,i)=>{const s=S.mitigation[i];return `<div class="mrow"><input type="checkbox" data-mi="${i}"${s.on?' checked':''}><div><b>${x[1]}</b><p>${x[2]}</p><textarea data-md="${i}" placeholder="Detail, with the letters or records that show it, e.g. letters P2B/SOSA/ART-GCU/04-25/025 and /039 (Annexes A-1-1 and A-1-3)"${s.on?'':' hidden'}>${esc(s.detail)}</textarea></div></div>`;}).join('');}
el('mitList').addEventListener('change',e=>{const t=e.target;if(t.dataset.mi!=null){S.mitigation[+t.dataset.mi].on=t.checked;save();renderMit();renderSteps();}});
el('mitList').addEventListener('input',e=>{const t=e.target;if(t.dataset.md!=null){S.mitigation[+t.dataset.md].detail=t.value;save();}});

// ---------- legal
function propDefault(ref){const c=clauseByRef(ref);if(!c)return '';const r=formRef(c)||ref;
  return `Under *Sub-Clause ${r} [${c.title}]*, ${lc(c.duty||c.plain)} ${c.risk?cap(c.risk):''}`.trim();}
function renderProps(){const keep={};for(const r of S.event.clauses){keep[r]=S.legal.props[r]!=null?S.legal.props[r]:propDefault(r);}S.legal.props=keep;
  el('propList').innerHTML=S.event.clauses.map(r=>{const c=clauseByRef(r)||{title:''};return `<div class="f" style="margin-bottom:10px"><label>Sub-Clause ${showRef(r)} · ${esc(c.title)}</label><textarea data-p="${r}" style="min-height:70px">${esc(S.legal.props[r])}</textarea></div>`;}).join('')||'<span class="muted">Select clauses in the Event step.</span>';}
el('propList').addEventListener('input',e=>{const t=e.target;if(t.dataset.p){S.legal.props[t.dataset.p]=t.value;save();}});
function renderObj(){const t=el('objTable');const rows=S.legal.objections;
  t.innerHTML=(rows.length?'<thead><tr><th>Date</th><th>Reference</th><th>What the Engineer said (quote)</th><th>The answer</th><th></th></tr></thead>':'')+'<tbody>'+(rows.length?rows.map((r,i)=>`<tr><td style="width:150px"><input type="date" value="${r.date||''}" data-i="${i}" data-f="date"></td><td style="width:160px"><input value="${esc(r.ref||'')}" data-i="${i}" data-f="ref"></td><td><input value="${esc(r.quote||'')}" data-i="${i}" data-f="quote" placeholder="excessive time allowed for service diversions"></td><td><input value="${esc(r.answer||'')}" data-i="${i}" data-f="answer" placeholder="The Programme was accepted without qualification…"></td><td class="act"><button class="x" data-del="${i}">×</button></td></tr>`).join(''):'<tr><td class="muted">None recorded. Each objection is met in Section 5 with the First, Second, Third scaffold.</td></tr>')+'</tbody>';}
el('objTable').addEventListener('change',e=>{const t=e.target;if(t.dataset.f){S.legal.objections[+t.dataset.i][t.dataset.f]=t.value;save();}});
el('objTable').addEventListener('click',e=>{const b=e.target.closest('[data-del]');if(b){S.legal.objections.splice(+b.dataset.del,1);save();renderObj();}});
el('addObj').onclick=()=>{S.legal.objections.push({date:'',ref:'',quote:'',answer:''});save();renderObj();};
function renderAuth(){const t=el('authTable');const rows=S.legal.authorities;
  t.innerHTML=(rows.length?'<thead><tr><th>Case</th><th>Citation</th><th>Holding, in one sentence</th><th>Applies to clause</th><th></th></tr></thead>':'')+'<tbody>'+(rows.length?rows.map((r,i)=>`<tr><td><input value="${esc(r.name||'')}" data-i="${i}" data-f="name" placeholder="Peak Construction (Liverpool) Ltd v McKinney Foundations Ltd"></td><td style="width:160px"><input value="${esc(r.cite||'')}" data-i="${i}" data-f="cite" placeholder="(1970) 1 BLR 111"></td><td><input value="${esc(r.holding||'')}" data-i="${i}" data-f="holding"></td><td style="width:110px"><select data-i="${i}" data-f="clause"><option value="">general</option>${S.event.clauses.map(c=>`<option value="${c}"${r.clause===c?' selected':''}>${showRef(c)}</option>`).join('')}</select></td><td class="act"><button class="x" data-del="${i}">×</button></td></tr>`).join(''):'<tr><td class="muted">None. Add only authorities you have checked.</td></tr>')+'</tbody>';}
el('authTable').addEventListener('change',e=>{const t=e.target;if(t.dataset.f){S.legal.authorities[+t.dataset.i][t.dataset.f]=t.value;save();}});
el('authTable').addEventListener('click',e=>{const b=e.target.closest('[data-del]');if(b){S.legal.authorities.splice(+b.dataset.del,1);save();renderAuth();}});
el('addAuth').onclick=()=>{S.legal.authorities.push({name:'',cite:'',holding:'',clause:''});save();renderAuth();};

// ---------- delay hand-off from the Claims Desk
(function(){let d=null;try{d=JSON.parse(localStorage.getItem('cio-delay')||'null');}catch(e){}
  if(d&&d.eot!=null){el('pullDelay').hidden=false;el('pullDelayText').textContent=d.source==='programme'?`The programme builder on this device impacted the delay events on the programme: ${d.eot} days of extension supported by Employer events (${d.contractorDelay||0} days from Contractor events).`:`The delay check on this device found ${d.eot} days of extension (employer delay ${d.employerDelay} days less ${d.float} days of float; ${d.contractorDelay||0} days of concurrent contractor delay) under ${d.formName||''}.`;
    el('useDelay').onclick=()=>{S.delay.eot=d.eot;S.delay.critical=d.employerDelay;S.delay.float=d.float;S.delay.concurrency=d.contractorDelay>0?(d.separable?'some':'true'):'none';if(d.formId)S.project.form=d.formId;if(d.method)S.delay.method=d.method;if(d.baseline)S.delay.baseline=d.baseline;if(d.commence&&!S.project.commence)S.project.commence=d.commence;if(d.tfc&&!S.project.tfc)S.project.tfc=d.tfc;save();bindAll();derived('delay');};}})();

// ---------- quantum
function renderQuantum(){const cur=S.quantum.currency||S.project.currency;
  el('quantumCats').innerHTML=Object.keys(CATS).map(k=>{const rows=S.quantum.cats[k];const sum=rows.reduce((a,r)=>a+(+r.amount||0),0);
    return `<div class="panel" style="margin-top:14px"><div class="panel-head"><h3>Category ${k}: ${CATS[k]}</h3><span class="sub num">${cur} ${fmt(sum)}</span></div><div class="tbl-wrap"><table class="wrap"><thead><tr><th>Head of cost</th><th>Basis or period</th><th class="num">Amount (${cur})</th><th></th></tr></thead><tbody>${rows.map((r,i)=>`<tr><td><input value="${esc(r.desc||'')}" data-q="${k}" data-i="${i}" data-f="desc" placeholder="${k==='A'?'Idle pipelaying equipment, December 2025':k==='B'?'Extension of the Performance Security':'Site establishment and running costs'}"></td><td><input value="${esc(r.basis||'')}" data-q="${k}" data-i="${i}" data-f="basis" placeholder="${k==='A'?'daily rate × idle days (Appendix F)':'253 days × daily rate'}"></td><td style="width:160px"><input class="num" type="number" step="0.01" value="${r.amount||''}" data-q="${k}" data-i="${i}" data-f="amount"></td><td class="act"><button class="x" data-qdel="${k}:${i}">×</button></td></tr>`).join('')}</tbody></table></div><div class="row" style="margin-top:8px"><button class="btn" data-qadd="${k}">Add a head of cost</button></div></div>`;}).join('');
  const q=quantumTotals();el('qStats').innerHTML=[['Direct cost',q.direct],['Overheads',q.oh],['Profit',q.profit],['Total claimed',q.total]].map((x,i)=>`<div class="stat${i===3?' hi':''}"><span class="v">${fmt(x[1],0)}</span><span class="l">${x[0]}</span><span class="d">${cur}${i===3?' · '+money(cur,x[1],true).replace(/^[^(]*\(/,'(').replace(/\)$/,')'):''}</span></div>`).join('');}
function quantumTotals(){const q=S.quantum;const cat={};let direct=0;for(const k in CATS){cat[k]=q.cats[k].reduce((a,r)=>a+(+r.amount||0),0);direct+=cat[k];}
  const oh=direct*((+q.oh||0)/100),profit=direct*((+q.profit||0)/100);return {cat,direct,oh,profit,total:direct+oh+profit};}
el('quantumCats').addEventListener('input',e=>{const t=e.target;if(t.dataset.q){S.quantum.cats[t.dataset.q][+t.dataset.i][t.dataset.f]=t.value;save();if(t.dataset.f==='amount'){const q=quantumTotals();const cur=S.quantum.currency;el('qStats').querySelectorAll('.stat .v').forEach((v,i)=>v.textContent=fmt([q.direct,q.oh,q.profit,q.total][i],0));}}});
el('quantumCats').addEventListener('click',e=>{const a=e.target.closest('[data-qadd]'),d=e.target.closest('[data-qdel]');if(a){S.quantum.cats[a.dataset.qadd].push({desc:'',basis:'',amount:''});save();renderQuantum();}if(d){const [k,i]=d.dataset.qdel.split(':');S.quantum.cats[k].splice(+i,1);save();renderQuantum();}});
document.querySelectorAll('[data-k^="quantum."]').forEach(i=>i.addEventListener('change',renderQuantum));

// ---------- text helpers
const lc=s=>s?s.charAt(0).toLowerCase()+s.slice(1):'';
const cap=s=>s?s.charAt(0).toUpperCase()+s.slice(1):'';
const V=(v,flag)=>v&&String(v).trim()?String(v).trim():'['+(flag||'TO CONFIRM')+']';
const curly=s=>String(s).replace(/(^|[\s(\[])"/g,'$1\u201c').replace(/"/g,'\u201d').replace(/(^|[\s(\[])'/g,'$1\u2018').replace(/'/g,'\u2019').replace(/\s[\u2013\u2014]\s/g,', ').replace(/[\u2013\u2014]/g,', ');
function cite(row){if(!row)return '';const ax=row.annex?(row.party==='Contractor'?`*(refer to Annex ${row.annex})*`:`(Refer to Annex ${row.annex})`):'';return (row.ref?`letter ${row.ref}`:'')+(ax?' '+ax:'');}
function sub(ref,formal){const c=clauseByRef(ref);const r=c?(formRef(c)||ref):ref;return formal&&c?`*Sub-Clause ${r} [${c.title}]*`:`Sub-Clause ${r}`;}
// for references native to the selected form (its EOT, claim and determination clauses)
function subF(r,formal){const k=libRef(r);return k?sub(k,formal):`Sub-Clause ${r}`;}
function joinAnd(a){a=a.filter(Boolean);return a.length<=1?a.join(''):a.slice(0,-1).join(', ')+' and '+a[a.length-1];}
function paras(text){return String(text||'').split(/\n\s*\n|\n(?=\S)/).map(s=>s.replace(/\s+/g,' ').trim()).filter(Boolean);}

// ---------- the drafting engine
// Each section: {n, title, subs:[{n, title, blocks:[{t:'p'|'table'|'list'|'h3', ...}]}]}
function draft(){
  const p=S.project,f=form(),c=cause(),e=S.event,q=quantumTotals(),cur=S.quantum.currency||p.currency;
  const contractor=V(p.contractor,'Contractor'),employer=V(p.employer,'Employer'),engineer=V(p.engineer,'Engineer');
  const completion=(p.commence&&p.tfc)?long(addDays(parse(p.commence),+p.tfc)):'[Date for Completion TO CONFIRM]';
  const eot=+S.delay.eot||0;const revised=(p.commence&&p.tfc&&eot)?long(addDays(parse(p.commence),+p.tfc+eot)):'[revised date TO CONFIRM]';
  const cutoff=p.cutoff?long(p.cutoff):'[assessment date TO CONFIRM]';
  const chron=[...S.chronology].sort((a,b)=>(a.date||'9999').localeCompare(b.date||'9999'));
  const first=chron[0],notice=S.notice,evTitle=V(e.title,'event');
  const clauses=S.event.clauses;const clauseList=joinAnd(clauses.map(r=>sub(r)));
  const eotClause=f.eot,claimClause=f.claim,detClause=f.determination,admin=f.admin;
  const is2017=f.family==='2017';
  const cats=S.quantum.cats;const total=money(cur,q.total,true);const totalShort=money(cur,q.total);
  const mit=MIT.map((x,i)=>({...x,s:S.mitigation[i]})).filter(x=>x.s.on);
  const method=L.methods.find(x=>x.id===S.delay.method)||L.methods[0];
  const conc=S.delay.concurrency;
  const secs=[];
  const P=t=>({t:'p',text:curly(t)});
  const T=(head,rows,caption)=>({t:'table',head,rows,caption});
  const LI=items=>({t:'list',items:items.map(curly)});
  const H3=t=>({t:'h3',text:t});

  // 1 Executive summary
  secs.push({n:1,title:'Executive Summary',subs:[
    {n:'1.1',title:'Particulars',blocks:[T(['Item','Particular'],[['Claim',`Contractor\u2019s Claim No. ${V(p.number,'number')}: ${V(p.title,'title')}`],['Contractor',contractor],['Employer',employer],[admin,engineer],['Contract',`${V(p.contractNo,'contract number')} · ${V(p.projectName,'project')}`],['Form of Contract',f.name],['Extension of Time claimed',eot?daysWords(eot):'[TO CONFIRM]'],['Additional payment claimed',q.total?totalShort:'[TO CONFIRM]'],['Assessed up to',cutoff]])]},
    {n:'1.2',title:'Purpose',blocks:[P(`This document sets out the Contractor\u2019s claim for an extension of the Time for Completion and for additional payment arising from ${evTitle}, submitted pursuant to ${subF(claimClause,true)} of the Conditions of Contract. It follows the Notice of Claim given on ${notice.date?long(notice.date):'[date TO CONFIRM]'}${notice.ref?' through letter '+notice.ref:''} and provides the fully detailed claim that ${subF(claimClause)} requires.`)]},
    {n:'1.3',title:'Overview',blocks:[
      P(`${contractor} (the Contractor) submits this Claim No. ${V(p.number,'number')} against ${employer} (the Employer) under Contract ${V(p.contractNo,'contract number')} for the ${V(p.projectName,'project')}, governed by the FIDIC ${f.name.replace(/ \u2014.*$/,'')}. The project and contract particulars are set out in Section 2.`),
      P(`The Contractor claims an extension of the Time for Completion of **${eot?daysWords(eot):'[TO CONFIRM]'}**, revising the Date for Completion from ${completion} to ${revised}, and additional payment of **${q.total?total:'[TO CONFIRM]'}** (Cost plus reasonable profit). The events giving rise to this claim have a continuing effect; this submission assesses the impact up to ${cutoff}.`),
      P(`${paras(e.facts)[0]||'[The facts in summary TO CONFIRM]'} The factual chronology is set out in Section 3 with the Contractor\u2019s mitigation measures set out in Section 4 of this Claim.`),
      P(`The Contractor\u2019s entitlement, established in Section 5, rests on ${words(clauses.length+(S.legal.prevention?1:0)).toLowerCase()} propositions:`),
      LI([...clauses.map(r=>{const cc=clauseByRef(r);return `${sub(r,true)}: ${cc?lc(cc.plain.split('. ')[0]).replace(/\.$/,'')+'.':'[TO CONFIRM]'}`;}),...(S.legal.prevention?['The prevention principle: an Employer cannot hold the Contractor to a Date for Completion that the Employer\u2019s own acts or omissions have made impossible to achieve.']:[])]),
      P(`The delay analysis (Section 6) adopts the ${method.name} methodology${S.delay.windows?`, applied over ${S.delay.windows} impacted programmes`:''}. It demonstrates a cumulative critical delay of ${S.delay.critical?daysWords(+S.delay.critical):'[TO CONFIRM]'}${S.delay.driver?', driven by '+S.delay.driver:''}, and a resulting shift in the projected Date for Completion of ${eot?daysWords(eot):'[TO CONFIRM]'}.`),
      P(`The quantum analysis (Section 7) quantifies the additional cost at **${q.total?totalShort:'[TO CONFIRM]'}**, comprising ${joinAnd(Object.keys(CATS).filter(k=>cats[k].length).map(k=>lc(CATS[k]).replace(/prolongation costs: /,'prolongation of ')))}${q.oh||q.profit?', plus overheads and profit':''}. The Contractor requests that the ${admin} determine these amounts under ${subF(detClause)} and certify the same in the next Interim Payment Certificate.`)]},
    {n:'1.4',title:'Scope and Layout of Claim Document',blocks:[P(`This document comprises Volume 1 (Claim Narrative: Sections 1 to 8) and Volume 2 (Supporting Documents: programmes, correspondence, cost schedules and contemporary records). The Contractor reserves all rights set out in Section 8 of this Claim document and will submit ${is2017?'further particulars':'monthly interim updates'} until the effects of the described events are resolved.`)]}]});

  // 2 Project and contract particulars
  const s2=[];
  if(p.location)s2.push({n:'2.1',title:'Project Location and Coverage',blocks:paras(p.location).map(P)});
  s2.push({n:'2.2',title:'Form of Contract',blocks:[P(`The Contract is a written agreement under the FIDIC ${f.name.replace(/ \u2014 /,', ')}${p.signed?', effected on '+long(p.signed):''}, between ${employer} as the Employer and ${contractor} as the Contractor. The ${admin} under the Contract is ${engineer}.`)]});
  s2.push({n:'2.3',title:'Scope of Work',blocks:paras(p.scope).length?paras(p.scope).map(P):[P('[Scope of the Works TO CONFIRM]')]});
  s2.push({n:'2.4',title:'Contract Price',blocks:[P(`The Contract Price, as confirmed in the Contract Agreement, is **${p.price?money(p.currency,p.price,true):'[TO CONFIRM]'}**, subject to adjustment in accordance with the Contract.`)]});
  s2.push({n:'2.5',title:'Commencement Date and Completion',blocks:[P(`The Commencement Date of the Works was ${p.commence?long(p.commence):'[TO CONFIRM]'}. The Time for Completion is ${p.tfc?daysWords(+p.tfc):'[TO CONFIRM]'} from the Commencement Date, rendering the Date for Completion as ${completion}, subject to any entitlement to extension of time under the Contract.`)]});
  if(p.access)s2.push({n:'2.6',title:'Access to the Site',blocks:paras(p.access).map(P)});
  s2.push({n:(p.access?'2.7':'2.6'),title:'The Programme',blocks:[P(`The Contractor submitted its Programme under ${sub('8.3',true)}${p.programmeDate?' on '+long(p.programmeDate):''}${p.programmeRef?' (letter '+p.programmeRef+')':''}.${p.programmeAcceptDate?` The ${admin} ${is2017?'raised no notice of non-compliance and the Programme became the Programme for the purposes of the Contract':'accepted the Programme'} on ${long(p.programmeAcceptDate)}${p.programmeAcceptRef?' (letter '+p.programmeAcceptRef+')':''}.`:''} The ${p.programmeAcceptDate?'accepted ':''}Baseline Programme forms the reference against which the delay and disruption events described in this Claim are assessed, and establishes the logical sequence and dependencies on which the delay analysis in Section 6 rests.`)]});
  secs.push({n:2,title:'Project and Contract Particulars',subs:s2});

  // 3 Statement of facts
  const s3=[{n:'3.1',title:'Introduction',blocks:[P(`This section sets out the factual record of the events giving rise to this Claim: ${e.procedure?'the contractual procedure that governed the matter, ':''}the chronology of correspondence between the parties, and the position as at ${cutoff}. The facts described herein establish the basis upon which the Contractor\u2019s entitlement is assessed in Section 5, and the delay analysis is presented in Section 6.`)]}];
  if(e.procedure)s3.push({n:'3.2',title:'The Contractual Procedure',blocks:paras(e.procedure).map(P)});
  s3.push({n:e.procedure?'3.3':'3.2',title:'The Events Giving Rise to the Claim',blocks:paras(e.facts).length?paras(e.facts).map(P):[P('[The facts TO CONFIRM]')]});
  const chronBlocks=[P('The chronology that follows is drawn from the contemporaneous records maintained by the Contractor, including correspondence exchanged between the parties, arranged in the order in which the events occurred. All correspondence cited herein is compiled in Volume 2 of this document.')];
  for(const r of chron){chronBlocks.push(P(`On ${r.date?long(r.date):'[date TO CONFIRM]'}, ${lc(r.event||'[event TO CONFIRM]').replace(/\.$/,'')}${r.ref&&!(r.event||'').includes(r.ref)?', through '+cite(r):(r.annex?' '+cite({annex:r.annex,party:r.party}):'')}.`));}
  if(!chron.length)chronBlocks.push(P('[Chronology TO CONFIRM: send the events from the evidence desk or add rows in the Chronology step.]'));
  s3.push({n:e.procedure?'3.4':'3.3',title:'Chronology of Events',blocks:chronBlocks});
  s3.push({n:e.procedure?'3.5':'3.4',title:`Position as at ${cutoff}`,blocks:[P(`As at ${cutoff}, ${V(e.status,'position TO CONFIRM')}${e.sections?', affecting '+e.sections:''}. The consequence of these facts for the Time for Completion is assessed in Section 6 and for the Contract Price in Section 7.`)]});
  s3.push({n:e.procedure?'3.6':'3.5',title:'Conclusion',blocks:[P(`The record establishes that the cause of delay lies with ${c.id==='variation'||c.id==='drawings'||c.id==='access'||c.id==='employer'||c.id==='suspension'?'the Employer and the '+admin:'matters for which the Contractor is not responsible under the Contract'}. ${notice.advance?`The Contractor gave advance notice through letters ${notice.advance}, and its formal Notice of Claim ${notice.ref?'through letter '+notice.ref+' ':''}on ${notice.date?long(notice.date):'[date TO CONFIRM]'}.`:`The Contractor gave its Notice of Claim ${notice.ref?'through letter '+notice.ref+' ':''}on ${notice.date?long(notice.date):'[date TO CONFIRM]'}.`} The delay is real, critical, and continuing.`)]});
  secs.push({n:3,title:'Statement of Facts on Events Giving Rise to the Claim',subs:s3});

  // 4 Mitigation
  const s4=[{n:'4.1',title:'Introduction',blocks:[P(`${STYLE.formulae?STYLE.formulae.mitigation.replace('8.4(b)',eotClause+'(b)').replace(/Sub-Clause 8\.4/,'Sub-Clause '+eotClause):''} This section records the measures the Contractor took to reduce the effect of ${evTitle}.`)]}];
  mit.forEach((x,i)=>{s4.push({n:'4.'+(i+2),title:x[1],blocks:[P(x.s.detail?x.s.detail:`${x[2]} [Detail and references TO CONFIRM]`)]});});
  s4.push({n:'4.'+(mit.length+2),title:'Conclusion',blocks:[P(`The Contractor took every step that a prudent contractor in its position could reasonably take. ${mit.length?`The measures described above, ${joinAnd(mit.map(x=>lc(x[1])))}, reduced the effect of the delay without removing its cause, which lay outside the Contractor\u2019s control.`:'[Measures TO CONFIRM]'} The mitigation prerequisite of ${subF(eotClause)} is satisfied.`)]});
  secs.push({n:4,title:'Contractor\u2019s Mitigation Measures',subs:s4});

  // 5 Contractual and legal basis
  const s5=[{n:'5.1',title:'Introduction',blocks:[P(`The Contractor\u2019s entitlement rests on ${clauseList}${S.legal.prevention?', and on the prevention principle':''}. Each proposition is addressed in turn below, followed by the ${admin}\u2019s objections and the answers to them.`)]}];
  let k=2;
  for(const r of clauses){const cc=clauseByRef(r);const auth=S.legal.authorities.filter(a=>a.clause===r);const blocks=[P(S.legal.props[r]||propDefault(r))];
    if(cc&&cc.limits)blocks.push(P(`The clause is subject to ${lc(cc.limits)}`));
    blocks.push(P(`Applying the clause to the facts established in Section 3: ${paras(e.facts)[0]?lc(paras(e.facts)[0]):'[application TO CONFIRM]'}`));
    for(const a of auth)blocks.push(P(`This is consistent with the principle established in ***${a.name} ${a.cite}***, in which the court held that ${lc(a.holding||'[holding TO CONFIRM]')} The principle is directly applicable to the facts of this Claim.`));
    blocks.push(P(`The Contractor is entitled, pursuant to ${sub(r)} read with ${subF(claimClause)}, to ${cc&&cc.plain&&/cost|payment/i.test(cc.plain)?'an extension of the Time for Completion and to payment of any Cost incurred as a result':'the relief that the clause provides'}.`));
    s5.push({n:'5.'+(k++),title:`Sub-Clause ${cc?(formRef(cc)||r):r}: ${cc?cc.title:''}`,blocks});}
  if(S.legal.prevention)s5.push({n:'5.'+(k++),title:'The Prevention Principle',blocks:[P('The prevention principle provides that a party may not insist on the performance of an obligation that it has itself prevented; an Employer cannot hold the Contractor to a Date for Completion that the Employer\u2019s own acts or omissions have made impossible to achieve.'),...S.legal.authorities.filter(a=>!a.clause).map(a=>P(`This is consistent with the principle established in ***${a.name} ${a.cite}***, in which the court held that ${lc(a.holding||'[holding TO CONFIRM]')}`)),P('The Contractor emphasises, however, that the facts do not require recourse to the prevention principle. The express provisions of the Contract, applied in the preceding paragraphs, are sufficient.')]});
  if(S.legal.objections.length){const ob=[P(`The ${admin} has taken the following positions in correspondence. Each is addressed in turn.`)];
    for(const o of S.legal.objections){ob.push(P(`${o.date?'On '+long(o.date)+', ':''}the ${admin}${o.ref?', through letter '+o.ref+',':''} stated that ${o.quote?'*\u201c'+o.quote.replace(/^["\u201c]|["\u201d]$/g,'')+'\u201d*':'[quotation TO CONFIRM]'}. The Contractor does not accept this characterisation. ${o.answer||'[Answer TO CONFIRM]'} This contention is without contractual foundation.`));}
    s5.push({n:'5.'+(k++),title:`The ${admin}\u2019s Objections`,blocks:ob});}
  s5.push({n:'5.'+(k++),title:`Sub-Clause ${eotClause}: Extension of Time for Completion`,blocks:[P(`${subF(eotClause,true)} entitles the Contractor to an extension of the Time for Completion if and to the extent that completion is or will be delayed by ${c.name.toLowerCase()} (${c.clause}). The delay is quantified in Section 6.`)]});
  s5.push({n:'5.'+(k++),title:`Sub-Clause ${claimClause}: Compliance with Notice Requirements`,blocks:[P(`The Contractor became aware of the event on ${notice.aware?long(notice.aware):'[date TO CONFIRM]'} and gave Notice ${notice.ref?'through letter '+notice.ref+' ':''}on ${notice.date?long(notice.date):'[date TO CONFIRM]'}${notice.aware&&notice.date?`, ${between(notice.aware,notice.date)} days later and within the ${f.notice_days} days that ${subF(claimClause)} allows`:''}. ${is2017?`The ${admin} gave no Notice under Sub-Clause 20.2.2 within ${f.response_days} days that the Notice was out of time, and the Notice is accordingly valid.`:'The notice requirement is satisfied and the claim is not time-barred.'} This fully detailed claim follows within the ${f.detail_days} days provided.`)]});
  s5.push({n:'5.'+(k++),title:'Conclusion',blocks:[P(`The chain of causation is unbroken: ${paras(e.facts).slice(0,2).map(lc).join(' ')||'[TO CONFIRM]'} The causal chain is direct, unbroken, and attributable to a single dominant cause. The Contractor is entitled, pursuant to ${clauseList} read with ${subF(claimClause)}, to an extension of the Time for Completion and to payment of the Cost incurred as a result, as quantified in Sections 6 and 7.`)]});
  secs.push({n:5,title:'Contractual and Legal Basis for Entitlement to EOT and Additional Costs',subs:s5});

  // 6 Delay analysis
  const s6=[{n:'6.1',title:'Introduction',blocks:[P(`This section quantifies the effect of ${evTitle} on the Time for Completion. It identifies the method adopted, the Baseline Programme against which delay is measured, the delay events, the critical path and the resulting extension of time claimed.`)]},
    {n:'6.2',title:'Delay Analysis Methodology',blocks:[P(`The analysis adopts the ${method.name} method${method.summary?', '+lc(method.summary.replace(/\.$/,''))+'.':'.'} The method is one of the six recognised in the Society of Construction Law Delay and Disruption Protocol, 2nd edition (February 2017)${method.para?', at paragraph '+method.para:''}, and is suited to a claim ${S.delay.notes?'supported by '+lc(paras(S.delay.notes)[0]).replace(/\.$/,''):'of this kind'}.`)]},
    {n:'6.3',title:'The Baseline Programme',blocks:[P(`The Baseline Programme is ${V(S.delay.baseline,'baseline TO CONFIRM')}. It fixes the planned sequence, the durations and the logic links that govern the critical path.`)]},
    {n:'6.4',title:'The Delay Event',blocks:[P(`The delay event is ${evTitle}, running from ${S.delay.from?long(S.delay.from):'[date TO CONFIRM]'} to ${S.delay.to?long(S.delay.to):cutoff}${e.sections?' and affecting '+e.sections:''}. ${S.delay.driver?'The driving delay is '+S.delay.driver+'.':''}`)]}];
  if(S.delay.notes)s6.push({n:'6.5',title:'Windows of Delay and Impacted Programmes',blocks:paras(S.delay.notes).map(P)});
  let j=S.delay.notes?6:5;
  s6.push({n:'6.'+(j++),title:'Analysis of the Critical Path',blocks:[P(`The impacted programme shows a cumulative critical delay of **${S.delay.critical?daysWords(+S.delay.critical):'[TO CONFIRM]'}** to the Date for Completion. ${S.delay.float!==''&&S.delay.float!=null?`Float of ${S.delay.float} days on the affected path has been consumed by the event${+S.delay.float>0?', and the extension claimed is net of it':''}; any float that may have existed has been exhausted.`:''}`)]});
  s6.push({n:'6.'+(j++),title:'Concurrent Delay',blocks:[P(conc==='none'?'There is no concurrent delay. The Contractor\u2019s resources were mobilised and ready to proceed in accordance with the Programme, and no Contractor Risk Event was on the critical path during the period of delay. The whole of the delay is attributable to the Employer Risk Event.':conc==='some'?'Any delay for which the Contractor is responsible ran on a separate path and was not concurrent with the Employer Risk Event in the sense the Protocol uses (Core Principle 10). The Employer delay is the dominant and effective cause of the delay to completion, and the Contractor\u2019s entitlement is unaffected.':'To the extent that a Contractor Risk Event ran concurrently with the Employer Risk Event, the Contractor remains entitled to an extension of the Time for Completion for the whole of the Employer delay (Protocol Core Principle 10). The recovery of prolongation cost is confined to the period in which the Employer delay was the sole effective cause (Core Principle 14), and the quantum in Section 7 is presented on that basis.')]});
  s6.push({n:'6.'+(j++),title:'Extension of Time Claimed',blocks:[P(`The Contractor claims an extension of the Time for Completion of **${eot?daysWords(eot):'[TO CONFIRM]'}**, revising the Date for Completion from ${completion} to ${revised}. The events have a continuing effect, and the Contractor will update this assessment ${is2017?'in further particulars':'at monthly intervals'} until the effects cease.`)]});
  s6.push({n:'6.'+(j++),title:'Conclusion',blocks:[P(`Applying the \u2018but for\u2019 test: but for ${evTitle}, the Works would have proceeded in the sequence and to the dates of the Baseline Programme; the critical path would not have been extended; and the Date for Completion would have remained ${completion}. The delay impact on the projected Date for Completion is ${eot?daysWords(eot):'[TO CONFIRM]'}. Its cost is quantified in Section 7.`)]});
  secs.push({n:6,title:'Delay Analysis',subs:s6});

  // 7 Quantum
  const s7=[{n:'7.1',title:'Introduction',blocks:[P(`This section quantifies the additional payment to which the Contractor is entitled as a result of ${evTitle}, assessed ${S.quantum.from?'from '+long(S.quantum.from)+' ':''}up to ${cutoff}. Cost is claimed as defined in Sub-Clause 1.1, together with reasonable profit where the Contract provides for it.`)]},
    {n:'7.2',title:'Methodology and Assumptions',blocks:[P(`Costs are computed from the Contractor\u2019s contemporaneous records: idle resource returns, the cost ledger, invoices for securities and insurances, and the site establishment accounts. ${q.oh||q.profit?`Overheads of ${S.quantum.oh||0}% and profit of ${S.quantum.profit||0}% are applied to direct cost, consistent with the Contractor\u2019s established cost allocation.`:''} ${S.quantum.fx||''}`)]},
    {n:'7.3',title:'Grand Summary of Costs',blocks:[T(['Category','Head','Amount ('+cur+')'],[...Object.keys(CATS).map(k=>[k,CATS[k],fmt(q.cat[k])]),['','Sub-total, direct cost',fmt(q.direct)],['D','Overheads and profit',fmt(q.oh+q.profit)],['','**Total additional payment claimed**','**'+fmt(q.total)+'**']],'Table 7.1: Grand Summary of Additional Costs'),P(`The total additional payment claimed is **${q.total?total:'[TO CONFIRM]'}**.`)]}];
  let cn=4;
  for(const kk of Object.keys(CATS)){const rows=cats[kk];if(!rows.length)continue;
    s7.push({n:'7.'+(cn++),title:`Category ${kk}: ${CATS[kk]}`,blocks:[P(kk==='A'?'Disruption costs arise from the loss of productivity of resources mobilised in accordance with the Baseline Programme and rendered idle or under-utilised by the event. They are computed from the idle resource records maintained contemporaneously by the Contractor, each resource recorded by name, daily rate and idle days.':kk==='B'?'Prolongation of the Time for Completion extends the period for which the Contractor must maintain the securities, insurances and attendances that the Contract requires. Each is claimed for the extended period at the cost actually incurred.':'Direct prolongation costs are the time-related costs of maintaining the Site for the extended period: site establishment, supervision, labour and equipment retained on the Works.'),T(['Head of cost','Basis','Amount ('+cur+')'],[...rows.map(r=>[r.desc||'[TO CONFIRM]',r.basis||'',fmt(r.amount)]),['**Category '+kk+' total**','','**'+fmt(q.cat[kk])+'**']],`Table 7.${cn-1}: Category ${kk}`)]});}
  s7.push({n:'7.'+(cn++),title:'Category D: Overheads and Profit',blocks:[P(`Overheads of ${S.quantum.oh||0}% (${cur} ${fmt(q.oh)}) and profit of ${S.quantum.profit||0}% (${cur} ${fmt(q.profit)}) are applied to the direct cost of ${cur} ${fmt(q.direct)}. Head-office overheads are recoverable where the Contractor shows that they went unabsorbed during the period of delay; the supporting schedules are in Volume 2.`)]});
  s7.push({n:'7.'+(cn++),title:'Continuing Effect and Reservation of Rights',blocks:[P(`The events giving rise to this Claim have a continuing effect within the meaning of ${subF(claimClause)}. The amounts stated are assessed up to ${cutoff}. The Contractor reserves its right to claim the further Cost and profit that accrue after that date, and to revise the figures as the records are finalised.`)]});
  secs.push({n:7,title:'Quantum Analysis: Impact on Contract Price',subs:s7});

  // 8 Conclusion
  secs.push({n:8,title:'Conclusion',subs:[
    {n:'8.1',title:'Summary of the Contractor\u2019s Case',blocks:[P(`${evTitle.charAt(0).toUpperCase()+evTitle.slice(1)} delayed the Works by ${S.delay.critical?daysWords(+S.delay.critical):'[TO CONFIRM]'} on the critical path, as established in Section 3 and quantified in Section 6, and caused the Contractor to incur additional Cost of ${q.total?totalShort:'[TO CONFIRM]'}, as quantified in Section 7. The cause lies with matters for which the Employer bears the risk under ${clauseList}.`)]},
    {n:'8.2',title:'Entitlement Established',blocks:[P(`The Contractor is entitled, pursuant to ${clauseList} read with ${subF(claimClause)}, to an extension of the Time for Completion of ${eot?daysWords(eot):'[TO CONFIRM]'} and to payment of ${q.total?totalShort:'[TO CONFIRM]'}.`)]},
    {n:'8.3',title:'Continuing Effect',blocks:[P(`The events giving rise to this Claim have a continuing effect within the meaning of ${subF(claimClause)}. The Contractor will submit ${is2017?'further particulars':'monthly interim updates'} until the effects are resolved, and a final claim within ${f.detail_days} days after the end of the effects.`)]},
    {n:'8.4',title:'Reservation of Rights',blocks:[LI([`The Contractor reserves its right to claim a further extension of the Time for Completion for delay accruing after ${cutoff}.`,`The Contractor reserves its right to claim the further Cost and profit that accrue after ${cutoff}, including financing charges on sums withheld.`,'The Contractor reserves its right to refer any matter not agreed or determined to the '+f.board.replace(/\s*\(.*\)/,'')+' in accordance with the Contract.','Nothing in this Claim waives any right or entitlement of the Contractor under the Contract or at law.'])]},
    {n:'8.5',title:'Formal Request',blocks:[P(`In accordance with ${joinAnd([...clauses.map(r=>sub(r)),subF(claimClause),subF(detClause)])} of the Conditions of Contract, the Contractor respectfully requests that the ${admin}:`),LI([`Determine, pursuant to ${subF(detClause)}, that the Contractor is entitled to an extension of the Time for Completion of ${eot?daysWords(eot):'[TO CONFIRM]'}, revising the Date for Completion to ${revised}.`,`Determine, pursuant to ${subF(detClause)}, that the Contractor is entitled to additional payment of ${q.total?total:'[TO CONFIRM]'}.`,'Certify the amount so determined in the next Interim Payment Certificate.']),P(STYLE.formulae?STYLE.formulae.good_faith.replace(/the Engineer/g,'the '+admin).replace('Sub-Clause 3.5','Sub-Clause '+detClause):''),P(STYLE.formulae?STYLE.formulae.available.replace(/the Engineer/g,'the '+admin):'')]}]});

  // 9 Appendices
  const reg=S.register||[];const app=[['A','Contractor\u2019s Correspondence'],['B',admin+'\u2019s Correspondence'],['C','Employer\u2019s Correspondence'],['D','Programme Details and Other Records'],['E','Master Quantum Cost File'],['F','Disruption Cost Records'],['G','Tracking Schedules and Notes for Record'],['H','Supporting Documentation']];
  const s9=app.map((a,i)=>{const rows=reg.filter(r=>(r.annex||'').startsWith(a[0]+'-'));return {n:'9.'+(i+1),title:`Appendix ${a[0]}: ${a[1]}`,blocks:rows.length?[T(['Annex','Date','Reference','Subject'],rows.map(r=>[r.annex,r.date?long(r.date):'',r.ref||'',r.subject||r.file||'']))]:[P(i<3?'[Compiled from the evidence register.]':'[To be compiled.]')]};});
  secs.push({n:9,title:'Appendices: Volume 2, Supporting Documentation',subs:s9});

  // overrides (edited text) replace a subsection's paragraph blocks
  for(const s of secs)for(const ss of s.subs){const o=S.overrides[ss.n];if(o!=null){const tables=ss.blocks.filter(b=>b.t==='table');ss.blocks=[...paras(o).map(t=>t.startsWith('- ')?{t:'list',items:t.split(/\n?- /).filter(Boolean)}:{t:'p',text:t}),...tables];}}
  return secs;
}

// ---------- inline markup -> runs
function runs(text){const out=[];const re=/(\*\*\*[^*]+\*\*\*|\*\*[^*]+\*\*|\*[^*]+\*|\[[^\]]*(?:TO CONFIRM|CITE)[^\]]*\])/g;let last=0,mm;
  while((mm=re.exec(text))){if(mm.index>last)out.push({t:text.slice(last,mm.index)});const s=mm[0];
    if(s.startsWith('***'))out.push({t:s.slice(3,-3),b:1,i:1});else if(s.startsWith('**'))out.push({t:s.slice(2,-2),b:1});else if(s.startsWith('*'))out.push({t:s.slice(1,-1),i:1});else out.push({t:s,flag:1});last=mm.index+s.length;}
  if(last<text.length)out.push({t:text.slice(last)});return out;}
const runsHtml=text=>runs(text).map(r=>{let s=esc(r.t);if(r.flag)s=`<span class="flag">${s}</span>`;if(r.i)s=`<i>${s}</i>`;if(r.b)s=`<b>${s}</b>`;return s;}).join('');

// ---------- review
function renderReview(){const secs=draft();const p=S.project;
  let h=`<div class="cover"><p class="e">${esc(V(p.employer,'Employer'))}</p><p>${esc(V(p.projectName,'project'))}</p><p style="margin-top:14pt">Contract No. ${esc(V(p.contractNo,'contract number'))}</p><p class="t">CONTRACTOR\u2019S CLAIM NO. ${esc(V(p.number,'number'))}</p><p class="s">${esc(V(p.title,'title'))}</p><p class="s" style="margin-top:20pt">Volume 1: Claim Narrative</p><p class="s">Submitted by ${esc(V(p.contractor,'Contractor'))}</p><p class="s">${p.cutoff?long(p.cutoff):''}</p></div>`;
  h+='<div class="toc"><h1>Table of Contents</h1>'+secs.map(s=>`<p>${s.n} ${esc(s.title)}</p>`+s.subs.map(ss=>`<p class="l2">${ss.n} ${esc(ss.title)}</p>`).join('')).join('')+'</div>';
  for(const s of secs){h+=`<h1>${s.n} ${esc(s.title)}</h1>`;for(const ss of s.subs){h+=`<h2 id="ss-${ss.n}">${ss.n} ${esc(ss.title)}</h2>`;let n=0;
    for(const b of ss.blocks){if(b.t==='p')h+=`<p class="n"><span>${++n}.</span><span>${runsHtml(b.text)}</span></p>`;else if(b.t==='h3')h+=`<h3>${esc(b.text)}</h3>`;else if(b.t==='list')h+=`<ol class="abc">${b.items.map(i=>`<li>${runsHtml(i)}</li>`).join('')}</ol>`;else if(b.t==='table')h+=(b.caption?`<p style="font-weight:700;margin-bottom:2pt">${esc(b.caption)}</p>`:'')+`<table><thead><tr>${b.head.map(x=>`<th>${esc(x)}</th>`).join('')}</tr></thead><tbody>${b.rows.map(r=>`<tr>${r.map((x,i)=>`<td${i===r.length-1&&/^[\d,.*\-]+$/.test(String(x).replace(/\*/g,''))?' class="num"':''}>${runsHtml(String(x))}</td>`).join('')}</tr>`).join('')}</tbody></table>`;}}}
  el('paper').innerHTML=h;
  el('sectList').innerHTML=secs.flatMap(s=>s.subs.map(ss=>`<div class="sect"><span>${ss.n} ${esc(ss.title)}</span><button class="btn" data-edit="${ss.n}">${S.overrides[ss.n]!=null?'Edited':'Edit'}</button></div>`)).join('');
  sweep(secs);}
function sweep(secs){const B=STYLE.banned||{words:[],phrases:[],punctuation:[]};const found=[];
  for(const s of secs)for(const ss of s.subs)for(const b of ss.blocks){const texts=b.t==='p'?[b.text]:b.t==='list'?b.items:[];for(const t of texts){
    if(/[\u2013\u2014]/.test(t))found.push([ss.n,'dash',t]);
    if(/[^\s(]"|"[^\s)]/.test(t)||/\w'\w/.test(t))found.push([ss.n,'straight quotation mark or apostrophe',t]);
    for(const w of B.words){if(new RegExp('\\b'+w.replace(/[-\/\\^$*+?.()|[\]{}]/g,'\\$&')+'\\b','i').test(t)){found.push([ss.n,'\u201c'+w+'\u201d',t]);break;}}
    for(const w of B.phrases){if(t.toLowerCase().includes(w.toLowerCase())){found.push([ss.n,'\u201c'+w+'\u201d',t]);break;}}
    if(/TO CONFIRM|\[CITE\]/.test(t))found.push([ss.n,'gap to fill',t]);}}
  el('sweep').innerHTML=found.length?found.slice(0,40).map(f=>`<li><b>${esc(f[0])}</b> · ${esc(f[1])}: <span class="muted">${esc(f[2].slice(0,110))}${f[2].length>110?'…':''}</span></li>`).join('')+(found.length>40?`<li class="muted">and ${found.length-40} more</li>`:''):'<li style="color:var(--good)">Nothing found. No dashes, no banned vocabulary, no gaps left to fill.</li>';}
let editing=null;
el('sectList').addEventListener('click',e=>{const b=e.target.closest('[data-edit]');if(!b)return;editing=b.dataset.edit;const secs=draft();const ss=secs.flatMap(s=>s.subs).find(x=>x.n===editing);
  el('editTitle').textContent=editing+' '+ss.title;el('editText').value=S.overrides[editing]!=null?S.overrides[editing]:ss.blocks.filter(x=>x.t==='p'||x.t==='list').map(x=>x.t==='p'?x.text:x.items.map(i=>'- '+i).join('\n')).join('\n\n');
  el('editor').hidden=false;el('editClaude').hidden=!window.__cioClaude;el('editor').scrollIntoView({behavior:'smooth'});});
el('editDone').onclick=()=>{if(editing!=null){S.overrides[editing]=el('editText').value;save();}el('editor').hidden=true;editing=null;renderReview();};
el('editReset').onclick=()=>{if(editing!=null){delete S.overrides[editing];save();}el('editor').hidden=true;editing=null;renderReview();};
el('editClaude').onclick=async()=>{if(!window.__cioClaude||editing==null)return;const btn=el('editClaude');btn.innerHTML='<span class="busy"></span>Drafting…';btn.disabled=true;
  try{const secs=draft();const ss=secs.flatMap(s=>s.subs).find(x=>x.n===editing);const text=await window.__cioClaude({section:editing+' '+ss.title,current:el('editText').value,state:S,style:STYLE,form:form(),cause:cause()});if(text)el('editText').value=text;}
  catch(e){alert('Could not draft: '+(e&&e.message||e));}btn.textContent='Redraft with Claude';btn.disabled=false;};

// ---------- Word (.docx) writer
const X=s=>String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
function rPr(r){return '<w:rPr>'+(r.b?'<w:b/>':'')+(r.i?'<w:i/>':'')+(r.flag?'<w:highlight w:val="yellow"/>':'')+'</w:rPr>';}
function wruns(text){return runs(text).map(r=>`<w:r>${rPr(r)}<w:t xml:space="preserve">${X(r.t)}</w:t></w:r>`).join('');}
function para(text,opt){opt=opt||{};let ppr='<w:pPr>'+(opt.style?`<w:pStyle w:val="${opt.style}"/>`:'')+(opt.numId?`<w:numPr><w:ilvl w:val="${opt.ilvl||0}"/><w:numId w:val="${opt.numId}"/></w:numPr>`:'')+(opt.jc?`<w:jc w:val="${opt.jc}"/>`:'')+(opt.pageBreak?'<w:pageBreakBefore/>':'')+(opt.spacing||'')+'</w:pPr>';
  const rs=opt.raw?opt.raw:wruns(text);return `<w:p>${ppr}${rs}</w:p>`;}
function table(head,rows){const W=9026;const n=head.length;let widths;
  if(n===2)widths=[Math.floor(W*0.3),W-Math.floor(W*0.3)];
  else if(/amount/i.test(head[n-1])){const last=Math.floor(W*0.22);widths=head.map((_,i)=>i===n-1?last:Math.floor((W-last)/(n-1)));}
  else widths=head.map(()=>Math.floor(W/n));
  const cell=(t,i,isHead)=>`<w:tc><w:tcPr><w:tcW w:w="${widths[i]}" w:type="dxa"/>${isHead?'<w:shd w:val="clear" w:color="auto" w:fill="E7E6E6"/>':''}</w:tcPr><w:p><w:pPr><w:spacing w:before="40" w:after="40" w:line="240" w:lineRule="auto"/>${i===n-1&&n>1&&!isHead&&/^[\d,.*\-]+$/.test(String(t).replace(/\*/g,''))?'<w:jc w:val="right"/>':''}</w:pPr>${(isHead?[{t:String(t),b:1}]:runs(String(t))).map(r=>`<w:r><w:rPr>${r.b?'<w:b/>':''}${r.i?'<w:i/>':''}<w:sz w:val="19"/></w:rPr><w:t xml:space="preserve">${X(r.t)}</w:t></w:r>`).join('')}</w:p></w:tc>`;
  return `<w:tbl><w:tblPr><w:tblW w:w="${W}" w:type="dxa"/><w:tblBorders><w:top w:val="single" w:sz="4" w:color="808080"/><w:left w:val="single" w:sz="4" w:color="808080"/><w:bottom w:val="single" w:sz="4" w:color="808080"/><w:right w:val="single" w:sz="4" w:color="808080"/><w:insideH w:val="single" w:sz="4" w:color="808080"/><w:insideV w:val="single" w:sz="4" w:color="808080"/></w:tblBorders><w:tblLook w:val="04A0" w:firstRow="1"/></w:tblPr><w:tblGrid>${widths.map(w=>`<w:gridCol w:w="${w}"/>`).join('')}</w:tblGrid><w:tr><w:trPr><w:tblHeader/></w:trPr>${head.map((h,i)=>cell(h,i,true)).join('')}</w:tr>${rows.map(r=>`<w:tr>${r.map((c,i)=>cell(c,i,false)).join('')}</w:tr>`).join('')}</w:tbl><w:p><w:pPr><w:spacing w:before="0" w:after="60"/></w:pPr></w:p>`;}
function buildDocx(secs){const p=S.project;const body=[];const nums=[];let numId=10;
  const newNum=(abs)=>{const id=numId++;nums.push(`<w:num w:numId="${id}"><w:abstractNumId w:val="${abs}"/><w:lvlOverride w:ilvl="0"><w:startOverride w:val="1"/></w:lvlOverride></w:num>`);return id;};
  // cover
  body.push(para('',{spacing:'<w:spacing w:before="2400"/>'}));
  body.push(para('**'+V(p.employer,'Employer').toUpperCase()+'**',{jc:'center'}));
  body.push(para(V(p.projectName,'project'),{jc:'center'}));
  body.push(para('Contract No. '+V(p.contractNo,'contract number'),{jc:'center',spacing:'<w:spacing w:before="400"/>'}));
  body.push(para('**CONTRACTOR\u2019S CLAIM NO. '+V(p.number,'number')+'**',{jc:'center',spacing:'<w:spacing w:before="600"/>',raw:`<w:r><w:rPr><w:b/><w:sz w:val="36"/></w:rPr><w:t>CONTRACTOR\u2019S CLAIM NO. ${X(V(p.number,'number'))}</w:t></w:r>`}));
  body.push(para('',{jc:'center',raw:`<w:r><w:rPr><w:sz w:val="28"/></w:rPr><w:t>${X(V(p.title,'title'))}</w:t></w:r>`}));
  body.push(para('Volume 1: Claim Narrative',{jc:'center',spacing:'<w:spacing w:before="800"/>'}));
  body.push(para('Submitted by '+V(p.contractor,'Contractor')+' pursuant to Sub-Clause '+form().claim+' of the Conditions of Contract',{jc:'center'}));
  body.push(para(p.cutoff?long(p.cutoff):'',{jc:'center'}));
  // toc
  body.push(para('Table of Contents',{style:'TOCHeading',pageBreak:true}));
  body.push(`<w:p><w:pPr><w:spacing w:before="0" w:after="0"/></w:pPr><w:r><w:fldChar w:fldCharType="begin" w:dirty="true"/></w:r><w:r><w:instrText xml:space="preserve"> TOC \\o "1-2" \\h \\z \\u </w:instrText></w:r><w:r><w:fldChar w:fldCharType="separate"/></w:r></w:p>`);
  for(const s of secs){body.push(`<w:p><w:pPr><w:pStyle w:val="TOC1"/></w:pPr><w:r><w:t xml:space="preserve">${s.n}\t${X(s.title)}</w:t></w:r></w:p>`.replace('\t','</w:t></w:r><w:r><w:tab/></w:r><w:r><w:t xml:space="preserve">'));
    for(const ss of s.subs)body.push(`<w:p><w:pPr><w:pStyle w:val="TOC2"/></w:pPr><w:r><w:t xml:space="preserve">${ss.n}</w:t></w:r><w:r><w:tab/></w:r><w:r><w:t xml:space="preserve">${X(ss.title)}</w:t></w:r></w:p>`);}
  body.push(`<w:p><w:pPr><w:spacing w:before="0" w:after="0"/></w:pPr><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>`);
  // sections
  for(const s of secs){body.push(para(s.title,{style:'Heading1',pageBreak:true}));
    for(const ss of s.subs){body.push(para(ss.title,{style:'Heading2'}));const bodyNum=newNum(2);
      for(const b of ss.blocks){if(b.t==='p')body.push(para(b.text,{numId:bodyNum}));else if(b.t==='h3')body.push(para(b.text,{style:'Heading3'}));
        else if(b.t==='list'){const ln=newNum(3);for(const it of b.items)body.push(para(it,{numId:ln,ilvl:0}));}
        else if(b.t==='table'){if(b.caption)body.push(para('**'+b.caption+'**',{spacing:'<w:spacing w:before="120" w:after="40"/>'}));body.push(table(b.head,b.rows));}}}}
  const sect=`<w:sectPr><w:headerReference w:type="default" r:id="rIdH"/><w:footerReference w:type="default" r:id="rIdF"/><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="708" w:footer="708" w:gutter="0"/></w:sectPr>`;
  const NS='xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"';
  const document=`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document ${NS}><w:body>${body.join('')}${sect}</w:body></w:document>`;
  const font='<w:rFonts w:ascii="Helvetica Neue" w:hAnsi="Helvetica Neue" w:cs="Helvetica Neue" w:eastAsia="Helvetica Neue"/>';
  const styles=`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:styles ${NS}><w:docDefaults><w:rPrDefault><w:rPr>${font}<w:sz w:val="22"/><w:szCs w:val="22"/><w:lang w:val="en-GB"/></w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:before="100" w:after="160" w:line="360" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:keepLines/><w:numPr><w:numId w:val="1"/></w:numPr><w:spacing w:before="360" w:after="160"/><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:b/><w:caps/><w:sz w:val="28"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:keepLines/><w:numPr><w:ilvl w:val="1"/><w:numId w:val="1"/></w:numPr><w:spacing w:before="280" w:after="120"/><w:outlineLvl w:val="1"/></w:pPr><w:rPr><w:b/><w:sz w:val="24"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:numPr><w:ilvl w:val="2"/><w:numId w:val="1"/></w:numPr><w:spacing w:before="200" w:after="80"/><w:outlineLvl w:val="2"/></w:pPr><w:rPr><w:b/><w:i/><w:sz w:val="22"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="TOCHeading"><w:name w:val="TOC Heading"/><w:basedOn w:val="Normal"/><w:pPr><w:keepNext/><w:spacing w:before="360" w:after="160"/></w:pPr><w:rPr><w:b/><w:caps/><w:sz w:val="28"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="TOC1"><w:name w:val="toc 1"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:before="60" w:after="0" w:line="276" w:lineRule="auto"/><w:ind w:left="567" w:hanging="567"/><w:tabs><w:tab w:val="left" w:pos="567"/><w:tab w:val="right" w:leader="dot" w:pos="9016"/></w:tabs></w:pPr><w:rPr><w:b/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="TOC2"><w:name w:val="toc 2"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:before="0" w:after="0" w:line="276" w:lineRule="auto"/><w:ind w:left="1134" w:hanging="567"/><w:tabs><w:tab w:val="left" w:pos="1134"/><w:tab w:val="right" w:leader="dot" w:pos="9016"/></w:tabs></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="Header"><w:name w:val="header"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:before="0" w:after="0" w:line="240" w:lineRule="auto"/></w:pPr><w:rPr><w:sz w:val="18"/><w:color w:val="666666"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Footer"><w:name w:val="footer"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:before="0" w:after="0" w:line="240" w:lineRule="auto"/><w:jc w:val="center"/></w:pPr><w:rPr><w:sz w:val="18"/></w:rPr></w:style>
<w:style w:type="table" w:default="1" w:styleId="TableNormal"><w:name w:val="Normal Table"/><w:tblPr><w:tblCellMar><w:left w:w="80" w:type="dxa"/><w:right w:w="80" w:type="dxa"/></w:tblCellMar></w:tblPr></w:style></w:styles>`;
  const lvl=(i,fmt,txt,ind,pStyle)=>`<w:lvl w:ilvl="${i}"><w:start w:val="1"/><w:numFmt w:val="${fmt}"/>${pStyle?`<w:pStyle w:val="${pStyle}"/>`:''}<w:lvlText w:val="${txt}"/><w:lvlJc w:val="left"/><w:pPr><w:ind w:left="${ind[0]}" w:hanging="${ind[1]}"/></w:pPr></w:lvl>`;
  const numbering=`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:numbering ${NS}>
<w:abstractNum w:abstractNumId="1"><w:multiLevelType w:val="multilevel"/>${lvl(0,'decimal','%1',[567,567],'Heading1')}${lvl(1,'decimal','%1.%2',[850,850],'Heading2')}${lvl(2,'decimal','%1.%2.%3',[1134,1134],'Heading3')}</w:abstractNum>
<w:abstractNum w:abstractNumId="2"><w:multiLevelType w:val="singleLevel"/>${lvl(0,'decimal','%1.',[567,567])}</w:abstractNum>
<w:abstractNum w:abstractNumId="3"><w:multiLevelType w:val="singleLevel"/>${lvl(0,'lowerLetter','(%1)',[1134,567])}</w:abstractNum>
<w:num w:numId="1"><w:abstractNumId w:val="1"/></w:num>${nums.join('')}</w:numbering>`;
  const header=`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:hdr ${NS}><w:p><w:pPr><w:pStyle w:val="Header"/></w:pPr><w:r><w:t xml:space="preserve">Contractor\u2019s Claim No. ${X(V(p.number,'number'))} · ${X(V(p.title,'title'))}</w:t></w:r></w:p></w:hdr>`;
  const footer=`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:ftr ${NS}><w:p><w:pPr><w:pStyle w:val="Footer"/></w:pPr><w:r><w:t xml:space="preserve">Page </w:t></w:r><w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r><w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>1</w:t></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r><w:r><w:t xml:space="preserve"> of </w:t></w:r><w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText xml:space="preserve"> NUMPAGES </w:instrText></w:r><w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>1</w:t></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p></w:ftr>`;
  const settings=`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:settings ${NS}><w:updateFields w:val="true"/><w:defaultTabStop w:val="720"/></w:settings>`;
  const ct=`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/><Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/><Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/><Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/><Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/><Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/><Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/></Types>`;
  const rels=`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/><Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/></Relationships>`;
  const drels=`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rIdS" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/><Relationship Id="rIdN" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/><Relationship Id="rIdT" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings" Target="settings.xml"/><Relationship Id="rIdH" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/><Relationship Id="rIdF" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/></Relationships>`;
  const now=new Date().toISOString();
  const core=`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:title>Contractor\u2019s Claim No. ${X(V(p.number,'number'))}</dc:title><dc:creator>${X(V(p.contractor,'Contractor'))}</dc:creator><dcterms:created xsi:type="dcterms:W3CDTF">${now}</dcterms:created><dcterms:modified xsi:type="dcterms:W3CDTF">${now}</dcterms:modified></cp:coreProperties>`;
  const app=`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"><Application>CiO Lab Claim Builder</Application></Properties>`;
  const zip=new JSZip();zip.file('[Content_Types].xml',ct);zip.file('_rels/.rels',rels);zip.file('word/document.xml',document);zip.file('word/styles.xml',styles);zip.file('word/numbering.xml',numbering);zip.file('word/settings.xml',settings);zip.file('word/header1.xml',header);zip.file('word/footer1.xml',footer);zip.file('word/_rels/document.xml.rels',drels);zip.file('docProps/core.xml',core);zip.file('docProps/app.xml',app);
  return zip.generateAsync({type:'blob',mimeType:'application/vnd.openxmlformats-officedocument.wordprocessingml.document'});}
async function saveBlob(name,blob){if(window.__cioSave){await window.__cioSave(name,blob);return;}const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=name;document.body.appendChild(a);a.click();setTimeout(()=>{URL.revokeObjectURL(a.href);a.remove();},2000);}
el('exportDocx').onclick=async()=>{const b=el('exportDocx');b.innerHTML='<span class="busy"></span>Building…';try{const blob=await buildDocx(draft());const name=`Claim_No_${(S.project.number||'1')}_${(S.project.title||'claim').replace(/[^A-Za-z0-9]+/g,'_').slice(0,60)}.docx`;await saveBlob(name,blob);}catch(e){alert('Could not build the document: '+(e&&e.message||e));}b.textContent='Download Word (.docx)';};
el('exportJson').onclick=()=>saveBlob('claim_inputs.json',new Blob([JSON.stringify(S,null,1)],{type:'application/json'}));
el('importJson').addEventListener('change',async e=>{const f=e.target.files[0];if(!f)return;try{const s=JSON.parse(await f.text());localStorage.setItem('cio-claim',JSON.stringify(s));location.reload();}catch(err){alert('That file could not be read.');}});

// ---------- sample and reset
el('reset').onclick=()=>{if(!confirm('Clear everything entered for this claim on this device?'))return;S=fresh();save();location.hash='';location.reload();};
el('loadSample').onclick=()=>{S=fresh();Object.assign(S.project,{title:'Delayed Instructions Impeding Right of Access and Possession of Site',number:'1',contractor:'Sogea Satom',employer:'National Water and Sewerage Corporation',engineer:'ARTELIA in Association with Gauff Consultants Uganda Ltd',form:'mdb2010',projectName:'Greater Kampala Metropolitan Area Water Supply Network, Phase 1: Construction of Primary Network (Package 2B)',contractNo:'NWSC/HQ/WRKS/2020-2021/172191',signed:'2024-09-13',currency:'EUR',price:'92405463.49',commence:'2025-02-01',tfc:'913',cutoff:'2026-02-28',scope:'The Contract comprises a Fixed Tranche (Sections 1 to 4a) and a Conditional Tranche (Sections 4b to 7). The scope of the Works encompasses the design, supply, delivery, construction, testing and commissioning of approximately 69 kilometres of water transmission and distribution pipeline distributed across seven sections, together with associated booster stations, reservoirs and ancillary civil works.',location:'The project comprises a water transmission and distribution system covering Kampala City and its metropolitan area in Wakiso District. The pipeline routes traverse Kawempe, Nakawa, Wakiso, Kasangati, Kira and Nansana, with a total of 30 branches from the Katosi Water Treatment Plant, to improve water coverage and meet projected demand to the year 2040.',programmeDate:'2025-04-10',programmeRef:'P2B/SOSA/ART-GCU/04-25/029',programmeAcceptDate:'2025-04-29',programmeAcceptRef:'W20/CTR/031',access:'The Employer provided right of access to each section of the Works within or in advance of the contractual timescales set out in the Contract Data, with the exception of Sections 6 and 7, for which access was provided on 22 April 2025, approximately 50 days after the required date of 03 March 2025. Section 10.4(g) of the Employer\u2019s Requirements provides that *\u201cPermanent Works cannot start until the relevant relocations of existing facilities have been completed.\u201d* That prerequisite remained unfulfilled across all sections throughout the period under assessment; the access granted was formal access, not effective possession.'});
  Object.assign(S.event,{cause:'drawings',title:'the delayed instructions for the relocation of existing services',clauses:['1.9','2.1'].filter(r=>clauseByRef(r)),facts:'The Contract requires the relocation of existing utility services before pipelaying can commence (Employer\u2019s Requirements, Section 10.4(g)). The relocation procedure depends upon instructions from the Engineer under Sub-Clause 13.5. The Contractor requested those instructions from 01 April 2025, 48 days before the Baseline Programme date for commencement of relocation works (19 May 2025). No instructions were issued until late September 2025.\n\nThose instructions were cancelled by the Employer on 13 October 2025, when the Contractor was instructed to halt the signing of the subcontracts that the Engineer had just directed it to conclude. Replacement instructions covering only Sections 3, 4B and 7 were issued between January and February 2026.',procedure:'Section 10.4 [Protection and Relocation of Existing Services] of the Employer\u2019s Requirements prescribes the procedure: the Contractor identifies the services encumbering each route and submits them to the Engineer; the Engineer nominates the utility subcontractors and approves their rates; and the Engineer issues the instruction to relocate under Sub-Clause 13.5. Two features of this procedure are material to the claim: the Contractor cannot begin relocation without the instruction, and the remaining steps, nomination, rate approval and issuance of the instruction, lie with the Engineer and the Employer.',sections:'Sections 3, 4, 5, 6 and 7',status:'five of seven pipeline sections remained without relocation instructions of any kind'});
  Object.assign(S.notice,{date:'2025-11-03',ref:'P2B/SOSA/ART-GCU/11-25/133',aware:'2025-10-13',advance:'P2B/SOSA/ART-GCU/06-25/060 and P2B/SOSA/ART-GCU/09-25/108'});
  S.chronology=[['2025-02-01','the Works commenced','Employer','','' ],['2025-04-01','the Contractor drew the Engineer\u2019s attention to Section 10.4 of the Employer\u2019s Requirements and the incomplete nominated subcontractor list, and requested nominations and joint route inspections','Contractor','P2B/SOSA/ART-GCU/04-25/025','A-1-1'],['2025-04-10','the Contractor submitted its Programme of Works (Revision B)','Contractor','P2B/SOSA/ART-GCU/04-25/029','A-1-2'],['2025-04-29','the Engineer accepted the Programme, confirming that it satisfied the requirements of the Contract','Engineer','W20/CTR/031','B-4'],['2025-05-05','the Engineer characterised the period allowed for service diversions as \u201cexcessive\u201d and as \u201cbelonging to the Employer\u201d in the event of a claim','Engineer','W20/CTR/033','B-5'],['2025-06-23','the Contractor notified the Engineer of a delay of 32 days in the commencement of relocation for Sections 3, 4, 6 and 7 and reserved its entitlement under Sub-Clause 20.1','Contractor','P2B/SOSA/ART-GCU/06-25/060','A-1-6'],['2025-07-14','the Engineer rejected the advance notice of delay, stating that it was \u201cunlikely there will be a delay\u201d','Engineer','W20/CTR/053','B-6'],['2025-09-22','the Engineer acknowledged that it had been \u201ccompelled by various developments since the tender stage, and by the Employer\u2019s latest regulations, to be active in the early stages of the service diversion process\u201d','Engineer','W20/CTR/078','B-10'],['2025-09-30','the Engineer issued the first batch of relocation instructions, 119 days after the Baseline Programme date for commencement of relocation works','Engineer','W20/CTR/073 to W20/CTR/091','B-9'],['2025-10-13','the Employer instructed the Contractor to halt all subcontract signing until further notice, rendering the instructions of no effect','Employer','','C-1'],['2025-11-03','the Contractor submitted its formal Notice of Claim (NoC 001) pursuant to Sub-Clause 20.1','Contractor','P2B/SOSA/ART-GCU/11-25/133','A-1-20']].map(r=>({date:r[0],event:r[1],party:r[2],ref:r[3],annex:r[4]}));
  S.register=S.chronology.filter(r=>r.annex).map(r=>({annex:r.annex,date:r.date,ref:r.ref,party:r.party,subject:r.event.charAt(0).toUpperCase()+r.event.slice(1)}));
  S.mitigation=MIT.map((x,i)=>({id:x[0],on:i<6,detail:['The Contractor identified the services encumbering each route through joint inspections and submitted the lists to the Engineer from 24 April 2025 (letters P2B/SOSA/ART-GCU/04-25/039, /05-25/053, /06-25/066 and /07-25/072, Annexes A-1-3 to A-1-8), in each case before the Baseline Programme date for the section concerned.','The Contractor gave advance notice of delay on 23 June 2025 (Annex A-1-6), renewed it on 15 September 2025 (Annex A-1-17), and raised the matter at every monthly progress meeting.','The Contractor proposed an early start of pipelaying in Sections S001 and N001 on 13 August 2025 (Annex A-1-14) and commenced pipelaying on the shorter sections released to it.','Monthly programme updates were submitted throughout, and idle resources were recorded daily by name, rate and idle days in the Notes for Record (Annexes G1 and G2).','Pipelaying teams, equipment and site resources were mobilised in accordance with the Baseline Programme and held ready for the releases that did not materialise.','The Contractor answered the Engineer\u2019s request for a breakdown of the service diversion period on 31 July 2025 (Annex A-1-9).',''][i]}));
  S.legal.prevention=true;S.legal.objections=[{date:'2025-05-05',ref:'W20/CTR/033',quote:'excessive time allowed for service diversions',answer:'First, the Programme was accepted on 29 April 2025 without qualification, and the Engineer\u2019s later comments do not amend it. Second, the period allowed reflected the procedure in Section 10.4 of the Employer\u2019s Requirements, which the Engineer itself later described as requiring its active involvement. Third, and in any event, float belongs to the project and does not become the Employer\u2019s by assertion.'},{date:'2025-07-14',ref:'W20/CTR/053',quote:'unlikely there will be a delay',answer:'The Engineer\u2019s prediction was overtaken by events: the first instructions were issued 119 days after the Baseline Programme date and were then cancelled by the Employer.'}];
  S.legal.authorities=[{name:'Peak Construction (Liverpool) Ltd v McKinney Foundations Ltd',cite:'(1970) 1 BLR 111',holding:'an employer cannot insist on completion by a date that its own act of prevention has made impossible, so that time is set at large unless the contract provides for an extension for that cause.',clause:''}];
  Object.assign(S.delay,{method:'tia',baseline:'Revision B, submitted on 10 April 2025 and accepted by the Engineer on 29 April 2025 (letter W20/CTR/031, Annex B-4)',from:'2025-05-19',to:'2026-02-28',critical:'211',eot:'253',float:'0',driver:'Section 6 (Route S001, 7.6 km), for which no instructions have been issued',concurrency:'none',windows:'8',notes:'Eight monthly impacted programmes, from July 2025 to February 2026, incorporate 73 delay fragnet activities and 27 relocation activities across all seven sections. Each window inserts the fragnets for the instructions outstanding at the data date and re-schedules the programme, so that the critical path and the projected Date for Completion are read directly from the impacted programme.'});
  Object.assign(S.quantum,{currency:'EUR',from:'2025-10-01',oh:'25',profit:'5',fx:'Local-currency costs are converted at the Contract exchange rate stated in the Contract Data.',cats:{A:[{desc:'Idle equipment, October 2025 to February 2026',basis:'daily rate × idle days (Appendix F)',amount:'118432.16'},{desc:'Idle personnel, October 2025 to February 2026',basis:'daily rate × idle days (Appendix F)',amount:'9214.55'}],B:[{desc:'Extension of the Performance Security',basis:'253 days at the bank\u2019s rate',amount:'96420.00'},{desc:'Extension of insurances',basis:'253 days pro rata',amount:'58200.00'},{desc:'Engineer\u2019s facilities and attendance',basis:'253 days at the monthly rate',amount:'142650.00'}],C:[{desc:'Site establishment and running costs',basis:'253 days at the recorded daily cost',amount:'1856400.00'},{desc:'Supervisory and indirect labour',basis:'253 days at the recorded daily cost',amount:'1244110.00'},{desc:'Retained plant and equipment',basis:'253 days at the internal hire rate',amount:'804230.00'}]}});
  S.overrides={};save();location.hash='';location.reload();};

// ---------- claims-desk state export for the delay check (read by claims.html)
function init(){renderSteps();derived();renderChron();renderMit();renderProps();renderObj();renderAuth();renderQuantum();if(S.step===7)renderReview();}
init();
})();
