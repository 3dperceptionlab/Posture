'use strict';
pages.analysis=['Análisis de métricas','Compara las ejecuciones del laboratorio por altura de mesa, operario y condiciones de captura.'];
const visionAnalysisState={filters:{group_by:'table_height_cm',latest:'true'},data:null,generation:0};
const visionAnalysisDimensions={table_height_cm:'Altura de mesa',operator_id:'Operario',camera_index:'Cámara',condition:'Robot',day:'Día (UTC)'};
const visionAnalysisConditions={with_robot:'Con robot',without_robot:'Sin robot',unknown:'Sin definir'};
const visionAnalysisShell=shell;
shell=function(content){
  visionAnalysisShell(content);
  const laboratory=document.querySelector('.nav a[href="#vision"]');
  if(laboratory){const link=document.createElement('a');link.href='#analysis';link.className=state.view==='analysis'?'active':'';link.innerHTML=icon('overview')+'Análisis de métricas';laboratory.after(link);}
  visionAnalysisBind();
};
function visionAnalysisOperator(id){return state.operators.find(o=>o.operator_id===id)?.display_name||'Sin asignar';}
function visionAnalysisDimension(key,value){
  if(key==='operator_id')return visionAnalysisOperator(value);
  if(key==='table_height_cm')return value==null?'Sin definir':number(value)+' cm';
  if(key==='camera_index')return 'Cámara '+value;
  if(key==='condition')return visionAnalysisConditions[value]||'Sin definir';
  return value||'Sin definir';
}
function visionAnalysisSelect(name,label,options){const selected=visionAnalysisState.filters[name]||'';return `<label class='field'>${label}<select name='${name}'><option value=''>Todos</option>${options.map(([value,text])=>`<option value='${esc(value)}' ${String(value)===selected?'selected':''}>${esc(text)}</option>`).join('')}</select></label>`;}
async function visionAnalysisPage(){
  if(!admin())return empty('Acceso de administración','Los análisis de laboratorio están reservados a administradores.');
  const data=await visionRequest('/analysis?'+new URLSearchParams(visionAnalysisState.filters));
  visionAnalysisState.data=data;
  const f=visionAnalysisState.filters;
  return `<div id='vision-analysis'><div class='analysis-navigation'><a class='btn' href='#vision'>${icon('arrow')} Captura y vídeos</a><span class='chip outline'>LABORATORIO DE VISIÓN</span></div>
    <section class='panel analysis-controls'><div class='panel-head'><div><h2>Seleccionar y comparar</h2><p>Usa las alturas anotadas en cada ejecución; se pueden editar en el visor.</p></div></div>
    <form id='vision-analysis-filters'><div class='analysis-filter-grid'>
    ${visionAnalysisSelect('operator_id','Operario',data.available.operators.map(id=>[id,visionAnalysisOperator(id)]))}
    ${visionAnalysisSelect('table_height_cm','Altura de mesa',[...data.available.heights.map(n=>[String(n),n+' cm']),['none','Sin definir']])}
    ${visionAnalysisSelect('camera_index','Cámara',[['1','Cámara 1'],['2','Cámara 2']])}
    ${visionAnalysisSelect('condition','Uso de robot (según título)',Object.entries(visionAnalysisConditions))}
    ${visionAnalysisSelect('context_revision','Revisión de supuestos',data.available.revisions.map(n=>[n,'Revisión '+n]))}
    <label class='field'>Desde (UTC)<input type='date' name='since' value='${esc(f.since||'')}'></label>
    <label class='field'>Hasta (UTC)<input type='date' name='until' value='${esc(f.until||'')}'></label></div>
    <fieldset class='analysis-grouping'><legend>Agrupar por</legend>${Object.entries(visionAnalysisDimensions).map(([key,label])=>`<label><input type='checkbox' name='group' value='${key}' ${(f.group_by||'').split(',').includes(key)?'checked':''}>${label}</label>`).join('')}</fieldset>
    <div class='analysis-filter-actions'><label><input type='checkbox' name='latest' ${f.latest!=='false'?'checked':''}> Solo el último análisis terminado de cada vídeo</label><div class='actions'><button class='btn' type='reset'>Restablecer</button><button class='btn primary' type='submit'>Aplicar filtros</button></div></div>
    <p id='vision-analysis-error' class='vision-error' role='alert'></p></form></section>
    <div id='vision-analysis-report'>${visionAnalysisReport(data)}</div></div>`;
}
function visionAnalysisHistogram(summary,metric){
  const total=summary.valid_samples;
  return `<div class='analysis-histogram analysis-${metric}' role='img' aria-label='Distribución ${metric.toUpperCase()} en ${total} fotogramas evaluables'>${summary.counts.map((n,i)=>`<div title='${metric.toUpperCase()} ${i+1}: ${number(n)} fotogramas · ${number(total?n/total*100:0,1)} %'><span style='height:${total?Math.max(n?2:0,n/Math.max(...summary.counts,1)*46):0}px'></span><small>${i+1}</small></div>`).join('')}</div>`;
}
function visionAnalysisMetric(summary,metric){return `<div class='analysis-metric'><strong>${summary.median??'—'}<small> / ${metric==='rula'?7:15}</small></strong><span>Mediana · máx. ${summary.peak??'—'}</span>${visionAnalysisHistogram(summary,metric)}<small>${number(summary.above_threshold_pct,1)} % con ${metric.toUpperCase()} ≥ ${summary.threshold}<br>${number(summary.valid_samples)} fotogramas evaluables</small></div>`;}
function visionAnalysisReport(data){
  const rows=[...data.groups].sort((a,b)=>data.group_by.map(k=>visionAnalysisDimension(k,a[k])).join(' ').localeCompare(data.group_by.map(k=>visionAnalysisDimension(k,b[k])).join(' '),'es',{numeric:true})||String(a.context_revision).localeCompare(String(b.context_revision)));
  const runs=[...data.runs].sort((a,b)=>b.created_at.localeCompare(a.created_at));
  return `<div class='analysis-summary'>${[['Capturas distintas',data.totals.captures],['Análisis de cámara',data.totals.analyses],['Fotogramas analizados',data.totals.samples],['Grupos comparables',data.groups.length]].map(([title,n])=>`<section class='panel'><span>${title}</span><strong>${number(n)}</strong></section>`).join('')}</div>
    <section class='panel'><div class='panel-head'><div><h2>Comparación por grupos</h2><p>Distribuciones de puntuación RULA (1–7) y REBA (1–15).</p></div><button id='vision-analysis-csv' class='btn small' ${runs.length?'':'disabled'}>${icon('download')} Exportar comparación CSV</button></div>
    <p class='analysis-method'>Cada fotograma evaluable tiene el mismo peso; los porcentajes son de fotogramas, no de tiempo ni de personas. Cada cámara aporta su propio análisis. Las revisiones de supuestos, algoritmo, geometría, estimador, frecuencia y confianza se mantienen separadas. Son estimaciones preliminares.</p>
    ${data.totals.without_results?`<p class='analysis-method'>${data.totals.without_results} análisis terminados no tienen resultados disponibles.</p>`:''}
    ${rows.length?`<div class='table-scroll'><table class='table analysis-table'><thead><tr><th>Grupo</th><th>Capturas / análisis</th><th>RULA</th><th>REBA</th><th>Contexto de cálculo</th></tr></thead><tbody>${rows.map(row=>`<tr><td>${data.group_by.map(k=>`<span class='analysis-group-value'>${esc(visionAnalysisDimension(k,row[k]))}</span>`).join('')}</td><td>${row.captures} / ${row.analyses}<small class='analysis-cell-note'>${number(row.samples)} fotogramas</small></td><td>${visionAnalysisMetric(row.rula,'rula')}</td><td>${visionAnalysisMetric(row.reba,'reba')}</td><td>${visionAnalysisContext(row)}</td></tr>`).join('')}</tbody></table></div>`:empty('No hay resultados para estos filtros','Prueba otro operario, altura o intervalo de fechas.')}</section>
    <section class='panel analysis-runs'><div class='panel-head'><div><h2>Ejecuciones incluidas</h2><p>Abre una ejecución para revisar el vídeo, la pose y su serie temporal.</p></div></div>
    ${runs.length?`<div class='table-scroll'><table class='table'><thead><tr><th>Ejecución / operario</th><th>Altura</th><th>Cámara</th><th>RULA mediana / máx.</th><th>REBA mediana / máx.</th><th>Supuestos</th><th></th></tr></thead><tbody>${runs.map(run=>`<tr><td><strong>${esc(run.name)}</strong><small class='analysis-cell-note'>${esc(visionAnalysisOperator(run.operator_id))} · ${date(run.created_at,true)}</small></td><td>${esc(visionAnalysisDimension('table_height_cm',run.table_height_cm))}</td><td>${run.camera_index}</td><td>${run.rula.median??'—'} / ${run.rula.peak??'—'}</td><td>${run.reba.median??'—'} / ${run.reba.peak??'—'}</td><td>Rev. ${esc(run.context_revision??'—')}</td><td><button class='btn small' data-analysis-open='${esc(run.job_id)}'>Ver vídeo</button></td></tr>`).join('')}</tbody></table></div>`:''}</section>`;
}
function visionAnalysisContext(row){return `<strong>Supuestos · rev. ${esc(row.context_revision??'—')}</strong><small class='analysis-cell-note'>${esc(row.algorithm_version||'Sin versión')}<br>${esc(row.geometry||'Sin geometría')}<br>${number(row.sample_fps)} fps · confianza ${number(row.confidence*100)} %<br>${esc(row.estimator||'Sin estimador')}<br>Contexto ${esc(row.context_signature||'')}</small>`;}
async function visionAnalysisReload(form){
  const fields=new FormData(form),groups=fields.getAll('group');
  if(!groups.length){$('#vision-analysis-error').textContent='Selecciona al menos una agrupación.';return;}
  const filters={group_by:groups.join(','),latest:String(fields.has('latest'))};
  for(const key of ['operator_id','table_height_cm','camera_index','condition','context_revision','since','until'])if(fields.get(key))filters[key]=fields.get(key);
  const generation=++visionAnalysisState.generation;
  const submit=form.querySelector('[type="submit"]');submit.disabled=true;$('#vision-analysis-error').textContent='';
  try{
    const data=await visionRequest('/analysis?'+new URLSearchParams(filters));
    if(generation!==visionAnalysisState.generation||!$('#vision-analysis-report'))return;
    visionAnalysisState.filters=filters;visionAnalysisState.data=data;
    $('#vision-analysis-report').innerHTML=visionAnalysisReport(data);visionAnalysisBindReport();
  }catch(error){if($('#vision-analysis-error'))$('#vision-analysis-error').textContent=error.message;}
  finally{if(submit.isConnected&&generation===visionAnalysisState.generation)submit.disabled=false;}
}
function visionAnalysisBind(){
  const form=$('#vision-analysis-filters');if(!form)return;
  form.onsubmit=event=>{event.preventDefault();visionAnalysisReload(form);};
  form.onreset=event=>{event.preventDefault();visionAnalysisState.filters={group_by:'table_height_cm',latest:'true'};render();};
  visionAnalysisBindReport();
}
function visionAnalysisBindReport(){
  document.querySelectorAll('[data-analysis-open]').forEach(button=>button.onclick=()=>{visionState.selected=button.dataset.analysisOpen;visionState.selectionKey=null;location.hash='vision';});
  const download=$('#vision-analysis-csv');if(download)download.onclick=visionAnalysisDownload;
}
function visionAnalysisDownload(){
  const data=visionAnalysisState.data;
  const columns=['job_id','name','operator_id','operator_name','table_height_cm','table_height_source','camera_index','capture_id','condition','created_at','context_revision','algorithm_version','geometry','estimator','sample_fps','confidence','samples','rula.valid_samples','rula.median','rula.peak','rula.above_threshold_pct','rula.counts','reba.valid_samples','reba.median','reba.peak','reba.above_threshold_pct','reba.counts'];
  const quote=value=>'"'+String(value??'').replaceAll('"','""')+'"';
  const csv=[columns.map(quote).join(','),...data.runs.map(run=>columns.map(key=>{const value=key==='operator_name'?visionAnalysisOperator(run.operator_id):key.split('.').reduce((obj,k)=>obj?.[k],run);return quote(Array.isArray(value)?JSON.stringify(value):value);}).join(','))].join('\r\n');
  const url=URL.createObjectURL(new Blob(['\ufeff'+csv],{type:'text/csv;charset=utf-8'}));
  const link=document.createElement('a');link.href=url;link.download='posture-laboratory-comparison.csv';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}

// Extend the existing capture and paired-video lifecycle without replacing it.
const visionHeightOptions=visionOptions;
visionOptions=function(){
  const options=visionHeightOptions(),value=$('#vision-capture-height')?.value;
  if(value&&value!=='auto')options.table_height_cm=value==='none'?null:Number(value);
  return options;
};
const visionHeightBind=visionBind;
visionBind=function(){
  visionHeightBind();
  if(!visionHere())return;
  const settings=$('.vision-settings');
  if(settings&&!$('#vision-capture-height')){
    const label=document.createElement('label');label.className='field';label.innerHTML="Altura de mesa<select id='vision-capture-height'><option value='auto'>Deducir del título</option><option value='75'>75 cm</option><option value='100'>100 cm</option><option value='120'>120 cm</option><option value='none'>Sin definir</option></select>";settings.append(label);
  }
  const header=$('.page-head');header.classList.add('vision-page-head');
  header.querySelector('.eyebrow')?.remove();header.querySelector('.subtitle')?.remove();
  if(!header.querySelector('[href="#analysis"]')){const link=document.createElement('a');link.className='btn';link.href='#analysis';link.innerHTML=icon('overview')+'Analizar por altura';header.querySelector('.actions').append(link);}
};
const visionHeightBindDetail=visionBindDetail;
visionBindDetail=function(job){
  visionHeightBindDetail(job);
  if(!job||$('#vision-height-editor'))return;
  const editor=document.createElement('form');editor.id='vision-height-editor';editor.className='vision-height-editor';
  editor.innerHTML=`<label for='vision-run-height'>Altura de mesa (cm)</label><input id='vision-run-height' type='number' min='20' max='200' step='1' placeholder='—' value='${esc(job.table_height_cm??'')}'><button class='btn small' type='submit'>Guardar altura</button><small>Vacío = sin definir · ${job.table_height_source==='title'?'deducida del título':'anotación de laboratorio'}</small>`;
  $('.vision-result .panel-head').after(editor);
  editor.onsubmit=async event=>{
    event.preventDefault();const button=editor.querySelector('button');button.disabled=true;
    try{const value=$('#vision-run-height').value;const updated=await visionRequest('/jobs/'+job.job_id+'/metadata',{method:'PATCH',body:JSON.stringify({table_height_cm:value===''?null:Number(value)})});Object.assign(job,updated);editor.querySelector('small').textContent='Altura guardada · anotación de laboratorio';toast('Altura de mesa guardada.');await visionRefresh();}
    catch(error){toast(error.message);}finally{button.disabled=false;}
  };
};
