(()=>{
 const panel=document.getElementById('debug-panel'),container=document.getElementById('debug-entries'),feedback=document.getElementById('debug-error');
 const names={service_started:'Dienst gestartet',chat_status:'Chatstatus',preflight_requested:'Verbindung prüfen',preflight_confirmed:'Verbindung bestätigt',preflight_failed:'Verbindungsprüfung fehlgeschlagen',workflow_started:'Loop gestartet',dispatch_requested:'Versand angefordert',dispatch_confirmed:'Versand bestätigt',dispatch_unconfirmed:'Versand nicht bestätigt',turn_detected:'Neuer Antwortdurchlauf',turn_completed:'Antwortdurchlauf fertig',workflow_state:'Laufstatus / Counter',stop_requested:'Stopp angefordert',unexpected_turn:'Zusätzlicher Auftrag erkannt'};
 let timer,inflight=false,signature='',generation=0;
 async function read(){const r=await fetch('/api/debug',{signal:AbortSignal.timeout(5000)});if(!r.ok)throw Error('Debug-Protokoll nicht erreichbar');return r.json();}
 async function refresh(){
  clearTimeout(timer);if(!panel.open||inflight)return;inflight=true;const current=generation;
  try{
   const data=await read();if(current!==generation)return;feedback.textContent=data.error||`${data.entries.length} / ${data.limit} Einträge · neueste zuerst`;
   const next=data.entries.map(e=>e.id).join();
   if(next!==signature||!container.hasChildNodes()){
    const opened=new Set([...container.querySelectorAll('details[open]')].map(e=>e.dataset.id));
    signature=next;container.replaceChildren();
    for(const entry of [...data.entries].reverse()){
     const row=document.createElement('details');row.dataset.id=entry.id;row.open=opened.has(entry.id);
     const title=document.createElement('summary');title.textContent=`${new Date(entry.time).toLocaleString('de-DE')} · ${names[entry.event]||entry.event}`;
     const fields=document.createElement('pre');fields.textContent=JSON.stringify(entry,null,2);
     row.append(title);
     if(entry.source&&entry.target){const route=document.createElement('p');route.textContent=`${entry.source_name||entry.source} → ${entry.target_name||entry.target}`;row.append(route);}
     row.append(fields);container.append(row);
    }
    if(!data.entries.length)container.textContent='Noch keine Debug-Einträge.';
   }
  }catch(e){feedback.textContent=e.message;}
  finally{inflight=false;if(panel.open)timer=setTimeout(refresh,1500);}
 }
 panel.addEventListener('toggle',()=>{try{localStorage.setItem('debug-open',String(panel.open));}catch{}refresh();});
 try{panel.open=localStorage.getItem('debug-open')==='true';}catch{}
 document.getElementById('debug-clear').onclick=async()=>{
  try{const r=await fetch('/api/command',{method:'POST',headers:{'Content-Type':'application/json','X-Workflow-Loop':'1'},body:JSON.stringify({action:'clear_debug'}),signal:AbortSignal.timeout(5000)});if(!r.ok)throw Error('Leeren fehlgeschlagen');generation++;signature=null;container.textContent='Noch keine Debug-Einträge.';feedback.textContent='Debug-Protokoll geleert.';await refresh();}catch(e){feedback.textContent=e.message;}
 };
 document.getElementById('debug-export').onclick=async()=>{
  try{const data=await read();const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='codex-workflow-debug.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(e){feedback.textContent=e.message;}
 };
 refresh();
})();
