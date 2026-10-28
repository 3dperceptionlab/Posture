'use strict';

function profileModal(id){
  const op=state.operators.find(o=>o.operator_id===id),p=op?.profile,rule=state.tableHeightRule;
  const xyz=p?.presentation_pose.position_m||[0,0,0],q=p?.presentation_pose.orientation_xyzw||[0,0,0,1];
  const mode=p?(p.table_height_mode||'manual'):'automatic';
  modal(op?'Editar perfil':'Nuevo operario',`<div class='form-grid'>
    <div class='full'>${field('Nombre del operario','name',op?.display_name||'','text','required maxlength=200')}</div>
    ${field('Estatura del operario · cm','stature',p?.stature_m!=null?Math.round(p.stature_m*1000)/10:'','number',`min=${rule.stature_min_m*100} max=${rule.stature_max_m*100} step=0.1 ${!op?'required':''}`)}
    <label class='field'>Altura de mesa<select name='table_height_mode'><option value='automatic' ${mode==='automatic'?'selected':''}>Calcular a partir de la estatura</option><option value='manual' ${mode==='manual'?'selected':''}>Ajustar manualmente</option></select></label>
    ${field('Altura superficie de mesa · cm','height',p?Math.round(p.table_height_m*1000)/10:'','number','min=20 max=200 step=0.1 required')}
    <p class='hint' id='table-height-hint'>${esc(rule.description)} No sustituye el ajuste del puesto a la tarea.</p>
    <div class='field full'>Posición de presentación · metros<div class='vector'>${['X','Y','Z'].map((k,i)=>field(k,'p'+i,xyz[i],'number','step=0.001 required')).join('')}</div></div>
    <div class='field full'>Orientación · cuaternión XYZW<div class='vector quat'>${['X','Y','Z','W'].map((k,i)=>field(k,'q'+i,q[i],'number','step=0.0001 required')).join('')}</div></div>
    ${field('Marco de referencia','frame',p?.presentation_pose.frame_id||'ur3_base','text','required')}
    <p class='hint full'>ROS valida los límites físicos y confirma la versión aplicada al robot y a la mesa. Introduce una pose validada para tu célula. Los perfiles anteriores conservan su altura hasta que los edites.</p>
  </div>`,op?'Guardar nueva revisión':'Crear perfil',async f=>{
    const automatic=f.get('table_height_mode')==='automatic';
    const body={display_name:f.get('name'),stature_m:f.get('stature')?Number(f.get('stature'))/100:null,
      table_height_mode:f.get('table_height_mode'),
      presentation_pose:{frame_id:f.get('frame'),position_m:[0,1,2].map(i=>Number(f.get('p'+i))),orientation_xyzw:[0,1,2,3].map(i=>Number(f.get('q'+i)))}};
    if(!automatic)body.table_height_m=Number(f.get('height'))/100;
    if(p){body.expected_revision=p.revision;await api('/operator-profiles/'+encodeURIComponent(p.profile_id),{method:'PUT',body:JSON.stringify(body)});}
    else await api('/operators',{method:'POST',body:JSON.stringify(body)});
    toast('Perfil guardado. La aplicación se confirmará desde ROS.');
  });
  const stature=$('#modal-form [name=stature]'),height=$('#modal-form [name=height]'),choice=$('#modal-form [name=table_height_mode]');
  function updateHeight(){
    const automatic=choice.value==='automatic';
    stature.required=!op||automatic;height.readOnly=automatic;
    if(automatic)height.value=stature.value&&stature.validity.valid?Math.round(Number(stature.value)*rule.factor*10)/10:'';
  }
  stature.oninput=updateHeight;choice.onchange=updateHeight;updateHeight();
}
