'use strict';
const realState={tab:'iterations',filters:{},rows:[],shifts:[],selected:null,detail:null,poll:null,busy:false,
  samples:[],rosResults:[],serverResults:[],serverJob:null,cursorStack:[],before:null};
pages.real=['Trabajo en entorno real','Turnos y piezas recibidos desde HMI y ROS.'];
const realStatus=s=>({active:'En curso',completed:'Finalizada',aborted:'Cancelada',error:'Error',rejected:'Rechazada',
  queued:'En cola',running:'Procesando',failed:'Incidencia',missing:'Sin vídeo',uploading:'Subiendo',ready:'Guardado'})[s]||s;
const realApi=(path,options={})=>api(path,options);
const realJson=(method,body)=>({method,body:JSON.stringify(body)});
const realNewId=()=>crypto.randomUUID?crypto.randomUUID():'web-'+Date.now()+'-'+Math.random().toString(36).slice(2);
const realHere=()=>state.user&&state.view==='real'&&$('#real-workspace');
function realQuery(){const query=new URLSearchParams({limit:100,...realState.filters});if(realState.before)query.set('before_id',realState.before);return query;}
async function realPage(){
  [realState.rows,realState.shifts,realState.settings]=await Promise.all([
    realApi('/iterations?'+realQuery()),realApi('/shifts?limit=500'),realApi('/real/settings')]);
  return `<div id='real-workspace'><section class='panel'><div class='panel-head'><div><span class='chip outline'>HMI / ROS</span><h2>Registro de trabajo</h2><p>Operarios y perfiles gestionados por la HMI. Los controles del laboratorio siguen disponibles en su apartado.</p></div><div class='actions'>${admin()?`<button class='btn' id='real-settings'>Opciones del servidor</button>`:''}<a class='btn' href='/api/docs#/Trabajo%20en%20entorno%20real' target='_blank'>API ROS</a><button class='btn' id='real-refresh'>Actualizar</button></div></div>
    <div class='info-strip' id='real-policy'>${realPolicyText()}</div>
    <div class='segmented'><button data-real-tab='iterations' class='${realState.tab==='iterations'?'selected':''}'>Iteraciones / piezas</button><button data-real-tab='shifts' class='${realState.tab==='shifts'?'selected':''}'>Turnos y formularios</button></div></section>
    <section class='panel' id='real-iterations' ${realState.tab==='iterations'?'':'hidden'}><div class='panel-head'><div><h2>Una fila por pieza</h2><p>Desde el inicio de recogida del UR hasta Quality Check.</p></div></div>
    <form class='filters' id='real-filter-form'><label>Turno <select name='shift_id'><option value=''>Todos</option>${realState.shifts.map(s=>`<option value='${s.shift_id}' ${String(s.shift_id)===realState.filters.shift_id?'selected':''}>#${s.shift_id} · ${esc(s.operator.name)}</option>`).join('')}</select></label>
    <label>Operario <select name='operator_id'><option value=''>Todos</option>${state.operators.filter(o=>o.source==='hmi').map(o=>`<option value='${esc(o.operator_id)}' ${o.operator_id===realState.filters.operator_id?'selected':''}>${esc(o.display_name)} · ${esc(o.external_id)}</option>`).join('')}</select></label>
    <label>Etiqueta <input name='label' value='${esc(realState.filters.label||'')}' placeholder='Coincidencia exacta' maxlength='200'></label>
    <label>Estado <select name='status'><option value=''>Todos</option>${['active','completed','aborted','error','rejected'].map(s=>`<option value='${s}' ${s===realState.filters.status?'selected':''}>${realStatus(s)}</option>`).join('')}</select></label><button class='btn primary' type='submit'>Filtrar</button><button class='btn' type='button' id='real-clear-filters'>Limpiar</button></form>
    <div class='table-wrap' id='real-rows'>${realRows()}</div><div class='actions real-pagination'><button class='btn small' id='real-previous' ${realState.cursorStack.length?'':'disabled'}>Anteriores</button><button class='btn small' id='real-next' ${realState.rows.length===100?'':'disabled'}>Siguientes</button><span class='subtitle'>Hasta 100 piezas por página</span></div></section>
    <section class='panel' id='real-shifts' ${realState.tab==='shifts'?'':'hidden'}><div class='panel-head'><div><h2>Turnos</h2><p>ID estable, operario y formularios previo / posterior.</p></div></div><div class='filters'><label>Operario <select id='real-shift-operator'><option value=''>Todos</option>${state.operators.filter(o=>o.source==='hmi').map(o=>`<option value='${esc(o.operator_id)}'>${esc(o.display_name)}</option>`).join('')}</select></label><label>Etiqueta <input id='real-shift-label' placeholder='Coincidencia exacta' maxlength='200'></label></div><div id='real-shift-rows' class='table-wrap'>${realShifts()}</div></section>
    <div id='real-detail'>${empty('Selecciona una pieza o un turno','Los originales se guardan sin calcular pose ni métricas con la configuración inicial.')}</div></div>`;
}
function realPolicyText(){const s=realState.settings;return `Configuración para nuevas piezas · métricas ROS: <strong>${esc({manual:'bajo petición',live:'durante la ejecución',after_iteration:'al finalizar la pieza'}[s.ros_metrics_mode])}</strong> · análisis de vídeo: <strong>${s.video_analysis_mode==='manual'?'bajo petición':'automático con pieza cerrada y MP4 recibido'}</strong>. Laboratorio y captura web tienen sus propias opciones.`;}
function realRows(){return realState.rows.length?`<table><thead><tr><th>ID / turno</th><th>Inicio / fin</th><th>Operario</th><th>Robot</th><th>Etiqueta</th><th>Estado</th><th>Vídeo</th><th></th></tr></thead><tbody>${realState.rows.map(i=>`<tr><td><strong>#${i.iteration_id}</strong><br><small>Turno #${i.shift_id}</small></td><td>${date(i.started_at,true)}<br><small>${i.ended_at?date(i.ended_at,true):'En curso'}${i.ended_at?' · '+number((new Date(i.ended_at)-new Date(i.started_at))/1000,1)+' s':''}</small></td><td>${esc(i.operator.name)}<br><small>HMI: ${esc(i.external_operator_id)}</small></td><td>${i.robot_assisted===true?'Sí':i.robot_assisted===false?'No':'—'}</td><td>${esc(i.label||'—')}${admin()?` <button class='icon-btn' data-real-label='${i.iteration_id}' aria-label='Etiquetar iteración ${i.iteration_id}'>✎</button>`:''}</td><td>${chip(realStatus(i.status),i.status==='error'?'red':i.status==='active'?'outline':'green')}</td><td>${realStatus(i.video_status)}<br><small>${number(i.sample_count)} muestras</small></td><td><button class='btn small' data-real-detail='${i.iteration_id}'>Abrir</button></td></tr>`).join('')}</tbody></table>`:empty('Todavía no hay piezas en esta selección','ROS inicia cada pieza con POST /iterations.');}
function realShifts(){const oid=$('#real-shift-operator')?.value||'',label=$('#real-shift-label')?.value||'';
  const shifts=realState.shifts.filter(s=>(!oid||s.operator_id===oid)&&(!label||s.label===label));
  return shifts.length?`<table><thead><tr><th>ID</th><th>Operario</th><th>Inicio / fin</th><th>Etiqueta</th><th>Estado</th><th></th></tr></thead><tbody>${shifts.map(s=>`<tr><td>#${s.shift_id}</td><td>${esc(s.operator.name)}<br><small>HMI: ${esc(s.external_operator_id)}</small></td><td>${date(s.started_at,true)}<br><small>${s.ended_at?date(s.ended_at,true):'En curso'}</small></td><td>${esc(s.label||'—')}${admin()?` <button class='icon-btn' data-real-shift-label='${s.shift_id}' aria-label='Etiquetar turno ${s.shift_id}'>✎</button>`:''}</td><td>${chip(realStatus(s.status),s.status==='active'?'outline':'green')}</td><td><button class='btn small' data-real-shift='${s.shift_id}'>Ver turno</button></td></tr>`).join('')}</tbody></table>`:empty('Sin turnos en esta selección','Los turnos recibidos de ROS aparecerán aquí.');}
function realMetricSummary(j){return `<strong>${number(j.processed_frames)} muestras</strong> · ${number(j.evaluable_frames)} evaluables${j.summary?` · máximos RULA ${j.summary.rula_max??'—'} / REBA ${j.summary.reba_max??'—'}`:''}`;}
async function realOpenIteration(id){
  realState.selected=Number(id);realState.detail=await realApi('/iterations/'+id);
  realState.samples=await realApi('/iterations/'+id+'/samples?limit=1000');
  realState.rosResults=[];realState.serverResults=[];realState.serverJob=null;
  const d=realState.detail,ros=d.analyses.find(j=>j.source==='ros'&&j.processed_frames>0),server=d.video_analyses.find(j=>j.preview_path);
  if(ros)realState.rosResults=(await realApi(`/iterations/${id}/analyses/${ros.analysis_id}/results?limit=5000`)).samples;
  if(server&&admin()){
    const result=await visionRequest('/jobs/'+server.job_id+'/results?limit=20000');
    realState.serverResults=result.samples;realState.serverJob=server;
  }
  if(!realHere())return;
  $('#real-detail').innerHTML=`<section class='panel real-piece-detail'><div class='panel-head'><div><span class='chip outline'>TURNO #${d.shift_id}</span><h2>Iteración #${d.iteration_id} · ${esc(d.operator.name)}</h2><p>${esc(d.label||'Sin etiqueta')} · ${realStatus(d.status)} · ${number(d.sample_count)} muestras</p></div><div class='actions'>${admin()?`<button class='btn' data-real-analyze='ros'>Calcular métricas ROS</button><button class='btn primary' data-real-analyze='video' ${d.video_status==='ready'?'':'disabled'}>Analizar MP4 en servidor</button>`:''}<button class='btn' id='real-detail-refresh'>Actualizar pieza</button></div></div>
    <p class='subtitle'>El análisis conserva su fuente, versión y supuestos. Con una convención 3D desconocida no se asignan puntuaciones a partir de esos valores.</p>
    <div class='real-analysis-grid'>${['ros','video'].map(source=>`<div><h3>${source==='ros'?'Pose recibida de ROS':'Pose estimada en el servidor'}</h3>${d.analyses.filter(j=>j.source===source).map(j=>`<div class='real-analysis'>${chip(realStatus(j.status),j.status==='failed'?'red':'outline')} ${realMetricSummary(j)}${j.error?`<p class='form-error'>${esc(j.error)}</p>`:''}<small>${date(j.created_at,true)} · ${esc(j.analysis_id.slice(-10))}</small></div>`).join('')||'<p class="subtitle">Sin análisis solicitado</p>'}</div>`).join('')}</div>
    ${admin()&&d.video_status==='ready'?`<h3>Vídeo de la pieza</h3><div class='real-player'><video id='real-video' controls playsinline preload='metadata' src='${server?visionVideoUrl(server):'/api/v1/iterations/'+id+'/video'}'></video><canvas id='real-overlay'></canvas></div><div class='real-playback-controls'><label class='field'>Esqueleto sobre el vídeo<select id='real-overlay-source'><option value='server'>Servidor · si hay análisis</option><option value='ros'>ROS · si incluye coordenadas de imagen</option><option value='none'>Ocultar</option></select></label><a class='btn small' href='/api/v1/iterations/${id}/video'>Descargar original MP4</a></div><p class='subtitle' id='real-video-position'>Tiempo relativo al primer fotograma del MP4. Los resultados conservan sus tiempos originales.</p><div class='real-analysis-grid' id='real-frame-metrics'></div>`:admin()?'<p class="subtitle">El MP4 aún no está completo. Las muestras recibidas ya se pueden consultar.</p>':''}
    <details class='accordion' open><summary>Muestras ROS · imagen y 33 joints</summary>${realState.samples.length?`<label class='field'>Fotograma<select id='real-sample-select'>${realState.samples.map((s,n)=>`<option value='${n}'>#${s.sequence} · ${number(s.video_time_s,3)} s · ${date(s.captured_at)}</option>`).join('')}</select></label><div id='real-sample-detail'></div>${d.sample_count>1000?'<p class="subtitle">Se muestran las primeras 1.000 muestras; la API permite paginar todas.</p>':''}`:'<p class="subtitle">Sin muestras recibidas.</p>'}</details>
    <details class='accordion'><summary>Acciones y estado final</summary><pre class='code-box'>${esc(JSON.stringify(d.summary||{completion_reason:d.completion_reason,summary_received:false},null,2))}</pre></details>
    <details class='accordion'><summary>Operario y configuración al iniciar la pieza</summary><pre class='code-box'>${esc(JSON.stringify({operator:d.operator,policies:d.policies,metadata:d.metadata},null,2))}</pre></details></section>`;
  $('#real-detail-refresh').onclick=()=>realOpenIteration(id).catch(e=>toast(e.message));
  document.querySelectorAll('[data-real-analyze]').forEach(b=>b.onclick=async()=>{b.disabled=true;try{
    await realApi('/iterations/'+id+'/analyses',realJson('POST',{client_analysis_id:realNewId(),sources:[b.dataset.realAnalyze],sample_fps:realState.settings.sample_fps,confidence:realState.settings.confidence}));
    toast('Análisis solicitado. Puedes seguir recibiendo datos.');await realOpenIteration(id);
  }catch(e){toast(e.message);b.disabled=false;}});
  if($('#real-sample-select')){$('#real-sample-select').onchange=realShowSample;realShowSample();}
  const video=$('#real-video');
  if(video){
    const present=(_,metadata)=>{if(!video.isConnected)return;video.realPresentedTime=metadata.mediaTime;realVideoFrame(metadata.mediaTime);video.requestVideoFrameCallback(present);};
    if(video.requestVideoFrameCallback)video.requestVideoFrameCallback(present);
    video.ontimeupdate=()=>{if(!video.requestVideoFrameCallback)realVideoFrame(video.currentTime);};
    video.onseeking=()=>{const canvas=$('#real-overlay');canvas.getContext('2d').clearRect(0,0,canvas.width,canvas.height);};
    video.onseeked=()=>{if(!video.requestVideoFrameCallback)realVideoFrame(video.currentTime);};
    $('#real-overlay-source').onchange=()=>{if(video.realPresentedTime!=null||!video.requestVideoFrameCallback)realVideoFrame(video.realPresentedTime??video.currentTime);};
  }
}
function realShowSample(){const sample=realState.samples[Number($('#real-sample-select').value)];if(!sample)return;
  $('#real-sample-detail').innerHTML=`<p class='subtitle'>${esc(sample.pose.estimator_name)} · unidades: ${esc(sample.pose.space.unit)} · ejes: ${esc(sample.pose.space.axes)} · marco: ${esc(sample.pose.space.frame_id)}</p>${admin()?`<img class='real-sample-image' src='/api/v1/iterations/${sample.iteration_id}/samples/${sample.sequence}/image' alt='Frame original ROS ${sample.sequence}'>`:''}<pre class='code-box'>${esc(JSON.stringify({pose:sample.pose,tool:sample.tool,table:sample.table},null,2))}</pre>`;
}
function realAtTime(rows,time,key){let match=null;for(const row of rows){if(row[key]<=time+.000001&&(!match||row[key]>match[key]))match=row;}return match;}
function realVideoFrame(time){
  const canvas=$('#real-overlay');if(!canvas)return;
  const ros=realAtTime(realState.rosResults,time,'video_time_s'),server=realAtTime(realState.serverResults,time,'offset_s');
  $('#real-video-position').textContent='Vídeo · '+number(time,3)+' s';
  $('#real-frame-metrics').innerHTML=[['ROS',ros],['Servidor',server]].map(([label,row])=>`<div><h3>${label}</h3><p>RULA ${row?.metrics.rula??'—'} / 7 · REBA ${row?.metrics.reba??'—'} / 15</p><small>${esc(row?.metrics.reason||row?.metrics.status||'Sin análisis para este instante')}</small></div>`).join('');
  canvas.width=1920;canvas.height=1080;const ctx=canvas.getContext('2d'),choice=$('#real-overlay-source').value;
  if(choice==='none')return;
  let joints;
  if(choice==='server')joints=server?.joints;
  else{
    const frame=realAtTime(realState.samples,time,'video_time_s');
    if(frame){
      const scale=Math.min(1920/frame.image_width,1080/frame.image_height),dx=(1920-frame.image_width*scale)/2,dy=(1080-frame.image_height*scale)/2;
      joints=Object.fromEntries(Object.entries(frame.pose.joints).map(([name,j])=>[name,{...j,image_xy_px:j.image_xy_px?[dx+j.image_xy_px[0]*scale,dy+j.image_xy_px[1]*scale]:null}]));
    }
  }
  if(!joints)return;
  const edges=[['left_shoulder','right_shoulder'],['left_shoulder','left_elbow'],['left_elbow','left_wrist'],['right_shoulder','right_elbow'],['right_elbow','right_wrist'],['left_shoulder','left_hip'],['right_shoulder','right_hip'],['left_hip','right_hip'],['left_hip','left_knee'],['right_hip','right_knee']];
  const p=name=>{const j=joints[name];return j&&j.status!=='missing'&&(j.confidence==null||j.confidence>=.5)?j.image_xy_px:null;};
  ctx.strokeStyle='#c9ff9c';ctx.lineWidth=5;ctx.lineCap='round';
  for(const [a,b]of edges){const x=p(a),y=p(b);if(!x||!y)continue;ctx.beginPath();ctx.moveTo(...x);ctx.lineTo(...y);ctx.stroke();}
}
async function realOpenShift(id){
  const shift=await realApi('/shifts/'+id);realState.selected=null;
  $('#real-detail').innerHTML=`<section class='panel'><div class='panel-head'><div><span class='chip outline'>TURNO #${shift.shift_id}</span><h2>${esc(shift.operator.name)}</h2><p>${esc(shift.label||'Sin etiqueta')} · ${realStatus(shift.status)}</p></div><button class='btn' id='real-shift-pieces'>Ver sus piezas</button></div><div class='real-analysis-grid'>${['pre','post'].map(phase=>{const a=shift.assessments.find(a=>a.phase===phase);return `<div><h3>${phase==='pre'?'Antes del turno':'Después del turno'}</h3>${a?`<p>${esc(a.form_id)} · ${date(a.submitted_at,true)}</p><dl>${Object.entries(a.answers).map(([k,v])=>`<dt>${esc(a.form_definition.questions.find(q=>q.key===k)?.label||k)}</dt><dd>${esc(v)}</dd>`).join('')}</dl>`:'<p class="subtitle">Formulario aún no recibido</p>'}</div>`;}).join('')}</div><details class='accordion'><summary>Datos originales del turno</summary><pre class='code-box'>${esc(JSON.stringify(shift,null,2))}</pre></details></section>`;
  $('#real-shift-pieces').onclick=async()=>{realState.filters={shift_id:String(id)};realState.tab='iterations';realState.before=null;realState.cursorStack=[];await render();};
}
async function realSettings(){
  const [settings,forms]=await Promise.all([realApi('/real/settings'),realApi('/assessment-forms')]);
  modal('Opciones · trabajo en entorno real',`<div class='form-grid'><label class='field full'>Métricas de la pose enviada por ROS<select name='ros_metrics_mode'>${[['manual','Guardar y calcular bajo petición'],['live','Calcular mientras llegan las muestras'],['after_iteration','Calcular al finalizar la pieza']].map(([v,l])=>`<option value='${v}' ${settings.ros_metrics_mode===v?'selected':''}>${l}</option>`).join('')}</select></label><label class='field full'>Análisis de pose del MP4 en el servidor<select name='video_analysis_mode'><option value='manual' ${settings.video_analysis_mode==='manual'?'selected':''}>Guardar y analizar bajo petición</option><option value='when_ready' ${settings.video_analysis_mode==='when_ready'?'selected':''}>Analizar cuando la pieza esté cerrada y el MP4 completo</option></select></label>${field('Fotogramas de vídeo por segundo','sample_fps',settings.sample_fps,'number','min=1 max=25 step=1 required')}${field('Confianza mínima del estimador de vídeo','confidence',settings.confidence,'number','min=0.5 max=0.9 step=0.1 required')}<label class='field full'>Formulario para los siguientes turnos<select name='assessment_form_id'>${forms.map(f=>`<option value='${esc(f.form_id)}' ${f.form_id===settings.assessment_form_id?'selected':''}>${esc(f.title)} · ${esc(f.form_id)}</option>`).join('')}</select></label><p class='hint full'>Las políticas se fijan al iniciar cada pieza; el formulario se fija al iniciar el turno. Las grabaciones del laboratorio mantienen sus propias opciones.</p><button class='btn full' id='real-new-form' type='button'>Registrar otra versión de formulario</button></div>`,'Guardar opciones',async f=>{
    await realApi('/real/settings',realJson('PUT',{...Object.fromEntries(f),sample_fps:Number(f.get('sample_fps')),confidence:Number(f.get('confidence')),expected_revision:settings.revision}));
    toast('Opciones guardadas para nuevas piezas y turnos.');
  });
  $('#real-new-form').onclick=()=>{
    $('#modal').close();const form={...forms.find(f=>f.form_id===settings.assessment_form_id),form_id:'posture.shift-checkin.v2'};delete form.archived_at;
    modal('Nueva versión de formulario',`<p class='subtitle'>El ID debe ser nuevo. Cada pregunta define clave, texto, tipo, escala y fases pre/post. No se calcula una puntuación agregada.</p><label class='field'>Definición JSON<textarea name='definition' style='min-height:340px'>${esc(JSON.stringify(form,null,2))}</textarea></label>`,'Registrar versión',async f=>{await realApi('/assessment-forms',realJson('POST',JSON.parse(f.get('definition'))));toast('Formulario registrado. Puedes seleccionarlo en las opciones.');});
  };
}
async function realRefreshRows(){
  if(!realHere()||realState.busy)return;realState.busy=true;
  try{
    const shiftQuery=new URLSearchParams({limit:500});
    if($('#real-shift-operator')?.value)shiftQuery.set('operator_id',$('#real-shift-operator').value);
    if($('#real-shift-label')?.value)shiftQuery.set('label',$('#real-shift-label').value);
    [realState.rows,realState.shifts]=await Promise.all([realApi('/iterations?'+realQuery()),realApi('/shifts?'+shiftQuery)]);
    if(!realHere())return;
    $('#real-rows').innerHTML=realRows();$('#real-shift-rows').innerHTML=realShifts();realBindRows();
    $('#real-next').disabled=realState.rows.length<100;$('#real-previous').disabled=!realState.cursorStack.length;
    if(realState.selected&&(!$('#real-video')||$('#real-video').paused)){
      const latest=await realApi('/iterations/'+realState.selected);
      const signature=d=>JSON.stringify([d.status,d.sample_count,d.video_status,d.analyses.map(j=>[j.analysis_id,j.status,j.processed_frames])]);
      if(signature(latest)!==signature(realState.detail))await realOpenIteration(realState.selected);
    }
  }catch(e){toast(e.message);}finally{realState.busy=false;}
}
function realBindRows(){
  document.querySelectorAll('[data-real-detail]').forEach(b=>b.onclick=()=>realOpenIteration(b.dataset.realDetail).catch(e=>toast(e.message)));
  document.querySelectorAll('[data-real-shift]').forEach(b=>b.onclick=()=>realOpenShift(b.dataset.realShift).catch(e=>toast(e.message)));
  for(const kind of ['iteration','shift']){
    const attribute=kind==='iteration'?'data-real-label':'data-real-shift-label';
    document.querySelectorAll('['+attribute+']').forEach(b=>b.onclick=()=>{
      const id=Number(b.getAttribute(attribute)),row=(kind==='iteration'?realState.rows:realState.shifts).find(r=>r[kind+'_id']===id);
      modal('Etiqueta · '+(kind==='iteration'?'iteración':'turno')+' #'+id,field('Etiqueta para agrupar registros','label',row.label,'text','maxlength=200'),'Guardar etiqueta',async f=>{
        await realApi('/'+(kind==='iteration'?'iterations':'shifts')+'/'+id,realJson('PATCH',{label:f.get('label')}));toast('Etiqueta guardada.');
      });
    });
  }
}
function realBind(){
  clearInterval(realState.poll);if(!realHere())return;
  realBindRows();
  if(realState.selected&&realState.tab==='iterations')realOpenIteration(realState.selected).catch(e=>toast(e.message));
  document.querySelectorAll('[data-real-tab]').forEach(b=>b.onclick=()=>{realState.tab=b.dataset.realTab;render();});
  $('#real-refresh').onclick=async()=>{await realRefreshRows();if(realState.selected)await realOpenIteration(realState.selected);};
  if($('#real-settings'))$('#real-settings').onclick=()=>realSettings().catch(e=>toast(e.message));
  $('#real-filter-form').onsubmit=async e=>{e.preventDefault();realState.filters=Object.fromEntries([...new FormData(e.target)].filter(([,v])=>v!==''));realState.before=null;realState.cursorStack=[];await realRefreshRows();};
  $('#real-clear-filters').onclick=()=>{realState.filters={};realState.before=null;realState.cursorStack=[];render();};
  $('#real-next').onclick=async()=>{realState.cursorStack.push(realState.before);realState.before=realState.rows.at(-1).iteration_id;await realRefreshRows();};
  $('#real-previous').onclick=async()=>{realState.before=realState.cursorStack.pop()||null;await realRefreshRows();};
  ['#real-shift-operator','#real-shift-label'].forEach(id=>$(id).onchange=realRefreshRows);
  realState.poll=setInterval(()=>{if(realHere()&&!$('#modal').open)realRefreshRows();},5000);
}
function realOperatorCard(o){return `<section class='panel profile-card'><div class='profile-name'><div class='avatar'>${esc(o.display_name.slice(0,2).toUpperCase())}</div><div><h2>${esc(o.display_name)}</h2><p>Identidad recibida de HMI · ${esc(o.external_id)}</p></div></div>${chip('Gestionado por HMI','outline')}<div class='detail-list'><span>Estatura recibida</span><strong>${o.stature_m?number(o.stature_m*100,1)+' cm':'Sin informar'}</strong></div><p class='subtitle'>El historial de cada pieza conserva el perfil enviado al iniciarla. Los perfiles locales siguen disponibles para pruebas.</p></section>`;}
