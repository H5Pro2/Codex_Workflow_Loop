const $ = selector => document.querySelector(selector);
const cards = new Map();
let state = {chats: [], events: []}, online = false, busy = false, stopped = false;
let knownEvents = null, knownForward, audio;
let revision=0;
let transfer=null;
let chatDrag=null;
function beginChatDrag(e,card){
  if(e.button!==0||e.target.closest('button,input,textarea,select,a,label,[contenteditable]')||busy||chatDrag)return;
  e.preventDefault();
  const startY=e.clientY,pointer=e.pointerId;
  let moved=false,before=null,finishing=false;
  const marker=document.createElement('div');marker.className='chat-drop-marker';
  const origin=card.getBoundingClientRect(),offsetX=e.clientX-origin.left,offsetY=e.clientY-origin.top;
  const reduced=window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const ghost=card.cloneNode(true);ghost.classList.add('chat-drag-preview');ghost.setAttribute('aria-hidden','true');ghost.inert=true;
  ghost.removeAttribute('id');ghost.querySelectorAll('[id]').forEach(el=>el.removeAttribute('id'));
  ghost.style.width=origin.width+'px';

  chatDrag=card;
  const move=event=>{
    if(event.pointerId!==pointer||finishing)return;
    if(!(event.buttons&1)){finish({type:'pointercancel'});return;}
    if(Math.abs(event.clientY-startY)<5&&!moved)return;
    if(!moved){moved=true;document.body.append(marker,ghost);card.classList.add('dragging');document.body.classList.add('reordering-chats');if(!reduced)ghost.animate([{transform:'scale(1)'},{transform:'scale(1.025)'}],{duration:160,easing:'ease-out'});}
    const siblings=[...document.querySelectorAll('#chats .chat')].filter(c=>c!==card);
    before=siblings.find(c=>event.clientY<c.getBoundingClientRect().top+c.getBoundingClientRect().height/2)||null;
    const rect=$('#chats').getBoundingClientRect();
    const last=siblings.at(-1);
    const y=before?before.getBoundingClientRect().top-6:last?last.getBoundingClientRect().bottom+6:rect.top;
    marker.style.cssText=`left:${rect.left}px;top:${y}px;width:${rect.width}px`;
    ghost.style.left=(event.clientX-offsetX)+'px';ghost.style.top=(event.clientY-offsetY)+'px';
    if(event.clientY<70)window.scrollBy(0,-24);
    else if(event.clientY>window.innerHeight-70)window.scrollBy(0,24);
  };
  const finish=async event=>{
    if(finishing||(event.pointerId!==undefined&&event.pointerId!==pointer))return;
    finishing=true;
    try{
    document.removeEventListener('pointermove',move);document.removeEventListener('pointerup',finish);document.removeEventListener('pointercancel',finish);document.removeEventListener('keydown',escape);window.removeEventListener('blur',finish);card.removeEventListener('lostpointercapture',finish);document.removeEventListener('visibilitychange',visibility);
    if(card.hasPointerCapture(pointer))card.releasePointerCapture(pointer);
    marker.remove();document.body.classList.remove('reordering-chats');
    if(moved&&event.type==='pointerup'){
      const rect=$('#chats').getBoundingClientRect();
      if(event.clientX>=rect.left&&event.clientX<=rect.right){
        const order=state.chats.map(c=>c.id).filter(id=>id!==card.dataset.id);
        const index=before?order.indexOf(before.dataset.id):order.length;
        order.splice(index<0?order.length:index,0,card.dataset.id);
        const positions=new Map([...document.querySelectorAll('#chats .chat')].map(c=>[c,c.getBoundingClientRect().top]));
        if(before&&!before.isConnected)before=null;
        $('#chats').insertBefore(card,before);
        const destination=card.getBoundingClientRect();
        if(!reduced){
          for(const [other,top] of positions){if(other!==card)other.animate([{transform:`translateY(${top-other.getBoundingClientRect().top}px)`},{transform:'translateY(0)'}],{duration:220,easing:'ease-out'});}
          const landing=ghost.animate([{left:ghost.style.left,top:ghost.style.top,transform:'scale(1.025)'},{left:destination.left+'px',top:destination.top+'px',transform:'scale(1)'}],{duration:220,easing:'cubic-bezier(.2,.8,.2,1)',fill:'forwards'});
          await Promise.race([landing.finished.catch(()=>{}),new Promise(resolve=>setTimeout(resolve,350))]);
          landing.cancel();
        }
        ghost.remove();card.classList.remove('dragging');
        await command('reorder',order);
      }
    }
    }catch(err){error('Anordnen fehlgeschlagen: '+err.message);}
    finally{
      ghost.getAnimations().forEach(animation=>animation.cancel());ghost.remove();marker.remove();
      card.classList.remove('dragging');document.body.classList.remove('reordering-chats');chatDrag=null;render();
    }
  };
  const escape=event=>{if(event.key==='Escape')finish(event);};
  const visibility=()=>{if(document.hidden)finish({type:'pointercancel'});};
  document.addEventListener('pointermove',move);document.addEventListener('pointerup',finish);document.addEventListener('pointercancel',finish);document.addEventListener('keydown',escape);window.addEventListener('blur',finish);
  document.addEventListener('visibilitychange',visibility);card.addEventListener('lostpointercapture',finish);
  try{card.setPointerCapture(pointer);}catch{finish({type:'pointercancel'});}
}
async function prepareTransfer(id){
  if(!transfer||busy)return;
  busy=true;revision++;error('');render();
  const feedback=cards.get(id).querySelector('.copy-feedback');
  feedback.textContent='Übergabe an die Codex-App …';
  try{
    await request('/api/send',{token:transfer.token,target:id});
    feedback.textContent='Von der Codex-App angenommen · Nachricht gesendet';
    transfer=null;
  }catch(e){feedback.textContent='Versand nicht bestätigt';error(e.message);}
  finally{busy=false;state=await request('/api/state').catch(()=>state);render();}
}
async function copyAnswer(id){
  if(busy)return;
  busy=true;revision++;error('');
  try{
    const answer=await request('/api/copy',{id});
    await navigator.clipboard.writeText(answer.text);
    transfer=answer;
    cards.get(id).querySelector('.copy-feedback').textContent='Antwort kopiert';
  }catch(e){error('Kopieren fehlgeschlagen: '+e.message);}
  finally{busy=false;render();}
}
const defaultTheme={bg:'#181818',panel:'#212121',text:'#eeeeee',accent:'#eeeeee',green:'#91d5ad',waiting:'#a2a2a2',working:'#b6c9f7',paused:'#a2a2a2',searching:'#e3ca86',error:'#efb6a6'};
let editingTheme=false;
function applyTheme(theme){
  theme={...defaultTheme,...theme};
  for(const [key,value] of Object.entries(theme))document.documentElement.style.setProperty('--'+key,value);
  const rgb=theme.accent.slice(1).match(/../g).map(v=>parseInt(v,16));
  document.documentElement.style.setProperty('--accent-text',rgb[0]*.299+rgb[1]*.587+rgb[2]*.114>150?'#181818':'#ffffff');
}
function draftTheme(){return Object.fromEntries([...document.querySelectorAll('#colors input')].map(input=>[input.dataset.key,input.value]));}
function fillTheme(theme){theme={...defaultTheme,...theme};for(const input of document.querySelectorAll('#colors input')){input.value=theme[input.dataset.key];input.nextElementSibling.textContent=input.value;}applyTheme(theme);}
function node(tag, className, text) { const el = document.createElement(tag); el.className = className; el.textContent = text; return el; }
function error(message) { $('#error').textContent = message; $('#error').hidden = !message; }
function time(value) { return new Date(value).toLocaleString('de-DE', {day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'}); }
async function request(path, body) {
  const response = await fetch(path, body ? {method:'POST', headers:{'Content-Type':'application/json','X-Workflow-Loop':'1'},body:JSON.stringify(body),signal:AbortSignal.timeout(path==='/api/send'?120000:5000)} : {signal:AbortSignal.timeout(5000)});
  const data = await response.json(); if (!response.ok) throw new Error(data.error || 'Anfrage fehlgeschlagen'); return data;
}
async function command(action, id, label='') {
  if (busy) return false;
  busy=true; revision++; error('');
  try { state=await request('/api/command',{action,id,label}); render(); return true; }
  catch(e) { error(e.message); return false; }
  finally { busy=false; }
}
function render() {
  window.WorkflowUI?.update(state);
  if(!editingTheme)applyTheme(state.theme||defaultTheme);
  $('#sound').checked=state.sound;
  $('#sound-forward').checked=!!state.sound_forward;
  $('#activity-body').hidden=!!state.activity_collapsed;
  $('#activity-toggle').setAttribute('aria-expanded',String(!state.activity_collapsed));
  $('#activity-arrow').textContent=state.activity_collapsed?'▸':'▾';
  $('#events-clear').disabled=!state.events.length;
  $('#total').textContent=state.chats.length;
  const loopNodes=state.workflow?.graph?.nodes||[];
  const loopEdges=state.workflow?.graph?.edges||[];
  const reachable=new Set();let step=loopNodes.find(n=>n.kind==='start')?.id;
  while(step&&!reachable.has(step)){reachable.add(step);step=loopEdges.find(edge=>edge.source===step)?.target;}
  const counters=loopNodes.filter(n=>n.kind==='counter'&&reachable.has(n.id));
  $('#loop-progress').textContent=counters.length?counters.map((counter,index)=>`${counters.length>1?'Counter '+(index+1):'Durchläufe'} ${state.workflow?.run?.counts?.[counter.id]||0} / ${counter.limit}`).join(' · '):'Durchläufe –';
  $('#loop-progress').title=counters.length?'Abgeschlossene Durchläufe / eingestelltes Limit':'Noch kein Counter mit dem Start verbunden';

  const ids=new Set(state.chats.map(c=>c.id));
  for(const [id, card] of cards) if(!ids.has(id)){card.remove();cards.delete(id);}
  $('#chats .empty')?.remove();
  if(!state.chats.length){const empty=node('div','empty','Füge eine Chat-ID oder einen Deeplink hinzu.');empty.prepend(node('strong','','Dein erster Chat wartet.'));$('#chats').append(empty);}
  for(const chat of state.chats){
    let card=cards.get(chat.id);
    if(!card){
      card=node('article','chat','');card.dataset.id=chat.id;
      const head=node('div','card-head','');card.addEventListener('pointerdown',e=>beginChatDrag(e,card));
      const nameLine=node('div','name-line','');
      const spinner=node('span','spinner','');spinner.setAttribute('role','img');spinner.setAttribute('aria-label','Chat arbeitet');spinner.title='Chat arbeitet';spinner.hidden=true;
      nameLine.append(node('span','name',''),spinner);const headActions=node('div','card-head-actions','');headActions.append(node('span','badge',''));head.append(nameLine,headActions);
      const bottom=node('div','card-bottom','');const actions=node('div','actions','');
      const remove=node('button','quiet remove-chat','×');remove.title='Chat entfernen';remove.setAttribute('aria-label','Chat entfernen');headActions.append(remove);remove.onclick=()=>command('remove',chat.id);
      const toggle=node('button','toggle','');toggle.onclick=()=>{const current=state.chats.find(c=>c.id===chat.id);if(current)command(current.active?'pause':'start',chat.id);};
      const copy=node('button','copy','Kopieren');copy.onclick=()=>copyAnswer(chat.id);
      const paste=node('button','paste','Einfügen');paste.onclick=()=>prepareTransfer(chat.id);
      const details=node('div','chat-details','');details.id='details-'+chat.id;details.hidden=true;
      const identityRow=node('div','identity-row','');
      const edit=node('button','quiet reassign-button','✎');edit.title='Chat-Zuweisung ändern';edit.setAttribute('aria-label','Chat-Zuweisung ändern');edit.setAttribute('aria-haspopup','dialog');
      edit.onclick=()=>{
        $('#reassign-dialog').dataset.source=chat.id;
        $('#reassign-id').value=chat.id;
        $('#reassign-error').textContent='';
        $('#reassign-dialog').showModal();$('#reassign-id').focus();
      };
      identityRow.append(node('div','id',chat.id),edit);
      details.append(identityRow,node('p','message',''),node('span','meta',''));

      const disclosure=node('button','quiet details-toggle','▸ Details');disclosure.setAttribute('aria-expanded','false');disclosure.setAttribute('aria-controls',details.id);
      disclosure.onclick=()=>{details.hidden=!details.hidden;disclosure.setAttribute('aria-expanded',String(!details.hidden));disclosure.textContent=details.hidden?'▸ Details':'▾ Details';};
      actions.append(toggle,copy,paste);bottom.append(disclosure,actions);
      const feedback=node('span','copy-feedback','');feedback.setAttribute('role','status');
      card.append(head,bottom,feedback,details);cards.set(chat.id,card);$('#chats').append(card);
    }
    if(!chatDrag) { const position=state.chats.indexOf(chat); const existing=$('#chats').children[position]; if(existing!==card)$('#chats').insertBefore(card,existing||null); }
    card.dataset.state=chat.state;
    card.querySelector('.name').textContent=chat.title||chat.label||'Codex-Chat';
    const spinner=card.querySelector('.spinner');
    spinner.hidden=chat.state!=='working'||!chat.active||!online;
    spinner.title=chat.state==='working'?'Chat arbeitet · Überwachung aktiv':'Überwachung aktiv';
    spinner.setAttribute('aria-label',spinner.title);
    card.querySelector('.badge').textContent=({paused:'Pausiert',searching:'Suche',waiting:'Überwacht',working:'Arbeitet',complete:'Fertig',error:'Hinweis',unknown:'Status unklar'})[chat.state];
    card.querySelector('.message').textContent=chat.message;
    card.querySelector('.meta').textContent=(chat.active?'Überwachung aktiv · ':'Überwachung pausiert · ')+(chat.last?`${chat.count} Abschlüsse · ${time(chat.last)}`:'Noch kein neuer Abschluss');
    const monitorToggle=card.querySelector('.toggle');
    monitorToggle.innerHTML=chat.active?'<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" focusable="false"><rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/></svg>':'Überwachen';
    monitorToggle.title=chat.active?'Überwachung pausieren':'Überwachung starten';
    monitorToggle.setAttribute('aria-label',monitorToggle.title);
    card.querySelector('.toggle').className=chat.active?'toggle':'toggle primary';
    card.querySelectorAll('.actions button').forEach(b=>b.disabled=!online);
    card.querySelector('.copy').disabled=!online||busy||!chat.can_copy||chat.state==='working';
    card.querySelector('.copy').title=chat.can_copy?'Vollständige Abschlussantwort kopieren':'Erst nach einer vollständigen Antwort verfügbar';
    const inWorkflow=['running','stopping'].includes(state.workflow?.run?.status)&&state.workflow.run.participants.includes(chat.id);
    if(inWorkflow)card.querySelectorAll('.actions button').forEach(b=>b.disabled=true);
    card.querySelector('.remove-chat').disabled=inWorkflow||!online||busy;
    card.querySelector('.reassign-button').disabled=['running','stopping'].includes(state.workflow?.run?.status)||!online||busy;
    card.querySelector('.remove-chat').setAttribute('aria-label',(chat.title||chat.label||'Chat')+' entfernen');
    card.querySelector('.paste').disabled=inWorkflow||!online||busy||!transfer||transfer.source===chat.id||!chat.can_paste;
    card.querySelector('.paste').title=!transfer?'Zuerst eine Antwort kopieren':transfer.source===chat.id?'Einfügen im Quellchat gesperrt':!chat.can_paste?'Der Zielchat ist derzeit nicht verfügbar':'Kopierte Antwort in diesem Codex-Chat senden und starten';
  }
  const signature=state.events.map(e=>e.key).join();
  if($('#events').dataset.signature!==signature || !$('#events').hasChildNodes()){
    $('#events').dataset.signature=signature;$('#events').replaceChildren();
    if(!state.events.length)$('#events').append(node('div','empty','Neue Antwortabschlüsse erscheinen hier.'));
    for(const event of state.events){const el=node('div','event',event.message);el.append(node('small','',`${event.label||event.chat} · ${time(event.time)}`));$('#events').append(el);}
  }
  const next=new Set(state.events.map(e=>e.key));
  const finished=knownEvents && [...next].some(key=>!knownEvents.has(key)) && state.sound;
  const forwarded=knownForward!==undefined && state.last_forward && knownForward!==state.last_forward && state.sound_forward;
  if((finished||forwarded)&&audio){const osc=audio.createOscillator(),gain=audio.createGain();osc.connect(gain);gain.connect(audio.destination);gain.gain.setValueAtTime(.08,audio.currentTime);gain.gain.exponentialRampToValueAtTime(.001,audio.currentTime+.25);osc.frequency.value=forwarded?880:660;osc.start();osc.stop(audio.currentTime+.25);}
  knownForward=state.last_forward;
  knownEvents=next;

}
async function poll(){
  if(stopped)return;
  try{if(!busy){const currentRevision=revision;const result=await request('/api/state');if(currentRevision===revision&&!busy&&!stopped){state=result;online=true;$('#connection').textContent='● Verbunden';$('#connection').className='connection online';render();}}}
  catch{online=false;$('#connection').textContent='○ Verbindung unterbrochen';$('#connection').className='connection';document.querySelectorAll('.chat button').forEach(b=>b.disabled=true);document.querySelectorAll('.spinner').forEach(s=>s.hidden=true);}
  setTimeout(poll,1000);
}
$('#add').onclick=()=>{$('#form').hidden=false;$('#identity').focus();};
for(const [heading,fields] of Object.entries({Layout:{bg:'Hintergrund',panel:'Chat-Karten',text:'Text',accent:'Schaltflächen'},Statusmeldungen:{waiting:'Überwacht',working:'Arbeitet',green:'Fertig',paused:'Pausiert',searching:'Suche',error:'Hinweis / Fehler'}})){
 const group=node('fieldset','color-group','');group.append(node('legend','',heading));$('#colors').append(group);
 for(const [key,label] of Object.entries(fields)){
  const row=node('label','color-row','');const input=document.createElement('input');input.type='color';input.dataset.key=key;input.setAttribute('aria-label',label);
  row.append(node('span','',label),input,node('span','color-value',''));group.append(row);
  input.oninput=()=>{input.nextElementSibling.textContent=input.value;applyTheme(draftTheme());$('#settings-feedback').textContent='Vorschau · noch nicht gespeichert';};
 }
}
function closeSettings(){editingTheme=false;$('#settings').close();$('#setup').setAttribute('aria-expanded','false');applyTheme(state.theme||defaultTheme);$('#setup').focus();}
$('#setup').onclick=()=>{if(editingTheme){closeSettings();return;}editingTheme=true;fillTheme(state.theme||defaultTheme);$('#settings').showModal();$('#setup').setAttribute('aria-expanded','true');$('#settings-feedback').textContent='Für alle Browseransichten dieser Installation gespeichert.';$('#colors input').focus();};
$('#settings-close').onclick=closeSettings;
$('#settings').addEventListener('cancel',event=>{event.preventDefault();closeSettings();});
$('#theme-reset').onclick=()=>{fillTheme(defaultTheme);$('#settings-feedback').textContent='Standardfarben als Vorschau · zum Übernehmen speichern';};
$('#theme-save').onclick=async()=>{const button=$('#theme-save');button.disabled=true;const saved=await command('theme',draftTheme());button.disabled=false;$('#settings-feedback').textContent=saved?'Farben gespeichert.':'Speichern fehlgeschlagen. Bitte erneut versuchen.';};
$('#cancel').onclick=()=>{$('#form').hidden=true;error('');};
$('#form').onsubmit=async event=>{event.preventDefault();if(await command('add',$('#identity').value,$('#label').value)){$('#form').reset();$('#form').hidden=true;}};
$('#sound').onchange=()=>{const enabled=$('#sound').checked;if(enabled){audio??=new AudioContext();audio.resume();}command('sound',enabled);};
document.addEventListener('click',()=>{if($('#sound').checked||$('#sound-forward').checked){audio??=new AudioContext();audio.resume();}});
$('#shutdown').onclick=async()=>{try{await request('/api/shutdown',{});stopped=true;online=false;document.querySelectorAll('.spinner').forEach(s=>s.hidden=true);$('#connection').textContent='○ Dienst beendet';$('#connection').className='connection';document.querySelectorAll('button').forEach(b=>b.disabled=true);error('Dienst beendet. Zum Starten erneut Start.bat öffnen.');}catch(e){error(e.message);}};
poll();
if(document.modelContext?.registerTool){
  const lifecycle=new AbortController();
  window.addEventListener('pagehide',()=>lifecycle.abort(),{once:true});
  try{Promise.resolve(document.modelContext.registerTool({
    name:'read_chat_monitor_status',title:'Chat-Überwachung lesen',
    description:'Liest die gespeicherten Chat-Überwachungen und ihre aktuellen Abschlussmeldungen.',
    inputSchema:{type:'object',properties:{},additionalProperties:false},
    annotations:{readOnlyHint:true,untrustedContentHint:true},
    async execute(input){if(input && Object.keys(input).length)throw new Error('Keine Parameter erwartet');return await request('/api/state');}
  },{signal:lifecycle.signal})).catch(()=>{});}catch{}
}


$('#events-clear').onclick=()=>command('clear_events');
$('#activity-toggle').onclick=()=>command('activity_collapsed',!state.activity_collapsed);

$('#sound-forward').onchange=async()=>{const enabled=$('#sound-forward').checked;if(enabled){audio??=new AudioContext();audio.resume();}await command('sound_forward',enabled);render();};

// Close only a deliberate backdrop click, not a drag out of the dialog.
for(const [dialogId,closeId] of [['settings','settings-close'],['flow-dialog','flow-close'],['reassign-dialog','reassign-close']]){
  const dialog=document.getElementById(dialogId);
  let backdropPress=false;
  const outside=e=>{
    const rect=dialog.getBoundingClientRect();
    return e.target===dialog&&(e.clientX<rect.left||e.clientX>rect.right||e.clientY<rect.top||e.clientY>rect.bottom);
  };
  dialog.addEventListener('pointerdown',e=>{backdropPress=e.button===0&&outside(e);});
  dialog.addEventListener('pointercancel',()=>{backdropPress=false;});
  dialog.addEventListener('close',()=>{backdropPress=false;});
  dialog.addEventListener('click',e=>{
    const shouldClose=backdropPress&&outside(e);
    backdropPress=false;
    if(shouldClose)document.getElementById(closeId).click();
  });
}

$('#reassign-close').onclick=()=>$('#reassign-dialog').close();
$('#reassign-form').onsubmit=async e=>{
  e.preventDefault();
  const button=$('#reassign-apply');button.disabled=true;
  $('#reassign-error').textContent='';
  try{
    if(await command('reassign',$('#reassign-dialog').dataset.source,$('#reassign-id').value)){
      transfer=null;window.WorkflowUI?.reloadGraph?.();render();$('#reassign-dialog').close();
    }else{
      $('#reassign-error').textContent=$('#error').textContent||'Bitte erneut versuchen.';
    }
  }finally{button.disabled=false;}
};
