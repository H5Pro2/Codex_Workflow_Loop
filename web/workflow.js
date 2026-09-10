/* Standalone graph editor; the server alone owns execution. */
(()=>{
 const q=s=>document.querySelector(s), svgNS='http://www.w3.org/2000/svg';
 let graph={nodes:[],edges:[]}, currentState={}, dirty=false, saving=false, timer, selected=null, zoom=1, version=0, starting=false, saveError='';
 const dialog=q('#flow-dialog'), board=q('#flow-board');
 const grid=20,snap=value=>Math.round(value/grid)*grid;
 board.style.setProperty('--grid-size',grid+'px');
 const el=(tag,text,cls='')=>{const e=document.createElement(tag);e.textContent=text;e.className=cls;return e;};
 const running=()=>['running','stopping'].includes(currentState.workflow?.run?.status);
 const hint=(message,failed=false)=>{q('#flow-hint').textContent=message;q('#flow-hint').classList.toggle('failed',failed);};
 async function api(body){const r=await fetch('/api/workflow',{method:'POST',headers:{'Content-Type':'application/json','X-Workflow-Loop':'1'},body:JSON.stringify(body),signal:AbortSignal.timeout(body.action==='start'?60000:15000)});const data=await r.json();if(!r.ok)throw new Error(data.error||'Workflow-Anfrage fehlgeschlagen');return data;}
 async function save(){
  clearTimeout(timer);if(!dirty)return true;if(saving){timer=setTimeout(save,500);return false;}
  saving=true;saveError='';updateButtons();const v=version;
  try{await api({action:'save',graph});if(v===version)dirty=false;hint(dirty?'Weitere Änderungen werden gespeichert …':'Gespeichert');return !dirty;}
  catch(e){saveError='Änderungen nicht gespeichert: '+e.message;hint(saveError,true);q('#flow-status').textContent=saveError;return false;}
  finally{saving=false;updateButtons();if(dirty&&version!==v)timer=setTimeout(save,300);}
 }
 function changed(){dirty=true;version++;hint('Änderungen werden gespeichert …');clearTimeout(timer);timer=setTimeout(save,500);updateButtons();}
 function updateButtons(){q('#flow-start').disabled=running()||starting||saving;q('#flow-stop').disabled=!running();q('#flow-save').disabled=running()||saving;for(const id of ['node-tool','node-chat'])q('#'+id).disabled=running();}
 function label(n){return n.kind==='start'?'Start':n.kind==='counter'?'Loop / Counter':(currentState.chats||[]).find(c=>c.id===n.chat)?.title||'Codex-Chat';}
 function roundedRoute(points){
  points=points.filter((p,i)=>!i||p[0]!==points[i-1][0]||p[1]!==points[i-1][1]);
  let d=`M ${points[0][0]} ${points[0][1]}`;
  for(let i=1;i<points.length-1;i++){
   const a=points[i-1],b=points[i],c=points[i+1];
   const incoming=Math.hypot(b[0]-a[0],b[1]-a[1]),outgoing=Math.hypot(c[0]-b[0],c[1]-b[1]);
   const r=Math.min(10,incoming/2,outgoing/2);
   const entry=[b[0]-(b[0]-a[0])*r/incoming,b[1]-(b[1]-a[1])*r/incoming];
   const exit=[b[0]+(c[0]-b[0])*r/outgoing,b[1]+(c[1]-b[1])*r/outgoing];
   d+=` L ${entry[0]} ${entry[1]} Q ${b[0]} ${b[1]} ${exit[0]} ${exit[1]}`;
  }
  const end=points.at(-1);return d+` L ${end[0]} ${end[1]}`;
 }
 function drawEdges(){
  const svg=q('#flow-edges');svg.replaceChildren();
  const defs=document.createElementNS(svgNS,'defs');
  for(const type of ['start','chat','loop']){
   const marker=document.createElementNS(svgNS,'marker');marker.id='flow-arrow-'+type;
   for(const [k,v] of Object.entries({viewBox:'0 0 10 10',refX:'9',refY:'5',markerWidth:'7',markerHeight:'7',orient:'auto'}))marker.setAttribute(k,v);
   const arrow=document.createElementNS(svgNS,'path');arrow.setAttribute('d','M 0 0 L 10 5 L 0 10 z');arrow.setAttribute('fill',`var(--edge-${type})`);marker.append(arrow);defs.append(marker);
  }
  svg.append(defs);
  graph.edges.forEach((edge,index)=>{
   const a=graph.nodes.find(n=>n.id===edge.source),b=graph.nodes.find(n=>n.id===edge.target);if(!a||!b)return;
   const path=document.createElementNS(svgNS,'path'),x=a.x+240,y=a.y+50,tx=b.x,ty=b.y+50;
   const type=a.kind==='start'?'start':a.kind==='counter'?'loop':'chat';
   let points;
   if(tx-x>=70){const mid=(x+tx)/2;points=[[x,y],[mid,y],[mid,ty],[tx,ty]];}
   else{
    const height=n=>[...q('#flow-nodes').children].find(c=>c.dataset.node===n.id)?.offsetHeight||160;
    const lane=Math.max(a.y+height(a),b.y+height(b))+32+index*12;
    points=[[x,y],[x+36,y],[x+36,lane],[tx-36,lane],[tx-36,ty],[tx,ty]];
   }
   path.setAttribute('d',roundedRoute(points));path.setAttribute('marker-end',`url(#flow-arrow-${type})`);path.setAttribute('class',`flow-edge edge-${type}`);path.setAttribute('tabindex','0');path.setAttribute('role','button');path.setAttribute('aria-label',`${label(a)} nach ${label(b)} – Verbindung entfernen`);
   const remove=()=>{if(running())return;graph.edges.splice(index,1);changed();drawEdges();};path.onclick=remove;path.onkeydown=e=>{if(['Enter','Delete','Backspace'].includes(e.key)){e.preventDefault();remove();}};svg.append(path);
  });
 }
 function connect(target){
  if(running()||!selected)return;
  if(selected===target){hint('Ein Baustein kann nicht mit sich selbst verbunden werden.',true);return;}
  if(graph.edges.some(e=>e.source===selected)){hint('Dieser Ausgang ist bereits verbunden. Die bestehende Linie zuerst entfernen.',true);selected=null;render();return;}
  graph.edges.push({source:selected,target});selected=null;changed();render();
 }
 function render(){
  const container=q('#flow-nodes');container.replaceChildren();
  for(const n of graph.nodes){
   const card=el('article','',`flow-node ${n.kind}`);card.dataset.node=n.id;card.style.left=n.x+'px';card.style.top=n.y+'px';
   const header=el('div','','flow-node-head'),name=el('strong',label(n)),remove=el('button','×','quiet');remove.setAttribute('aria-label',label(n)+' entfernen');remove.disabled=running();remove.onclick=()=>{graph.nodes=graph.nodes.filter(x=>x.id!==n.id);graph.edges=graph.edges.filter(e=>e.source!==n.id&&e.target!==n.id);changed();render();};header.append(name,remove);card.append(header);
   card.onpointerdown=e=>{if(e.button!==0||e.target.closest('button,input,textarea,select'))return;e.preventDefault();header.setPointerCapture(e.pointerId);const x=e.clientX,y=e.clientY,ox=n.x,oy=n.y;
    header.onpointermove=move=>{n.x=Math.max(20,Math.min(1900,snap(ox+(move.clientX-x)/zoom)));n.y=Math.max(20,Math.min(1200,snap(oy+(move.clientY-y)/zoom)));card.style.left=n.x+'px';card.style.top=n.y+'px';drawEdges();};
    header.onpointerup=()=>{header.onpointermove=null;header.onpointerup=null;changed();};header.onpointercancel=()=>{header.onpointermove=null;changed();};};
   if(n.kind!=='start'){const input=el('button','', 'flow-port input');input.dataset.in=n.id;input.title='Eingang';input.setAttribute('aria-label',label(n)+' Eingang');input.onclick=()=>connect(n.id);input.disabled=running();card.append(input);}
   const output=el('button','',`flow-port output ${selected===n.id?'selected':''}`);output.title='Ausgang – zum Eingang eines anderen Bausteins ziehen oder klicken';output.setAttribute('aria-label',label(n)+' Ausgang');output.disabled=running();output.onpointerdown=e=>{if(e.button!==0)return;e.stopPropagation();selected=n.id;output.classList.add('selected');hint('Jetzt einen Eingang auswählen oder die Verbindung dorthin ziehen.');};output.onclick=()=>{selected=n.id;};card.append(output);
   if(n.kind==='start')card.append(el('span','Letzte Antwort des ersten verbundenen Chats weitergeben.','flow-chat-status'));
   if(n.kind==='counter'){const lab=el('label','Durchläufe (nach Rückgabe)'),input=document.createElement('input');input.type='number';input.min=1;input.max=1000;input.value=n.limit;input.disabled=running();input.onchange=()=>{n.limit=Number(input.value);changed();};lab.append(input);card.append(lab,el('span','0 / '+n.limit,'flow-counter'));}
   if(n.kind==='chat')card.append(el('span','', 'flow-chat-status'));
   container.append(card);
  }
  const select=q('#node-chat');select.replaceChildren(new Option('Chat-Auswahl',''));for(const c of currentState.chats||[])if(!graph.nodes.some(n=>n.chat===c.id))select.add(new Option(c.title||c.label||c.id,c.id));
  drawEdges();paintStatus();updateButtons();
 }
 function paintStatus(){
  for(const card of q('#flow-nodes').children){const n=graph.nodes.find(n=>n.id===card.dataset.node);if(!n)continue;card.classList.toggle('executing',running()&&currentState.workflow?.run?.node===n.id);
   if(n.kind==='counter')card.querySelector('.flow-counter').textContent=`${currentState.workflow?.run?.counts?.[n.id]||0} / ${n.limit}`;
   if(n.kind==='chat'){const c=currentState.chats?.find(c=>c.id===n.chat);card.querySelector('.flow-chat-status').textContent=({working:'◌ Arbeitet',complete:'Fertig',waiting:'Überwacht',paused:'Pausiert',unknown:'Status unklar',error:'Hinweis',searching:'Suche'})[c?.state]||'Bereit';}
  }
 }
 function add(kind,chat){if(running())return;if(kind==='start'&&graph.nodes.some(n=>n.kind==='start')){hint('Es gibt bereits einen Start-Baustein.',true);return;}const i=graph.nodes.length;graph.nodes.push({id:crypto.randomUUID(),kind,x:40+(i%3)*320,y:40+Math.floor(i/3)*260,...(kind==='chat'?{chat}:kind==='start'?{}:{limit:5})});changed();render();}
 document.addEventListener('pointerup',e=>{if(e.button!==0)return;const target=document.elementFromPoint(e.clientX,e.clientY)?.closest('[data-in]');if(target&&selected){connect(target.dataset.in);}});
 q('#flow-open').onclick=()=>{if(!dirty)graph=structuredClone(currentState.workflow?.graph||{nodes:[],edges:[]});dialog.showModal();render();};
 q('#flow-close').onclick=()=>{dialog.close();save();};dialog.addEventListener('cancel',()=>{save();});
 q('#node-tool').onchange=e=>{const kind=e.target.value;e.target.value='';if(kind)add(kind);};q('#node-chat').onchange=e=>{if(e.target.value)add('chat',e.target.value);};q('#flow-save').onclick=save;
 function setZoom(value){zoom=Math.max(.4,Math.min(1.4,value));board.style.transform=`scale(${zoom})`;q('#flow-space').style.width=2200*zoom+'px';q('#flow-space').style.height=1450*zoom+'px';q('#zoom-label').textContent=Math.round(zoom*100)+' %';}
 const viewport=q('#flow-viewport');
 let pan=null;
 viewport.addEventListener('contextmenu',e=>e.preventDefault());
 viewport.addEventListener('pointerdown',e=>{
  if(e.button!==2)return;
  e.preventDefault();
  pan={id:e.pointerId,x:e.clientX,y:e.clientY,left:viewport.scrollLeft,top:viewport.scrollTop};
  viewport.setPointerCapture(e.pointerId);
  viewport.classList.add('panning');
 },true);
 viewport.addEventListener('pointermove',e=>{
  if(!pan||e.pointerId!==pan.id)return;
  viewport.scrollLeft=pan.left-(e.clientX-pan.x);
  viewport.scrollTop=pan.top-(e.clientY-pan.y);
 });
 function endPan(e){
  if(!pan||e.pointerId!==pan.id)return;
  pan=null;viewport.classList.remove('panning');
  if(viewport.hasPointerCapture(e.pointerId))viewport.releasePointerCapture(e.pointerId);
 }
 viewport.addEventListener('pointerup',endPan);
 viewport.addEventListener('pointercancel',endPan);
 viewport.addEventListener('lostpointercapture',endPan);

 viewport.addEventListener('wheel',e=>{
  e.preventDefault();
  const rect=viewport.getBoundingClientRect();
  const x=e.clientX-rect.left-viewport.clientLeft,y=e.clientY-rect.top-viewport.clientTop;
  const worldX=(viewport.scrollLeft+x)/zoom,worldY=(viewport.scrollTop+y)/zoom;
  const delta=e.deltaY*(e.deltaMode===1?16:e.deltaMode===2?viewport.clientHeight:1);
  setZoom(zoom*Math.exp(-Math.max(-150,Math.min(150,delta))*.002));
  viewport.scrollLeft=worldX*zoom-x;viewport.scrollTop=worldY*zoom-y;
 },{passive:false});
 q('#flow-start').onclick=async()=>{
  if(running()||starting||saving)return;
  starting=true;updateButtons();
  try{
   if(dirty&&!await save())return;
   const result=await api({action:'start'});window.WorkflowUI.update(result);
  }catch(e){q('#flow-status').textContent=e.message;}
  finally{starting=false;updateButtons();}
 };
 q('#flow-stop').onclick=async()=>{try{window.WorkflowUI.update(await api({action:'stop'}));}catch(e){q('#flow-status').textContent=e.message;}};
 window.WorkflowUI={reloadGraph(){graph=structuredClone(currentState.workflow?.graph||{nodes:[],edges:[]});dirty=false;clearTimeout(timer);if(dialog.open)render();},update(state){const wasRunning=running();currentState=state;if(wasRunning&&!running()&&dirty)save();q('#flow-status').textContent=saveError||state.workflow?.run?.message||'Start mit dem Quellchat verbinden.';updateButtons();if(dialog.open&&wasRunning!==running())render();else paintStatus();}};
})();
