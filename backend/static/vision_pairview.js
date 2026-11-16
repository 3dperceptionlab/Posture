'use strict';
const visionPrimaryBindDetail=visionBindDetail;
visionBindDetail=function(job){
  visionPrimaryBindDetail(job);
  const primary=$('#vision-result-video');
  if(primary&&job)visionLoadPairedView(job,primary).catch(error=>{if(primary.isConnected)toast('No se pudo cargar la otra cámara: '+error.message);});
};
async function visionLoadPairedView(job,primary){
  const pair=await visionRequest('/jobs/'+encodeURIComponent(job.job_id)+'/cameras');
  if(!primary.isConnected||visionState.selected!==job.job_id||pair.cameras.length<2||$('#vision-companion-video'))return;
  const current=pair.cameras.find(camera=>camera.job.job_id===job.job_id);
  const companion=pair.cameras.find(camera=>camera.camera_index!==current?.camera_index);
  if(!current||!companion)return;
  let other=companion.job;
  const player=primary.parentElement,wrapper=document.createElement('div');wrapper.className='vision-paired-playback';
  player.before(wrapper);wrapper.append(player);
  const label=document.createElement('span');label.className='vision-view-label';label.textContent='Cámara '+current.camera_index+' · métricas seleccionadas';player.append(label);
  const panel=document.createElement('div');
  panel.innerHTML=`<div class='vision-player'><video id='vision-companion-video' muted playsinline preload='metadata' aria-label='Vídeo de cámara ${companion.camera_index}'></video><canvas id='vision-companion-overlay'></canvas><span class='vision-view-label'>Cámara ${companion.camera_index}</span></div><button type='button' class='btn small vision-select-companion'>Ver métricas de cámara ${companion.camera_index}</button>`;
  wrapper.append(panel);
  const hint=document.createElement('p');hint.className='hint vision-pair-hint';hint.textContent='Ambas cámaras se reproducen juntas con los controles del vídeo seleccionado. Las métricas corresponden a la cámara marcada.';wrapper.after(hint);
  const video=panel.querySelector('video'),canvas=panel.querySelector('canvas');
  video.src=other.preview_path?visionVideoUrl(other):'/api/v1/vision/jobs/'+encodeURIComponent(other.job_id)+'/source-video';
  panel.querySelector('button').onclick=async()=>{primary.pause();video.pause();visionState.selected=other.job_id;visionState.selectionKey=null;await visionRefresh();};
  let samples=[],timer,loading=false,presentedTime;
  visionState.chartPrimaryIndex=current.camera_index;
  visionState.chartPeer={selectedJobId:job.job_id,camera:companion.camera_index,samples};
  visionRenderChart();
  function draw(){
    const time=presentedTime??video.currentTime;
    let low=0,high=samples.length;
    while(low<high){const mid=(low+high)>>1;if(samples[mid].offset_s<=time)low=mid+1;else high=mid;}
    const row=low?samples[low-1]:null;
    const gap=Math.max(.15,1/(other.options.sample_fps||5)*1.6);
    visionDraw(row&&time-row.offset_s<=gap?row:null,canvas,other.options.confidence);
  }
  async function load(){
    if(!video.isConnected){clearInterval(timer);video.pause();return;}
    if(loading)return;loading=true;
    try{
      const data=await visionRequest('/jobs/'+encodeURIComponent(other.job_id)+'/results?after='+(samples.at(-1)?.offset_s??-1));
      if(!video.isConnected)return;
      other=data.job;samples.push(...data.samples);draw();
      if(visionState.selected===job.job_id)visionRenderChart();
      if(other.preview_path&&video.getAttribute('src')!==visionVideoUrl(other)){
        presentedTime=undefined;video.src=visionVideoUrl(other);
      }
      if(!visionActive(other)&&samples.length>=data.total)clearInterval(timer);
    }catch(error){if(video.isConnected)hint.textContent='La segunda cámara sigue disponible; no se pudieron actualizar sus métricas.';}
    finally{loading=false;}
  }
  function sync(seek=false){
    if(!video.isConnected)return;
    video.playbackRate=primary.playbackRate;
    if(Number.isFinite(video.duration)&&(seek||Math.abs(video.currentTime-primary.currentTime)>.15))video.currentTime=Math.min(primary.currentTime,Math.max(0,video.duration-.001));
    if(primary.paused){video.pause();return;}
    video.play().catch(()=>{hint.textContent='Pulsa reproducir en el vídeo seleccionado para iniciar ambas cámaras.';});
  }
  primary.addEventListener('play',()=>sync(true));primary.addEventListener('playing',()=>sync());
  primary.addEventListener('pause',()=>video.pause());primary.addEventListener('waiting',()=>video.pause());
  primary.addEventListener('seeking',()=>sync(true));primary.addEventListener('timeupdate',()=>sync());
  primary.addEventListener('ratechange',()=>sync());video.addEventListener('loadedmetadata',()=>sync(true));
  video.addEventListener('seeking',()=>{presentedTime=undefined;visionDraw(null,canvas);});
  $('#vision-show-pose').addEventListener('change',draw);
  if(video.requestVideoFrameCallback){
    const next=()=>video.requestVideoFrameCallback((_,metadata)=>{if(!video.isConnected){video.pause();return;}presentedTime=metadata.mediaTime;draw();next();});next();
  }else video.addEventListener('timeupdate',draw);
  timer=setInterval(load,2000);await load();
}
