'use strict';
const visionState = {tab:'upload',jobs:[],assets:[],selected:null,samples:[],status:null,folder:'',root:'examples',
  poll:null,polling:false,stream:null,recording:false,uploading:false,recorder:null,frameTimer:null,
  cameraJob:null,captureMode:'manual',uploadQueue:Promise.resolve(),cameraError:null,selectionKey:null,drawSample:null};
const visionStatus = {queued:'En cola',running:'Analizando',capturing:'Capturando',finalizing:'Finalizando',completed:'Terminado',failed:'Incidencia',cancelled:'Cancelado'};
const visionActive = j => !['completed','failed','cancelled'].includes(j.status);
const visionBytes = n => n==null?'Grabación':n<1024**2?number(n/1024,1)+' KiB':n<1024**3?number(n/1024**2,1)+' MiB':number(n/1024**3,2)+' GiB';
const visionSeconds = n => number(n||0,2)+' s';
const visionHere = () => state.user && state.view==='vision' && $('#vision-lab');
const visionVideoUrl = job => '/api/v1/vision/jobs/'+encodeURIComponent(job.job_id)+'/video'+
  (!document.createElement('video').canPlayType('video/mp4;codecs="avc1.42E01E"')&&job.preview_webm_path?'?format=webm':'');

async function visionRequest(path,options={}) {
  const response=await fetch('/api/v1/vision'+path,{credentials:'same-origin',...options,
    headers:{...(options.body&&typeof options.body==='string'?{'Content-Type':'application/json'}:{}),...(options.headers||{})}});
  if(!response.ok){let detail;try{detail=(await response.json()).detail;}catch{detail=response.statusText;}
    throw new Error(typeof detail==='string'?detail:JSON.stringify(detail));}
  return response.json();
}
function visionOptions(){return {sample_fps:Number($('#vision-fps')?.value||5),confidence:Number($('#vision-confidence')?.value||.5),
  operator_id:$('#vision-operator')?.value||null,name:$('#vision-name')?.value.trim()||undefined};}
async function visionPage(){
  if(!admin())return empty('Acceso de administración','Los originales y las pruebas de cámara están reservados a administradores.');
  [visionState.jobs,visionState.assets,visionState.status]=await Promise.all([visionRequest('/jobs'),visionRequest('/assets'),visionRequest('/status')]);
  if(!visionState.jobs.some(j=>j.job_id===visionState.selected))visionState.selected=visionState.jobs[0]?.job_id||null;
  visionState.selectionKey=null;
  return `<div id='vision-lab'><div class='vision-intro'><div><span class='chip outline'>PRUEBAS CON IMAGEN REAL</span><h2>De la imagen a la postura</h2><p>Importa un clip o abre tu cámara. Explora cada movimiento junto a sus indicadores ergonómicos.</p></div><div id='vision-engine'>${visionEngine()}</div></div>
  <section class='panel vision-input'><div class='panel-head'><div><h2>Nuevo análisis</h2><p>Los originales se conservan como estudios hasta que los elimines.</p></div><div class='segmented vision-tabs'>${[['upload','Subir vídeos'],['server','Vídeos del servidor'],['camera','Cámara USB']].map(([id,label])=>`<button type='button' data-vision-tab='${id}' class='${visionState.tab===id?'selected':''}'>${label}</button>`).join('')}</div></div>
  <div class='vision-settings'><label class='field'>Nombre del análisis<input id='vision-name' placeholder='Ej. Recogida y acabado de pieza' maxlength='200'></label><label class='field'>Operario<select id='vision-operator'><option value=''>Laboratorio · sin asignar</option>${state.operators.filter(o=>!o.laboratory).map(o=>`<option value='${esc(o.operator_id)}'>${esc(o.display_name)}</option>`).join('')}</select></label><label class='field'>Fotogramas a analizar<select id='vision-fps'>${[1,2,5,10,15,25].map(n=>`<option value='${n}' ${n===5?'selected':''}>${n} por segundo</option>`).join('')}</select></label><label class='field'>Confianza mínima<select id='vision-confidence'>${[.5,.6,.7,.8,.9].map(n=>`<option value='${n}'>${number(n*100)} %</option>`).join('')}</select></label></div>
  <div id='vision-source-panel'></div><div id='vision-upload-status' class='vision-transfer' role='status' aria-live='polite'></div></section>
  <section id='vision-pending' class='panel' ${visionPendingAssets().length?'':'hidden'}>${visionPending()}</section>
  <div class='vision-workspace'><section class='panel vision-history'><div class='panel-head'><div><h2>Análisis guardados</h2><p>Cola y resultados</p></div><button class='icon-btn' id='vision-refresh' aria-label='Actualizar análisis'>${icon('refresh')}</button></div><div id='vision-jobs-list'>${visionJobs()}</div><details class='vision-library'><summary>Vídeos subidos e importados</summary><div id='vision-assets-list'>${visionAssets()}</div></details></section><div id='vision-detail'></div></div></div>`;
}
function visionEngine(){const w=visionState.status?.worker;return `<div class='vision-engine-mark'><span class='dot ${w?.healthy?'':'offline'}'></span><strong>${w?.healthy?'GPU preparada':w?.status==='loading'?'Cargando modelos':'GPU sin confirmar'}</strong></div><small>${esc(w?.gpu||'RTX 4090 · procesamiento en el servidor')}</small>${w?.error?`<p class='vision-error'>${esc(w.error)}</p>`:''}`;}
function visionJobs(){return visionState.jobs.length?visionState.jobs.map(j=>`<button class='vision-job ${j.job_id===visionState.selected?'selected':''}' data-vision-job='${esc(j.job_id)}'><span class='vision-job-top'><strong>${esc(j.name)}</strong>${chip(visionStatus[j.status]||j.status,j.status==='failed'?'red':j.status==='completed'?'green':'outline')}</span><span>${date(j.created_at,true)} · ${number(j.processed_frames)} frames</span>${visionActive(j)?`<progress max='1' value='${j.progress||0}' aria-label='Progreso de ${esc(j.name)}'></progress>`:''}</button>`).join(''):empty('Tu primera prueba empieza aquí','Sube un vídeo o selecciona uno de examples.');}
function visionAssets(){return visionState.assets.length?visionState.assets.map(a=>`<div class='vision-asset'><div><strong>${esc(a.name)}</strong><small>${a.source==='server'?(a.root==='project'?'Referencia de POSTURE':'Referencia de examples'):'Subida del cliente'} · ${visionBytes(a.size_bytes)} · ${a.status==='ready'?'Guardado':'Subida incompleta'}</small></div><div class='actions'>${a.status==='ready'?`<button class='btn small' data-vision-analyze='${esc(a.asset_id)}'>Analizar</button>`:''}<button class='btn small danger' data-vision-delete-asset='${esc(a.asset_id)}' aria-label='Eliminar vídeo ${esc(a.name)}'>${icon('close')}</button></div></div>`).join(''):`<p class='subtitle'>Todavía no hay vídeos.</p>`;}

function visionPendingAssets(){return visionState.assets.filter(a=>a.status==='ready'&&a.capture?.mode==='manual'&&!a.analysis_requested_at);}
function visionPending(){return `<div class='panel-head'><div><h2>Capturas pendientes de análisis</h2><p>Originales guardados. No se ha calculado pose ni métricas.</p></div></div>`+visionPendingAssets().map(a=>`<div class='vision-asset'><div><strong>${esc(a.capture.analysis_options.name||a.name)}</strong><small>${date(a.created_at,true)} · ${visionBytes(a.size_bytes)}</small></div><button class='btn primary small' data-vision-analyze='${esc(a.asset_id)}'>Procesar secuencia</button></div>`).join('');}

function visionUploadPanel(){return `<div class='vision-upload-box'><div class='vision-upload-symbol'>${icon('download')}</div><h3>Vídeos desde tu equipo</h3><p>MP4, MOV, MKV, AVI, WebM o M4V · hasta 2 GiB por vídeo</p><div class='actions'><label class='btn primary'>Seleccionar vídeos<input id='vision-file-input' type='file' accept='video/*,.mkv,.avi,.m4v' multiple hidden></label><label class='btn'>Seleccionar carpeta<input id='vision-folder-input' type='file' webkitdirectory multiple hidden></label></div><p class='hint'>Cada vídeo de la carpeta genera un análisis independiente. El archivo original se guarda en POSTURE/data/vision/uploads/.</p></div>`;}
async function visionSource(){
  const panel=$('#vision-source-panel');if(!panel)return;
  if(visionState.tab==='upload'){
    panel.innerHTML=visionUploadPanel();
    ['#vision-file-input','#vision-folder-input'].forEach(id=>$(id).onchange=e=>visionUploadFiles([...e.target.files]));
  }else if(visionState.tab==='server'){
    panel.innerHTML=`<label class='field'>Ubicación del servidor<select id='vision-server-root'><option value='examples' ${visionState.root==='examples'?'selected':''}>POSTURE/examples</option><option value='project' ${visionState.root==='project'?'selected':''}>POSTURE · carpeta del proyecto</option></select></label><p class='subtitle'>Carpeta del servidor: <strong>POSTURE/${visionState.root==='examples'?'examples/':''}${esc(visionState.folder)}</strong></p><div class='actions vision-server-actions'><button class='btn small' id='vision-folder-up'>Subir un nivel</button><button class='btn small primary' id='vision-folder-analyze'>Analizar todos los vídeos de esta carpeta</button></div><div id='vision-server-files'>Cargando archivos…</div>`;
    $('#vision-server-root').onchange=e=>{visionState.root=e.target.value;visionState.folder='';visionSource().catch(error=>toast(error.message));};
    $('#vision-folder-up').onclick=()=>{visionState.folder=visionState.folder.split('/').slice(0,-1).join('/');visionSource().catch(e=>toast(e.message));};
    $('#vision-folder-analyze').onclick=()=>visionAnalyzeFolder();
    const listing=await visionRequest('/files?root='+visionState.root+'&path='+encodeURIComponent(visionState.folder));
    if(!$('#vision-server-files'))return;
    $('#vision-server-files').innerHTML=listing.entries.length?listing.entries.map(f=>`<div class='vision-server-file'><span><strong>${esc(f.name)}</strong><small>${f.kind==='folder'?'Carpeta':visionBytes(f.size_bytes)}</small></span><button class='btn small' ${f.kind==='folder'?`data-vision-folder='${esc(f.path)}'`:`data-vision-import='${esc(f.path)}'`}>${f.kind==='folder'?'Abrir':'Analizar vídeo'}</button></div>`).join(''):`<div class='vision-folder-empty'>No hay vídeos aquí. Puedes copiar tus clips a <strong>POSTURE/examples/videos/</strong> y abrir esa carpeta.</div>`;
    panel.querySelectorAll('[data-vision-folder]').forEach(b=>b.onclick=()=>{visionState.folder=b.dataset.visionFolder;visionSource().catch(e=>toast(e.message));});
    panel.querySelectorAll('[data-vision-import]').forEach(b=>b.onclick=()=>visionImportAndAnalyze(b.dataset.visionImport));
  }else{
    const secure=window.isSecureContext&&navigator.mediaDevices?.getUserMedia;
    panel.innerHTML=`${!secure?`<div class='vision-https'><h3>Activa el acceso seguro para usar la cámara</h3><p>Instala el certificado de confianza de POSTURE en este equipo y abre la dirección HTTPS. La subida de vídeos funciona con la conexión actual.</p><div class='actions'><a class='btn' href='/api/v1/vision/certificate'>Descargar certificado público</a><a class='btn primary' href='${esc(visionState.status.https_url)}'>Abrir POSTURE con HTTPS ${icon('arrow')}</a></div><details><summary>Cómo confiar en el certificado</summary><p>Windows: importar en «Entidades de certificación raíz de confianza» del usuario. macOS: importar en Acceso a Llaveros y marcar «Confiar siempre». Linux: importar como autoridad en el navegador o instalarlo en el almacén del sistema. Después reinicia el navegador. Consulta docs/CAMERA_HTTPS.md para los pasos completos.</p></details></div>`:''}
<div class='vision-camera-grid'><div class='vision-camera-preview'><video id='vision-camera-video' autoplay muted playsinline aria-label='Vista previa de la cámara del cliente'></video><span id='vision-camera-badge'>Cámara apagada</span></div><div class='vision-camera-controls'><label class='field'>Dispositivo<select id='vision-camera-device'><option value=''>Cámara predeterminada</option></select></label><label class='field'>Modo de captura<select id='vision-camera-mode'>${[['manual','Solo capturar · procesar cuando lo indique'],['live','Procesar mientras se captura'],['record','Procesar al finalizar la captura']].map(([value,label])=>`<option value='${value}' ${visionState.captureMode===value?'selected':''}>${label}</option>`).join('')}</select></label><div class='actions'><button class='btn' id='vision-open-camera' ${secure?'':'disabled'}>Abrir cámara</button><button class='btn primary' id='vision-start-camera' disabled>Grabar</button><button class='btn danger' id='vision-stop-camera' disabled>Detener y guardar</button></div><p class='hint'>Por defecto solo se guarda el vídeo, sin calcular pose ni métricas. Puedes procesarlo después desde «Capturas pendientes de análisis». El vídeo se guarda sin audio. El análisis en directo muestra el último fotograma procesado con su propia pose y métricas, aunque llegue con retraso.</p><p class='vision-error' id='vision-camera-error' role='alert'></p></div></div>`;
    $('#vision-open-camera').onclick=()=>visionOpenCamera().catch(e=>{if($('#vision-camera-error'))$('#vision-camera-error').textContent=e.message;});
    $('#vision-start-camera').onclick=()=>visionStartCamera().catch(e=>visionCameraFailure(e));
    $('#vision-stop-camera').onclick=()=>visionStopCamera().catch(e=>visionCameraFailure(e));
    $('#vision-camera-device').onchange=()=>visionOpenCamera().catch(e=>toast(e.message));
    $('#vision-camera-mode').onchange=e=>{visionState.captureMode=e.target.value;};
    if(visionState.stream){$('#vision-camera-video').srcObject=visionState.stream;$('#vision-start-camera').disabled=false;}
  }
}

async function visionNewJob(asset,options=visionOptions(),mode='file'){
  const job=await visionRequest('/jobs',{method:'POST',body:JSON.stringify({...options,asset_id:asset.asset_id,mode})});
  visionState.selected=job.job_id;visionState.selectionKey=null;visionState.samples=[];
  return job;
}
async function visionPutBlob(asset,blob,offset=0,progress){
  const chunkSize=4*1024**2;
  for(let i=0;i<blob.size;i+=chunkSize){
    const chunk=blob.slice(i,Math.min(blob.size,i+chunkSize));
    const value=await visionRequest('/uploads/'+asset.asset_id+'?offset='+(offset+i),{method:'PUT',headers:{'Content-Type':'application/octet-stream'},body:chunk});
    if(progress)progress(value.uploaded_bytes);
  }
  return offset+blob.size;
}
function visionTransfer(text,fraction){const box=$('#vision-upload-status');if(box)box.innerHTML=`<span>${esc(text)}</span>${fraction!=null?`<progress max='1' value='${fraction}' aria-label='Progreso de subida'></progress>`:''}`;}
async function visionUploadFiles(files){
  if(visionState.uploading||visionState.recording){toast('Termina la operación actual antes de iniciar otra subida.');return;}
  const allowed=visionState.status.allowed_extensions;
  const videos=files.filter(f=>allowed.includes('.'+f.name.split('.').at(-1).toLowerCase()));
  if(!videos.length){toast('La selección no contiene vídeos compatibles.');return;}
  const opts=visionOptions();visionState.uploading=true;
  let completed=0;
  try{
    for(const file of videos){
      if(file.size>visionState.status.max_video_bytes)throw new Error(file.name+': supera el límite de 2 GiB.');
      const asset=await visionRequest('/uploads',{method:'POST',body:JSON.stringify({name:file.name,size_bytes:file.size})});
      await visionPutBlob(asset,file,0,n=>visionTransfer(`Subiendo ${completed+1}/${videos.length} · ${file.name} · ${visionBytes(n)} / ${visionBytes(file.size)}`,n/file.size));
      const ready=await visionRequest('/uploads/'+asset.asset_id+'/complete',{method:'POST'});
      await visionNewJob(ready,{...opts,name:opts.name?(videos.length>1?opts.name+' · '+file.name:opts.name):file.name});
      completed++;await visionRefresh();
    }
    visionTransfer(`${completed} vídeo${completed===1?'':'s'} guardado${completed===1?'':'s'}. El análisis continúa en el servidor.`);
  }catch(e){visionTransfer('Subida interrumpida: '+e.message);toast(e.message);}
  finally{visionState.uploading=false;await visionRefresh();}
}
async function visionImportAndAnalyze(path,opts=visionOptions()){
  try{const asset=await visionRequest('/import',{method:'POST',body:JSON.stringify({root:visionState.root,path})});await visionNewJob(asset,opts);await visionRefresh();toast('Vídeo añadido a la cola de análisis.');}
  catch(e){toast(e.message);}
}
async function visionAnalyzeFolder(){
  if(visionState.uploading||visionState.recording){toast('Termina la operación actual.');return;}
  visionState.uploading=true;const opts=visionOptions();
  try{const listing=await visionRequest('/files?root='+visionState.root+'&recursive=true&path='+encodeURIComponent(visionState.folder));
    const videos=listing.entries.filter(f=>f.kind==='video');
    if(!videos.length){toast('No hay vídeos en esta carpeta.');return;}
    for(const f of videos){const asset=await visionRequest('/import',{method:'POST',body:JSON.stringify({root:visionState.root,path:f.path})});await visionNewJob(asset,{...opts,name:opts.name?opts.name+' · '+f.name:f.name});}
    visionTransfer(videos.length+' vídeos añadidos a la cola.');await visionRefresh();
  }catch(e){toast(e.message);}finally{visionState.uploading=false;}
}

async function visionOpenCamera(){
  if(visionState.recording)return;
  if(visionState.stream)visionState.stream.getTracks().forEach(t=>t.stop());
  const device=$('#vision-camera-device').value;
  visionState.stream=await navigator.mediaDevices.getUserMedia({audio:false,video:{width:{ideal:1920},height:{ideal:1080},frameRate:{ideal:25,max:25},...(device?{deviceId:{exact:device}}:{})}});
  $('#vision-camera-video').srcObject=visionState.stream;
  await $('#vision-camera-video').play();
  const current=visionState.stream.getVideoTracks()[0].getSettings().deviceId;
  const devices=await navigator.mediaDevices.enumerateDevices();
  $('#vision-camera-device').innerHTML=devices.filter(d=>d.kind==='videoinput').map(d=>`<option value='${esc(d.deviceId)}' ${d.deviceId===current?'selected':''}>${esc(d.label||'Cámara USB')}</option>`).join('');
  $('#vision-start-camera').disabled=false;$('#vision-camera-badge').textContent='Vista previa · sin grabar';$('#vision-camera-error').textContent='';
}
async function visionStartCamera(){
  if(visionState.recording||visionState.saving||visionState.uploading||!visionState.stream)return;
  if(!window.MediaRecorder)throw new Error('Este navegador no permite grabar vídeo. Prueba con una versión reciente de Chrome, Edge o Firefox.');
  const mime=['video/webm;codecs=vp8','video/webm;codecs=vp9','video/webm','video/mp4'].find(m=>MediaRecorder.isTypeSupported(m));
  if(!mime)throw new Error('No hay un formato de grabación compatible.');
  const opts={...visionOptions(),capture_fps:visionState.stream.getVideoTracks()[0].getSettings().frameRate||25},mode=$('#vision-camera-mode').value;
  const name='camara-'+new Date().toISOString().replace(/[:.]/g,'-')+(mime.includes('mp4')?'.mp4':'.webm');
  const asset=await visionRequest('/uploads',{method:'POST',body:JSON.stringify({name,capture:{mode,analysis_options:opts}})});
  const job=mode==='live'?await visionNewJob(asset,opts,'live'):null;
  visionState.cameraAsset=asset;visionState.cameraJob=job;visionState.cameraOptions=opts;visionState.cameraMode=mode;
  visionState.cameraBytes=0;visionState.cameraError=null;visionState.uploadQueue=Promise.resolve();
  visionState.frameSequence=0;visionState.frameInFlight=false;visionState.framePromise=null;visionState.cameraStart=performance.now();visionState.recording=true;
  const recorder=new MediaRecorder(visionState.stream,{mimeType:mime,videoBitsPerSecond:6000000});
  visionState.recorder=recorder;
  visionState.recorderStopped=new Promise(resolve=>recorder.addEventListener('stop',resolve,{once:true}));
  recorder.ondataavailable=e=>{
    if(!e.data.size)return;
    visionState.uploadQueue=visionState.uploadQueue.then(async()=>{
      if(visionState.cameraError)return;
      visionState.cameraBytes=await visionPutBlob(asset,e.data,visionState.cameraBytes);
      visionTransfer('Grabando · '+visionSeconds((performance.now()-visionState.cameraStart)/1000)+' · '+visionBytes(visionState.cameraBytes)+' guardados');
    }).catch(error=>{visionState.cameraError=error;if(visionState.recording)visionStopCamera().catch(visionCameraFailure);});
  };
  recorder.onerror=e=>{visionState.cameraError=e.error||new Error('Error de grabación');visionStopCamera().catch(visionCameraFailure);};
  recorder.start(1000);
  $('#vision-start-camera').disabled=true;$('#vision-open-camera').disabled=true;$('#vision-stop-camera').disabled=false;
  $('#vision-camera-device').disabled=true;$('#vision-camera-mode').disabled=true;$('#vision-camera-badge').textContent=mode==='live'?'REC · análisis en curso':mode==='record'?'REC · análisis al terminar':'REC · solo captura, sin análisis';
  if(job){visionState.frameTimer=setInterval(()=>{if(!visionState.frameInFlight)visionState.framePromise=visionCaptureFrame().catch(error=>{if($('#vision-camera-error'))$('#vision-camera-error').textContent=error.message;});},1000/opts.sample_fps);visionState.framePromise=visionCaptureFrame();await visionState.framePromise;}
  await visionRefresh();
}
async function visionCaptureFrame(){
  if(!visionState.recording||visionState.frameInFlight||!visionState.cameraJob)return;
  const video=$('#vision-camera-video');if(!video?.videoWidth)return;
  visionState.frameInFlight=true;
  try{
    const canvas=document.createElement('canvas');canvas.width=1920;canvas.height=1080;
    const ctx=canvas.getContext('2d');ctx.fillStyle='#000';ctx.fillRect(0,0,1920,1080);
    const scale=Math.min(1920/video.videoWidth,1080/video.videoHeight),w=Math.round(video.videoWidth*scale),h=Math.round(video.videoHeight*scale);
    ctx.drawImage(video,(1920-w)/2,(1080-h)/2,w,h);
    const offset=(performance.now()-visionState.cameraStart)/1000;
    const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/jpeg',.8));
    const sequence=visionState.frameSequence++;
    const response=await fetch('/api/v1/vision/jobs/'+visionState.cameraJob.job_id+'/frames/'+sequence+'?offset_s='+offset.toFixed(6),{method:'PUT',credentials:'same-origin',headers:{'Content-Type':'image/jpeg'},body:blob});
    if(!response.ok&&response.status!==429){const data=await response.json();throw new Error(typeof data.detail==='string'?data.detail:'Error al enviar la captura.');}
  }finally{visionState.frameInFlight=false;}
}
async function visionStopCamera(){
  if(!visionState.recording)return;
  visionState.saving=true;
  visionState.recording=false;clearInterval(visionState.frameTimer);visionState.frameTimer=null;
  $('#vision-stop-camera').disabled=true;
  if(visionState.recorder.state!=='inactive')visionState.recorder.stop();
  await visionState.recorderStopped;
  await visionState.uploadQueue;
  await visionState.framePromise;
  if(visionState.cameraError)throw visionState.cameraError;
  await visionRequest('/uploads/'+visionState.cameraAsset.asset_id+'/complete',{method:'POST'});
  if(visionState.cameraJob)await visionRequest('/jobs/'+visionState.cameraJob.job_id+'/finish',{method:'POST'});
  else if(visionState.cameraMode==='record')await visionNewJob(visionState.cameraAsset,visionState.cameraOptions);
  visionState.cameraJob=null;
  if($('#vision-camera-badge'))$('#vision-camera-badge').textContent='Grabación guardada';
  if($('#vision-start-camera'))$('#vision-start-camera').disabled=false;
  if($('#vision-open-camera'))$('#vision-open-camera').disabled=false;
  if($('#vision-camera-device'))$('#vision-camera-device').disabled=false;
  if($('#vision-camera-mode'))$('#vision-camera-mode').disabled=false;
  visionState.saving=false;
  visionTransfer(visionState.cameraMode==='manual'?'Vídeo guardado sin análisis. Pulsa «Procesar secuencia» cuando quieras calcular la pose y las métricas.':'Vídeo original guardado. Preparando reproducción y resultados.');await visionRefresh();
}
function visionCameraFailure(error){
  visionState.saving=false;
  visionState.recording=false;clearInterval(visionState.frameTimer);
  if(visionState.recorder?.state==='recording')visionState.recorder.stop();
  if(visionState.cameraJob)visionRequest('/jobs/'+visionState.cameraJob.job_id+'/cancel',{method:'POST'}).catch(()=>{});
  if($('#vision-camera-error'))$('#vision-camera-error').textContent=error.message;
  if($('#vision-open-camera'))$('#vision-open-camera').disabled=false;
  if($('#vision-start-camera'))$('#vision-start-camera').disabled=false;
  if($('#vision-stop-camera'))$('#vision-stop-camera').disabled=true;
  if($('#vision-camera-device'))$('#vision-camera-device').disabled=false;
  if($('#vision-camera-mode'))$('#vision-camera-mode').disabled=false;
  toast('La grabación necesita revisión: '+error.message);
}

function visionDetail(job){
  if(!job)return `<section class='panel vision-empty-result'>${empty('Ver el movimiento, entender la postura','Selecciona un análisis o crea una prueba para explorar aquí sus resultados.')}</section>`;
  const id=encodeURIComponent(job.job_id);
  return `<section class='panel vision-result'><div class='panel-head'><div><h2>${esc(job.name)}</h2><p id='vision-job-stage'>${esc(job.stage)}</p></div><div class='actions'><button class='btn small' id='vision-reprocess'>Volver a analizar</button><button class='btn small danger' id='vision-delete-job'>Eliminar análisis</button></div></div>
  <div class='vision-job-state'><span id='vision-job-state'>${chip(visionStatus[job.status]||job.status,job.status==='failed'?'red':'outline')}</span><progress id='vision-job-progress' max='1' value='${job.progress||0}' aria-label='Progreso del análisis'></progress><span id='vision-job-count'>${number(job.processed_frames)} frames</span><button class='btn small' id='vision-cancel-job' ${visionActive(job)?'':'hidden'}>Cancelar</button></div>
  <p id='vision-job-error' class='vision-error' role='alert'>${esc(job.error||'')}</p>
  <div class='vision-player'><video id='vision-result-video' ${job.preview_path?`src='${visionVideoUrl(job)}'`:''} controls playsinline preload='metadata' aria-label='Vídeo de estudio sincronizado con la pose' ${job.preview_path?'':'hidden'}></video><img id='vision-result-frame' alt='Último fotograma analizado' hidden><div id='vision-video-placeholder' ${job.preview_path?'hidden':''}>${icon('studies')}<p>${job.mode==='live'?'Los fotogramas analizados aparecerán aquí.':'La reproducción estará disponible al terminar el análisis.'}</p></div><canvas id='vision-overlay' aria-label='Esqueleto inferido sobre el fotograma'></canvas></div>
  <div class='vision-player-meta'><span id='vision-frame-position'>Sin fotograma</span><label><input id='vision-show-pose' type='checkbox' checked> Mostrar esqueleto</label></div>
  <div id='vision-frame-metrics'></div><div id='vision-summary' class='vision-summary'></div>
  <div class='vision-chart'><div class='legend'><span><i></i>RULA</span><span><i class='orange'></i>REBA</span></div><div id='vision-score-chart'></div></div>
  <div class='actions vision-exports'><a class='btn small' href='/api/v1/vision/jobs/${id}/export.csv'>${icon('download')} Métricas CSV</a><a class='btn small' href='/api/v1/vision/jobs/${id}/export.json'>Pose y métricas JSON</a><a class='btn small' href='/api/v1/vision/jobs/${id}/original'>Vídeo original</a><a class='btn small' href='#session/${esc(job.session_id)}'>Ver sesión</a></div>
  <details class='accordion'><summary>Modelo, contexto y límites de la evaluación</summary><p class='subtitle'>RTMW-x · 133 puntos · CUDA. Se adapta al contrato de 33 puntos; las articulaciones no observadas quedan ausentes. Selección de la persona de mayor tamaño entre detecciones con confianza suficiente. Normalización a 1920×1080 sin deformar la imagen. El tiempo corresponde a la posición dentro del vídeo; no acredita la fecha real de grabación.</p><p class='subtitle'>Pose proyectada 2D. La profundidad y SMPL todavía no están activados. Las puntuaciones son preliminares y dependen de los supuestos de carga, agarre y apoyos.</p><div id='vision-assumptions'></div><pre class='code-box'>${esc(JSON.stringify({options:job.options,context:job.context,model_manifest:job.model_manifest||null},null,2))}</pre></details></section>`;
}
function visionPlot(){
  const samples=visionState.samples;if(!samples.length)return `<p class='subtitle'>Esperando resultados de detección.</p>`;
  const end=Math.max(.1,samples.at(-1).offset_s),x=t=>35+t/end*645,y=v=>145-v/15*125;
  const step=Math.max(1,Math.ceil(samples.length/1200));
  function line(key,color){let segments=[],part=[];samples.filter((_,i)=>i%step===0||i===samples.length-1).forEach(s=>{const v=s.metrics[key];if(v==null){if(part.length)segments.push(part.join(' '));part=[];}else part.push(`${x(s.offset_s).toFixed(2)},${y(v).toFixed(2)}`);});if(part.length)segments.push(part.join(' '));return segments.map(p=>`<polyline points='${p}' fill='none' stroke='${color}' stroke-width='2'/>`).join('');}
  return `<svg class='chart' viewBox='0 0 700 175' role='img' aria-label='RULA y REBA a lo largo del vídeo'>${[0,5,10,15].map(v=>`<path d='M35 ${y(v)}H680' stroke='#e1e7e2'/><text x='8' y='${y(v)+4}'>${v}</text>`).join('')}${line('rula','#1d6c5c')}${line('reba','#d7a05a')}<text x='35' y='168'>0 s</text><text x='625' y='168'>${number(end,1)} s</text></svg>`;
}
function visionDraw(row){
  const canvas=$('#vision-overlay');if(!canvas)return;
  canvas.width=1920;canvas.height=1080;const ctx=canvas.getContext('2d');ctx.clearRect(0,0,1920,1080);
  if(!row||!$('#vision-show-pose')?.checked)return;
  const p=row.keypoints,s=row.scores,cut=visionState.jobs.find(j=>j.job_id===visionState.selected)?.options.confidence||.5;
  const edges=[[0,1],[0,2],[1,3],[2,4],[5,6],[5,7],[7,9],[6,8],[8,10],[5,11],[6,12],[11,12],[11,13],[13,15],[12,14],[14,16],[15,17],[15,19],[16,20],[16,22]];
  for(const base of [91,112])for(let finger=0;finger<5;finger++){edges.push([base,base+1+finger*4]);for(let j=0;j<3;j++)edges.push([base+1+finger*4+j,base+2+finger*4+j]);}
  ctx.lineCap='round';ctx.lineJoin='round';
  for(const [a,b] of edges){if(!p[a]||!p[b]||s[a]<cut||s[b]<cut)continue;ctx.strokeStyle=a>=91?'#ffcf78':'#c9ff9c';ctx.lineWidth=a>=91?3:5;ctx.beginPath();ctx.moveTo(...p[a]);ctx.lineTo(...p[b]);ctx.stroke();}
  p.forEach((point,i)=>{if(s[i]<cut||i>=23&&i<91)return;ctx.beginPath();ctx.arc(...point,i>=91?3:6,0,Math.PI*2);ctx.fillStyle='#fff';ctx.strokeStyle='#145a4d';ctx.lineWidth=2;ctx.fill();ctx.stroke();});
}
function visionShowSample(row){
  if(visionState.drawSample===row&&$('#vision-frame-metrics')?.innerHTML)return;
  visionState.drawSample=row;visionDraw(row);
  const holder=$('#vision-frame-metrics');if(!holder)return;
  holder.innerHTML=metricCards(row?{metrics:row.metrics}:null)+(row?`<div class='vision-angle-grid'>${[['Tronco','trunk'],['Cuello','neck'],['Codo izquierdo','left_elbow_flexion'],['Codo derecho','right_elbow_flexion']].map(([name,key])=>`<div><span>${name}</span><strong>${row.metrics.angles[key]==null?'—':number(row.metrics.angles[key],1)+'°'}</strong></div>`).join('')}</div>`:'');
  if($('#vision-frame-position'))$('#vision-frame-position').textContent=row?`${visionSeconds(row.offset_s)} · ${row.persons_detected} persona${row.persons_detected===1?'':'s'} · confianza ${number(row.selection_confidence*100)} %`:'Sin detección sincronizada';
  if($('#vision-assumptions'))$('#vision-assumptions').innerHTML=assumptions(row?.metrics);
}
function visionVideoTime(frameTime){
  const video=$('#vision-result-video');if(!video)return;
  if(typeof frameTime==='number')video.posturePresentedTime=frameTime;
  // currentTime can lead the frame actually sent to the compositor. Once frame
  // callbacks are available, both playback and paused polling use that clock.
  const time=video.requestVideoFrameCallback?video.posturePresentedTime:video.currentTime;
  if(!Number.isFinite(time)||video.seeking){visionShowSample(null);return;}
  const samples=visionState.samples;let low=0,high=samples.length;
  while(low<high){const middle=(low+high)>>1;if(samples[middle].offset_s<=time)low=middle+1;else high=middle;}
  const row=low>0?samples[low-1]:null;
  const job=visionState.jobs.find(j=>j.job_id===visionState.selected);
  const maxGap=Math.max(.15,1/(job?.options.sample_fps||5)*1.6);
  visionShowSample(row&&Math.abs(time-row.offset_s)<=maxGap?row:null);
}
function visionBindDetail(job){
  if(!job)return;
  const video=$('#vision-result-video');
  video.ontimeupdate=()=>{if(!video.requestVideoFrameCallback)visionVideoTime();};
  video.onseeked=()=>visionVideoTime();
  video.onseeking=()=>{video.posturePresentedTime=undefined;visionShowSample(null);};
  if(video.requestVideoFrameCallback){
    const next=()=>video.requestVideoFrameCallback((_,metadata)=>{if(!video.isConnected)return;visionVideoTime(metadata.mediaTime);next();});
    next();
  }
  $('#vision-show-pose').onchange=()=>visionDraw(visionState.drawSample);
  $('#vision-result-frame').onload=()=>visionDraw(visionState.drawSample);
  $('#vision-cancel-job').onclick=async()=>{if(visionState.recording&&visionState.cameraJob?.job_id===job.job_id){toast('Para terminar la captura pulsa Detener y guardar.');return;}try{await visionRequest('/jobs/'+job.job_id+'/cancel',{method:'POST'});await visionRefresh();}catch(e){toast(e.message);}};
  $('#vision-reprocess').onclick=async()=>{try{await visionNewJob({asset_id:job.asset_id},{...visionOptions(),name:job.name+' · revisión'});await visionRefresh();}catch(e){toast(e.message);}};
  $('#vision-delete-job').onclick=async()=>{if(visionState.recording&&visionState.cameraJob?.job_id===job.job_id){toast('Detén y guarda la captura antes de eliminarla.');return;}if(!confirm('¿Eliminar este análisis, su sesión y sus fotogramas? El vídeo original se conserva en la biblioteca.'))return;try{await visionRequest('/jobs/'+job.job_id,{method:'DELETE'});visionState.selected=null;visionState.selectionKey=null;await visionRefresh();}catch(e){toast(e.message);}};
}
async function visionRefresh(){
  if(!visionHere()||visionState.polling)return;
  visionState.polling=true;
  try{
    [visionState.jobs,visionState.assets]=await Promise.all([visionRequest('/jobs'),visionRequest('/assets')]);
    if(!visionState.jobs.some(j=>j.job_id===visionState.selected)){visionState.selected=visionState.jobs[0]?.job_id||null;visionState.selectionKey=null;}
    if(!visionHere())return;
    $('#vision-jobs-list').innerHTML=visionJobs();$('#vision-assets-list').innerHTML=visionAssets();
    $('#vision-pending').hidden=!visionPendingAssets().length;$('#vision-pending').innerHTML=visionPending();visionBindLists();
    let job=visionState.jobs.find(j=>j.job_id===visionState.selected);
    if(visionState.selectionKey!==visionState.selected){visionState.samples=[];visionState.selectionKey=visionState.selected;$('#vision-detail').innerHTML=visionDetail(job);visionBindDetail(job);}
    if(!job){$('#vision-detail').innerHTML=visionDetail(null);return;}
    const id=job.job_id;
    const response=await visionRequest('/jobs/'+id+'/results?after='+(visionState.samples.at(-1)?.offset_s??-1));
    if(!visionHere()||visionState.selected!==id)return;
    job=response.job;
    const index=visionState.jobs.findIndex(j=>j.job_id===id);visionState.jobs[index]=job;
    visionState.samples.push(...response.samples);
    $('#vision-job-stage').textContent=job.stage;$('#vision-job-count').textContent=number(job.processed_frames)+' frames';
    $('#vision-job-progress').value=job.progress||0;$('#vision-job-error').textContent=job.error||'';
    $('#vision-job-state').innerHTML=chip(visionStatus[job.status]||job.status,job.status==='failed'?'red':'outline');
    $('#vision-cancel-job').hidden=!visionActive(job);
    $('#vision-summary').innerHTML=`<div><strong>${number(job.processed_frames)}</strong><span>Frames analizados</span></div><div><strong>${job.processed_frames?number(job.evaluable_frames/job.processed_frames*100):'—'} %</strong><span>Frames evaluables</span></div><div><strong>${job.summary?.rula_max??'—'} / ${job.summary?.reba_max??'—'}</strong><span>Máximos RULA / REBA</span></div>`;
    if(response.samples.length||!$('#vision-score-chart').innerHTML)$('#vision-score-chart').innerHTML=visionPlot();
    const video=$('#vision-result-video'),frame=$('#vision-result-frame');
    if(job.preview_path){if(video.hidden){video.src=visionVideoUrl(job);video.hidden=false;}frame.hidden=true;$('#vision-video-placeholder').hidden=true;
      if(video.paused)visionVideoTime();
    }else{
      const latest=visionState.samples.at(-1);
      if(latest){const url='/api/v1/frames/'+encodeURIComponent(id+':'+latest.sequence);
        if(frame.getAttribute('src')!==url){frame.hidden=true;visionDraw(null);frame.onload=()=>{frame.hidden=false;$('#vision-video-placeholder').hidden=true;visionState.drawSample=null;visionShowSample(latest);};frame.src=url;}
      }else visionShowSample(null);
    }
    if(!visionState.lastStatus||Date.now()-visionState.lastStatus>10000){visionState.status=await visionRequest('/status');visionState.lastStatus=Date.now();if($('#vision-engine'))$('#vision-engine').innerHTML=visionEngine();}
  }catch(e){if(visionHere()&&$('#vision-upload-status'))visionTransfer('No se ha podido actualizar: '+e.message);}
  finally{visionState.polling=false;}
}
function visionBindLists(){
  document.querySelectorAll('[data-vision-job]').forEach(b=>b.onclick=async()=>{visionState.selected=b.dataset.visionJob;visionState.selectionKey=null;await visionRefresh();});
  document.querySelectorAll('[data-vision-analyze]').forEach(b=>b.onclick=async()=>{b.disabled=true;try{const asset=visionState.assets.find(a=>a.asset_id===b.dataset.visionAnalyze);await visionNewJob(asset,asset.capture?.analysis_options||visionOptions());await visionRefresh();}catch(e){b.disabled=false;toast(e.message);}});
  document.querySelectorAll('[data-vision-delete-asset]').forEach(b=>b.onclick=async()=>{if(!confirm('¿Eliminar este vídeo y todos sus análisis? Los archivos importados de examples permanecerán en el servidor.'))return;try{await visionRequest('/assets/'+b.dataset.visionDeleteAsset,{method:'DELETE'});await visionRefresh();}catch(e){toast(e.message);}});
}
function visionBind(){
  clearInterval(visionState.poll);
  if(!visionHere()){
    if(!visionState.recording&&visionState.stream){visionState.stream.getTracks().forEach(t=>t.stop());visionState.stream=null;}
    return;
  }
  document.querySelectorAll('[data-vision-tab]').forEach(b=>b.onclick=async()=>{
    if(visionState.recording||visionState.uploading){toast('Termina la grabación o la subida antes de cambiar de entrada.');return;}
    if(visionState.stream){visionState.stream.getTracks().forEach(t=>t.stop());visionState.stream=null;}
    visionState.tab=b.dataset.visionTab;
    document.querySelectorAll('[data-vision-tab]').forEach(t=>t.classList.toggle('selected',t===b));
    try{await visionSource();}catch(e){toast(e.message);}
  });
  $('#vision-refresh').onclick=visionRefresh;
  $('#vision-detail').innerHTML=visionDetail(visionState.jobs.find(j=>j.job_id===visionState.selected));
  visionBindDetail(visionState.jobs.find(j=>j.job_id===visionState.selected));
  visionSource().catch(e=>toast(e.message));visionBindLists();
  visionRefresh();visionState.poll=setInterval(visionRefresh,1500);
}
function visionCanNavigate(view){
  if(visionState.recording||visionState.saving){if(view!=='vision'){location.hash='vision';toast('Detén y guarda la grabación antes de salir.');}return false;}
  return true;
}
window.addEventListener('beforeunload',e=>{if(visionState.recording||visionState.saving||visionState.uploading){e.preventDefault();e.returnValue='';}});
