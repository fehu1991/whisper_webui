'use strict';
const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="workspace-token"]').content;
const frame = $('editor-frame');
let ws, media, context, source, worklet, sessionId = '', busy = false, stopping = false;
let samples = 0, unread = 0, confirmed = 0, pendingRows = [], lastSaved = '', saveTimer, saveChain = Promise.resolve();
let flushResolve, micWasReady = false;
const bridge = () => frame.contentWindow?.transcriptBridge;
const error = message => { $('error').textContent = message; $('error').hidden = !message; };
const phase = message => { $('phase').textContent = message; };
function route() {
  const editor = location.hash === '#editor';
  $('page-capture').hidden = editor; $('page-editor').hidden = !editor;
  $('nav-capture').toggleAttribute('aria-current', !editor); $('nav-editor').toggleAttribute('aria-current', editor);
  if (editor) { $('nav-editor').setAttribute('aria-current','page'); unread=0; $('new-count').textContent=''; }
  else $('nav-capture').setAttribute('aria-current','page');
  $('main').focus({preventScroll:true});
}
window.addEventListener('hashchange',route); route();
async function api(path, options={}) {
  const response = await fetch('/live/api/'+path, {...options, headers:{'x-workspace-token':token,'Content-Type':'application/json',...(options.headers||{})}});
  if (!response.ok) { const body = await response.json().catch(()=>({})); throw new Error(body.detail || '本機服務無法回應。'); }
  return response.json();
}
function controls() {
  for(const id of ['model','language','microphone','record-audio','load-session','recheck']) $(id).disabled=busy;
  $('start').disabled=busy || !$('model').value || !$('model').dataset.ready;
  $('stop').disabled=!busy || stopping;
}
function queueSave() { clearTimeout(saveTimer); saveTimer=setTimeout(save,700); }
function save() {
  if (!bridge()) return Promise.resolve(false);
  if (!sessionId) {
    const empty=!bridge().snapshot().text;
    if(!empty) $('save-status').textContent='匯入的文字尚未建立場次，請使用編輯器下載 TXT';
    return Promise.resolve(empty);
  }
  const snapshot=bridge().snapshot(), encoded=JSON.stringify(snapshot), id=sessionId;
  if(encoded===lastSaved) return saveChain;
  $('save-status').textContent='正在儲存本機修改…';
  saveChain=saveChain.catch(()=>{}).then(async()=>{
    await api('sessions/'+id,{method:'PUT',body:encoded});
    if(id===sessionId){lastSaved=encoded; $('save-status').textContent='已儲存於本機 '+new Date().toLocaleTimeString('zh-TW');}
    return true;
  }).catch(e=>{ $('save-status').textContent='儲存失敗，請重試或下載 TXT'; error(e.message); return false; });
  return saveChain;
}
async function protectCurrent() {
  if(!bridge()?.snapshot().text) return sessionId ? save() : true;
  if(!sessionId) return confirm('目前匯入的內容沒有自動儲存。請先取消並下載 TXT；若已下載，按確定清空畫面並繼續。');
  return save();
}
window.addEventListener('message',event=>{
  if(event.source===frame.contentWindow && event.origin===location.origin && event.data?.type==='editor-dirty') queueSave();
});
function append(rows) {
  if(!bridge()){pendingRows.push(...rows); return;}
  const count=bridge().append(rows); confirmed+=count; unread+=count;
  $('row-count').textContent=confirmed+' 段已送入編輯頁';
  if(location.hash!=='#editor' && unread) $('new-count').textContent='+'+unread;
  queueSave();
}
frame.addEventListener('load',()=>{ if(pendingRows.length){const rows=pendingRows;pendingRows=[];append(rows);} });
async function check() {
  try {
    const status=await api('status');
    $('model').replaceChildren(...status.models.map(name=>new Option(name,name)));
    $('model').value=status.models.includes('small')?'small':(status.models[0]||'');
    $('model').dataset.ready=status.installed && status.models.length?'yes':'';
    $('readiness').textContent=!status.installed?'尚未安裝相符版本，請先執行 DeployLive.cmd。':!status.models.length?'找不到完整本機模型，請先執行 DeployLive.cmd。':status.busy?'另一項轉錄正在執行，開始收音時會再次檢查。':'本機套件與模型已備妥。按下開始後才會使用麥克風。';
    controls();
  } catch(e){error(e.message);}
}
async function refreshSessions() {
  try { const records=await api('sessions'); $('sessions').replaceChildren(new Option('選擇先前的工作',''), ...records.map(s=>new Option(s.created+' · '+s.model+' · '+(s.status==='completed'?'已結束':'中斷／未結束'),s.id))); }
  catch(e){error(e.message);}
}
async function releaseMicrophone() {
  source?.disconnect();worklet?.disconnect();
  if(media) media.getTracks().forEach(track=>{track.onended=null;track.stop();});
  if(context && context.state!=='closed') await context.close();
  media=null;context=null;source=null;worklet=null;$('level').value=0;
}
async function stop() {
  if(!busy || stopping) return; stopping=true;controls();phase('停止收音，正在處理最後一句…');
  if(worklet) {
    await Promise.race([new Promise(resolve=>{flushResolve=resolve;worklet.port.postMessage('stop');}),new Promise(resolve=>setTimeout(resolve,1500))]);
  }
  await releaseMicrophone();
  if(ws?.readyState===WebSocket.OPEN && micWasReady) ws.send('stop');
  else ws?.close();
  await save();
}
async function beginAudio() {
  await context.audioWorklet.addModule('/live/assets/capture-worklet.js');
  source=context.createMediaStreamSource(media); worklet=new AudioWorkletNode(context,'local-capture');
  worklet.port.onmessage=event=>{
    if(event.data.type==='flushed'){flushResolve?.();flushResolve=null;return;}
    if(event.data.type==='level'){$('level').value=Math.min(1,event.data.value*4);return;}
    if(event.data.type==='audio' && ws?.readyState===WebSocket.OPEN) {
      if(ws.bufferedAmount>320000){error('音訊傳送落後，已停止收音。請確認電腦負載，再重新開始。');stop();return;}
      ws.send(event.data.data);samples+=event.data.data.byteLength/2;
      $('elapsed').textContent=new Date(Math.floor(samples/16000)*1000).toISOString().slice(11,19);
    }
  };
  source.connect(worklet);worklet.connect(context.destination);await context.resume();
  if(context.state!=='running') throw new Error('瀏覽器未啟用收音，請停止後重新開始。');
  media.getTracks().forEach(track=>track.onended=()=>{error('麥克風已中斷。');stop();});
}
async function start() {
  error('');if(!bridge()){error('文字稿工具尚未載入，請稍候再試。');return;}
  if(sessionId && bridge().snapshot().text && !confirm('要建立新的收音文字稿嗎？現有內容儲存成功後才會開始，新場次不會覆蓋舊檔。')) return;
  if(!await protectCurrent()) return;
  busy=true;stopping=false;micWasReady=false;controls();phase('等待麥克風授權…');
  try {
    media=await navigator.mediaDevices.getUserMedia({audio:{deviceId:$('microphone').value?{exact:$('microphone').value}:undefined,channelCount:1,echoCancellation:true,noiseSuppression:true},video:false});
    context=new AudioContext({sampleRate:16000});
    if(context.sampleRate!==16000) throw new Error('瀏覽器不支援 16 kHz 收音，請使用最新版 Edge 或 Chrome。');
    // Resume during the explicit user action, then wait for the local model.
    await context.resume();
    sessionId='';lastSaved='';samples=0;confirmed=0;unread=0;pendingRows=[];
    bridge().reset();$('elapsed').textContent='00:00:00';$('row-count').textContent='0 段已送入編輯頁';
    $('preview').textContent='正在載入本機模型，備妥後才開始送入音訊…';phase('正在載入本機模型…');
    ws=new WebSocket('ws://'+location.host+'/live/ws');
    ws.onopen=()=>ws.send(JSON.stringify({token,model:$('model').value,language:$('language').value,record_audio:$('record-audio').checked}));
    ws.onmessage=async event=>{
      try {
        const message=JSON.parse(event.data);
        if(message.type==='session'){sessionId=message.id;$('save-status').textContent='已建立本機工作';}
        else if(message.type==='ready'){
          if(stopping){ws.send('stop');return;}
          micWasReady=true;await beginAudio();phase('收音中 · '+message.device+' / '+message.compute_type);
          $('preview').textContent='正在聆聽，確認後的文字會自動進入編輯頁。';
        } else if(message.type==='transcript'){
          append(message.rows||[]);
          if(message.preview) $('preview').textContent=message.preview;
          else if(message.rows?.length) $('preview').textContent=message.rows.at(-1).text;
          $('lag').textContent='尚待辨識的音訊約 '+Number(message.lag||0).toFixed(1)+' 秒';
        } else if(message.type==='done'){
          busy=false;stopping=false;phase('收音已結束');controls();await releaseMicrophone();await save();await refreshSessions();
        } else if(message.type==='error'){error(message.message);phase('收音已中斷');await releaseMicrophone();ws.close();}
      } catch(e){error(e.message);await stop();}
    };
    ws.onerror=()=>error('無法連上本機辨識服務。請確認工作台仍在執行。');
    ws.onclose=async()=>{await releaseMicrophone();if(busy){phase('收音已中斷');error($('error').textContent || '連線已結束。請確認最後一句是否完整，已確認的文字仍保留。');}busy=false;stopping=false;controls();await save();await refreshSessions();};
  } catch(e){await releaseMicrophone();busy=false;stopping=false;controls();phase('尚未收音');error(e.name==='NotAllowedError'?'麥克風未獲授權，請在瀏覽器允許此本機網頁使用麥克風。':e.message);}
}
$('start').addEventListener('click',start);$('stop').addEventListener('click',stop);$('save-now').addEventListener('click',save);
$('recheck').addEventListener('click',check);$('refresh-sessions').addEventListener('click',refreshSessions);
$('load-session').addEventListener('click',async()=>{
  const id=$('sessions').value;if(!id || busy || !bridge())return;
  try {
    if(!await protectCurrent()) return;
    const data=await api('sessions/'+id);sessionId=id;lastSaved='';confirmed=(data.edited?.seen||[]).length;unread=0;
    bridge().reset(data.edited?.text||'',data.edited?.seen||[]);append(data.rows||[]);location.hash='#editor';
    $('save-status').textContent='已載入本機文字稿';await save();
  } catch(e){error(e.message);}
});
window.addEventListener('beforeunload',event=>{
  if(busy || (bridge() && (sessionId ? JSON.stringify(bridge().snapshot())!==lastSaved : bridge().snapshot().text))){event.preventDefault();event.returnValue='';}
});
$('files-link').addEventListener('click',event=>{if(busy){event.preventDefault();error('收音仍在進行。請先停止收音，再前往音檔轉錄。');}});
if(navigator.mediaDevices?.enumerateDevices) navigator.mediaDevices.enumerateDevices().then(devices=>{
  for(const device of devices.filter(d=>d.kind==='audioinput' && d.deviceId && d.deviceId!=='default')) $('microphone').add(new Option(device.label||'麥克風 '+($('microphone').length),device.deviceId));
}).catch(()=>{});
check();refreshSessions();
