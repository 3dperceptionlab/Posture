'use strict';
// Keep the established single-camera/live flow intact; paired recordings share
// one UI lifecycle and have independent upload queues and analysis jobs.
const visionSingleSource=visionSource,visionSingleOpen=visionOpenCamera;
const visionSingleStart=visionStartCamera,visionSingleStop=visionStopCamera;
const visionSingleFailure=visionCameraFailure,visionSingleBind=visionBind;
function visionCloseSecondary(){
  visionState.secondaryStream?.getTracks().forEach(track=>track.stop());
  visionState.secondaryStream=null;
}
function visionMultiButtons(busy=false){
  for(const id of ['vision-open-camera','vision-camera-device','vision-camera-device-2','vision-camera-mode','vision-add-camera'])if($('#'+id))$('#'+id).disabled=busy;
  const secure=window.isSecureContext&&!!navigator.mediaDevices?.getUserMedia;
  for(const id of ['vision-open-camera','vision-add-camera'])if($('#'+id))$('#'+id).disabled=busy||!secure;
  if($('#vision-start-camera'))$('#vision-start-camera').disabled=busy||!visionState.stream||visionState.stream.getVideoTracks()[0]?.readyState!=='live'||(visionState.dualCamera&&!visionState.secondaryStream);
  if($('#vision-stop-camera'))$('#vision-stop-camera').disabled=!visionState.recording;
}
async function visionSecondDeviceOptions(){
  const select=$('#vision-camera-device-2');if(!select)return;
  const first=visionState.stream?.getVideoTracks()[0]?.getSettings().deviceId;
  const devices=(await navigator.mediaDevices.enumerateDevices()).filter(device=>device.kind==='videoinput'&&device.deviceId!==first);
  const saved=visionState.secondaryDeviceId;
  select.innerHTML=devices.map((device,i)=>`<option value='${esc(device.deviceId)}'>${esc(device.label||'Cámara '+(i+2))}</option>`).join('');
  if(devices.some(device=>device.deviceId===saved))select.value=saved;
  return devices;
}
async function visionMultiSetup(){
  if(!$('#vision-camera-video')||$('#vision-add-camera'))return;
  const first=$('#vision-camera-video').parentElement;
  const previews=document.createElement('div');previews.className='vision-camera-previews';
  first.before(previews);previews.append(first);
  const secondary=document.createElement('div');secondary.id='vision-secondary-preview';secondary.className='vision-camera-preview';secondary.hidden=!visionState.dualCamera;
  secondary.innerHTML="<video id='vision-camera-video-2' autoplay muted playsinline aria-label='Vista previa de cámara 2'></video><span id='vision-camera-badge-2'>Cámara 2 apagada</span>";
  previews.append(secondary);
  const field=$('#vision-camera-device').parentElement;
  const extra=document.createElement('div');extra.innerHTML=`<button type='button' class='btn small' id='vision-add-camera'>${visionState.dualCamera?'Quitar segunda cámara':'Añadir segunda cámara'}</button><label class='field' id='vision-second-device-field' ${visionState.dualCamera?'':'hidden'}>Cámara 2<select id='vision-camera-device-2'></select></label><p class='hint' id='vision-dual-hint' ${visionState.dualCamera?'':'hidden'}>Inicio y parada conjuntos. Cada cámara guarda su vídeo y se analiza por separado al terminar.</p>`;
  field.after(extra);
  const multi=!!visionState.dualCamera;
  $('#vision-open-camera').textContent=multi?'Abrir cámaras':'Abrir cámara';
  $('#vision-start-camera').textContent=multi?'Grabar ambas':'Grabar';
  $('#vision-stop-camera').textContent=multi?'Detener ambas y guardar':'Detener y guardar';
  $('#vision-camera-mode option[value=live]').disabled=multi;
  $('#vision-add-camera').onclick=async()=>{
    if(visionState.recording||visionState.saving)return;
    visionState.dualCamera=!visionState.dualCamera;
    if(visionState.dualCamera){visionState.preDualMode=visionState.captureMode;visionState.captureMode='record';}
    else{visionCloseSecondary();visionState.captureMode=visionState.preDualMode||'manual';}
    await visionSource();
    if(visionState.dualCamera)try{await visionOpenCamera();}catch(error){$('#vision-camera-error').textContent=error.message;}
  };
  $('#vision-camera-device-2').onchange=()=>{
    visionState.secondaryDeviceId=$('#vision-camera-device-2').value;
    visionOpenCamera().catch(error=>{$('#vision-camera-error').textContent=error.message;});
  };
  if(multi){
    await visionSecondDeviceOptions();
    if(visionState.secondaryStream){$('#vision-camera-video-2').srcObject=visionState.secondaryStream;$('#vision-camera-badge-2').textContent='Cámara 2 · vista previa';}
  }
  visionMultiButtons(visionState.recording||visionState.saving);
}
visionSource=async function(){
  if(visionState.tab!=='camera'&&!visionState.recording)visionCloseSecondary();
  await visionSingleSource();
  if(visionState.tab==='camera')await visionMultiSetup();
};
visionOpenCamera=async function(){
  if(visionState.recording||visionState.saving||visionState.multiOpening)return;
  visionState.multiOpening=true;visionMultiButtons(true);
  try{
    visionCloseSecondary();
    await visionSingleOpen();
    if(visionState.dualCamera){
      const devices=await visionSecondDeviceOptions();
      if(!devices?.length)throw new Error('Conecta una segunda cámara USB diferente y pulsa Abrir cámaras.');
      const id=$('#vision-camera-device-2').value;
      const stream=await navigator.mediaDevices.getUserMedia({audio:false,video:{deviceId:{exact:id},width:{ideal:1920},height:{ideal:1080},frameRate:{ideal:25,max:25}}});
      visionState.secondaryStream=stream;visionState.secondaryDeviceId=id;
      const firstId=visionState.stream.getVideoTracks()[0].getSettings().deviceId;
      if(firstId&&stream.getVideoTracks()[0].getSettings().deviceId===firstId){visionCloseSecondary();throw new Error('Selecciona dos cámaras diferentes.');}
      $('#vision-camera-video-2').srcObject=stream;await $('#vision-camera-video-2').play();
      $('#vision-camera-badge-2').textContent='Cámara 2 · vista previa';
    }
  }finally{visionState.multiOpening=false;visionMultiButtons(false);}
};
visionStartCamera=async function(){
  if(!visionState.dualCamera)return visionSingleStart();
  if(visionState.recording||visionState.saving||visionState.uploading)return;
  const streams=[visionState.stream,visionState.secondaryStream];
  if(streams.some(stream=>!stream||stream.getVideoTracks()[0]?.readyState!=='live'))throw new Error('Abre las dos cámaras antes de grabar.');
  if(!window.MediaRecorder)throw new Error('Este navegador no permite grabar vídeo.');
  const mime=['video/webm;codecs=vp8','video/webm;codecs=vp9','video/webm','video/mp4'].find(type=>MediaRecorder.isTypeSupported(type));
  if(!mime)throw new Error('No hay un formato de grabación compatible.');
  const group=crypto.randomUUID(),stamp=new Date().toISOString().replace(/[:.]/g,'-');
  const mode=$('#vision-camera-mode').value==='manual'?'manual':'record',opts=visionOptions();
  const capture={group,mode,sides:[],active:true};visionState.multiCapture=capture;
  visionState.saving=true;visionMultiButtons(true);
  try{
    for(let i=0;i<2;i++){
      const options={...opts,name:(opts.name||'Captura doble').slice(0,140)+' · '+group.slice(0,8)+' · Cámara '+(i+1),capture_fps:streams[i].getVideoTracks()[0].getSettings().frameRate||25};
      const asset=await visionRequest('/uploads',{method:'POST',body:JSON.stringify({name:'camaras-'+stamp+'-'+group.slice(0,8)+'-camara-'+(i+1)+(mime.includes('mp4')?'.mp4':'.webm'),capture:{mode,analysis_options:options,group_id:group,camera_index:i+1}})});
      const side={asset,options,bytes:0,queue:Promise.resolve(),error:null,recorder:new MediaRecorder(streams[i],{mimeType:mime,videoBitsPerSecond:6000000})};
      capture.sides.push(side);
      side.stopped=new Promise(resolve=>side.recorder.addEventListener('stop',resolve,{once:true}));
      side.recorder.ondataavailable=event=>{
        if(!event.data.size)return;
        side.queue=side.queue.then(async()=>{if(side.error)return;side.bytes=await visionPutBlob(asset,event.data,side.bytes);
          visionTransfer('Grabación doble · Cámara 1: '+visionBytes(capture.sides[0].bytes)+' · Cámara 2: '+visionBytes(capture.sides[1]?.bytes||0));
        }).catch(error=>{side.error=error;if(visionState.recording)visionStopCamera().catch(visionCameraFailure);});
      };
      side.recorder.onerror=event=>{side.error=event.error||new Error('Error en cámara '+(i+1));if(visionState.recording)visionStopCamera().catch(visionCameraFailure);};
    }
    visionState.saving=false;visionState.recording=true;capture.startedAt=performance.now();
    // No awaited operation between either start or stop: both run in one turn.
    for(const side of capture.sides){side.recorder.start(1000);side.started=true;side.startedAt=performance.now();}
    visionState.cameraAsset=capture.sides[0].asset;
    visionMultiButtons(true);$('#vision-stop-camera').disabled=false;
    $('#vision-camera-badge').textContent='REC · Cámara 1';$('#vision-camera-badge-2').textContent='REC · Cámara 2';
  }catch(error){
    if(visionState.recording)await visionStopCamera().catch(()=>{});
    else{capture.active=false;visionState.saving=false;for(const side of capture.sides)if(!side.bytes)await visionRequest('/assets/'+side.asset.asset_id,{method:'DELETE'}).catch(()=>{});visionMultiButtons(false);}
    throw error;
  }
};
visionStopCamera=async function(){
  const capture=visionState.multiCapture;
  if(!capture?.active)return visionSingleStop();
  if(!visionState.recording)return;
  visionState.recording=false;visionState.saving=true;capture.stoppedAt=performance.now();visionMultiButtons(true);
  for(const side of capture.sides)if(side.started&&side.recorder.state!=='inactive'){side.recorder.stop();side.stoppedAt=performance.now();}
  const results=await Promise.allSettled(capture.sides.map(async(side,i)=>{
    if(side.started)await side.stopped;
    await side.queue;
    if(side.error)throw side.error;
    if(!side.bytes)throw new Error('La cámara '+(i+1)+' no ha guardado vídeo.');
    const ready=await visionRequest('/uploads/'+side.asset.asset_id+'/complete',{method:'POST'});
    side.ready=true;
    if(capture.mode==='record')side.job=await visionNewJob(ready,side.options);
    return ready;
  }));
  capture.active=false;visionState.saving=false;visionMultiButtons(false);
  $('#vision-camera-badge').textContent=capture.sides[0].ready?'Cámara 1 guardada':'Revisar cámara 1';
  $('#vision-camera-badge-2').textContent=capture.sides[1].ready?'Cámara 2 guardada':'Revisar cámara 2';
  await visionRefresh();
  const failures=results.filter(result=>result.status==='rejected');
  if(failures.length)throw new Error('Revisar grabación doble: '+failures.map(result=>result.reason.message).join(' · '));
  visionTransfer(capture.mode==='record'?'Dos vídeos guardados. Cada cámara tiene su propio análisis en la cola.':'Dos vídeos guardados sin análisis. Puedes procesar cada secuencia cuando quieras.');
};
visionCameraFailure=function(error){
  if(visionState.dualCamera||visionState.multiCapture?.active){
    if($('#vision-camera-error'))$('#vision-camera-error').textContent=error.message;
    if(!visionState.recording&&!visionState.saving)visionMultiButtons(false);
    toast(error.message);return;
  }
  return visionSingleFailure(error);
};
visionBind=function(){if(!visionHere()&&!visionState.recording)visionCloseSecondary();return visionSingleBind();};
