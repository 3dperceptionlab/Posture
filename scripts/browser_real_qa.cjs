const {chromium}=require('playwright');
const fs=require('fs');
const assert=require('assert/strict');
(async()=>{
  const browser=await chromium.launch({headless:true});
  const context=await browser.newContext({viewport:{width:1440,height:1050}});
  const page=await context.newPage(),base='http://172.19.33.30:8080';
  const errors=[],checks=[],source='qa-real-browser-'+Date.now();
  page.on('pageerror',e=>errors.push(e.message));
  const headers={Authorization:'Bearer '+process.env.POSTURE_INGEST_TOKEN};
  async function post(path,data){const r=await page.request.post(base+'/api/v1'+path,{headers,data});assert(r.ok(),await r.text());return r.json();}
  async function get(path){const r=await page.request.get(base+'/api/v1'+path);assert(r.ok(),await r.text());return r.json();}
  async function poll(fn,ready,label){for(let n=0;n<180;n++){const v=await fn();if(ready(v))return v;await page.waitForTimeout(500);}throw new Error('Timeout: '+label);}
  let shift,iteration;
  try{
    await page.goto(base+'/#real');
    await page.locator('[name=username]').fill(process.env.POSTURE_ADMIN_USER);
    await page.locator('[name=password]').fill(process.env.POSTURE_ADMIN_PASSWORD);
    await page.getByRole('button',{name:'Entrar en la plataforma'}).click();
    await page.locator('#real-workspace').waitFor();
    const settings=await get('/real/settings'),operator={id:source,name:'Operario QA interfaz',stature_m:1.8,profile:{table_height_m:1.08}};
    const t=new Date(Date.now()-60000),at=n=>new Date(t.getTime()+n*1000).toISOString();
    shift=await post('/shifts',{source_id:source,cell_id:source,client_shift_id:'shift-1',started_at:at(0),operator,
      assessment:{form_id:settings.assessment_form_id,submitted_at:at(0),answers:{fatigue:2,comfort:8}}});
    iteration=await post('/iterations',{source_id:source,cell_id:source,client_iteration_id:'piece-1',shift_id:shift.shift_id,started_at:at(1),operator,robot_assisted:true});
    fs.writeFileSync('/results/fixture.json',JSON.stringify({source,shift_id:shift.shift_id,iteration_id:iteration.iteration_id}));
    const sample=JSON.parse(fs.readFileSync('/project/examples/ros/sample.json'));sample.captured_at=at(1);
    const upload=await page.request.post(base+`/api/v1/iterations/${iteration.iteration_id}/update_sample`,{headers,multipart:{
      metadata:JSON.stringify(sample),image:{name:'frame.jpg',mimeType:'image/jpeg',buffer:fs.readFileSync('/project/examples/ros/frame.synthetic.jpg')}}});
    assert(upload.ok(),await upload.text());
    await post(`/iterations/${iteration.iteration_id}/summary`,{ended_at:at(3),actions:[{event_id:'qc-1',observed_at:at(3),type:'quality_check',message:'Prueba interfaz'}]});
    const mp4=fs.readFileSync('/project/examples/videos/mmpose-demo.mp4'),crypto=require('crypto');
    await post(`/iterations/${iteration.iteration_id}/video/uploads`,{size_bytes:mp4.length,sha256:crypto.createHash('sha256').update(mp4).digest('hex'),recorded_at:at(1)});
    const block=await page.request.put(base+`/api/v1/iterations/${iteration.iteration_id}/video?offset=0`,{headers:{...headers,'Content-Type':'video/mp4'},data:mp4});assert(block.ok());
    await post(`/iterations/${iteration.iteration_id}/video/complete`,{});
    await page.reload();await page.locator(`[data-real-detail="${iteration.iteration_id}"]`).waitFor();
    await page.locator(`[data-real-detail="${iteration.iteration_id}"]`).click();
    await page.locator('.real-piece-detail').waitFor();
    assert.equal((await get(`/iterations/${iteration.iteration_id}`)).analyses.length,0);
    await page.locator('.real-sample-image').waitFor();
    await page.waitForFunction(()=>document.querySelector('.real-sample-image')?.naturalWidth===1920);
    await page.screenshot({path:'/results/real-before-analysis.png',fullPage:true});
    checks.push('HTTP dashboard shows HMI snapshot, frame, iteration and shift with no automatic analysis');
    await page.locator(`[data-real-label="${iteration.iteration_id}"]`).click();
    await page.locator('#modal-form [name=label]').fill('QA grupo ergonómico');
    await page.getByRole('button',{name:'Guardar etiqueta',exact:true}).click();
    await page.locator('#modal').waitFor({state:'hidden'});
    await page.locator('#real-filter-form [name=label]').fill('QA grupo ergonómico');
    await page.getByRole('button',{name:'Filtrar',exact:true}).click();
    await poll(()=>get('/iterations?label='+encodeURIComponent('QA grupo ergonómico')),rows=>rows.some(r=>r.iteration_id===iteration.iteration_id),'label');
    checks.push('Iteration label editable and filterable');
    await page.locator(`[data-real-detail="${iteration.iteration_id}"]`).click();
    await page.getByRole('button',{name:'Calcular métricas ROS',exact:true}).click();
    await poll(()=>get(`/iterations/${iteration.iteration_id}`),i=>i.analyses.some(j=>j.source==='ros'&&j.status==='completed'),'ROS analysis');
    await page.getByRole('button',{name:'Actualizar pieza',exact:true}).click();
    await page.getByRole('button',{name:'Analizar MP4 en servidor',exact:true}).click();
    await poll(()=>get(`/iterations/${iteration.iteration_id}`),i=>i.analyses.some(j=>j.source==='video'&&j.status==='completed'),'CUDA analysis');
    await page.getByRole('button',{name:'Actualizar pieza',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('#real-video')?.videoWidth===1920);
    await page.locator('#real-video').evaluate(v=>{v.currentTime=.4;});
    await page.waitForFunction(()=>/RULA \d+/.test(document.querySelector('#real-frame-metrics')?.children[1]?.textContent||''));
    assert(await page.evaluate(()=>{
      const video=document.querySelector('#real-video'),frame=realAtTime(realState.serverResults,video.realPresentedTime,'offset_s');
      return frame&&frame.offset_s<=video.realPresentedTime+.000001;
    }));
    assert(await page.locator('.real-analysis-grid').first().textContent().then(t=>t.includes('ROS')&&t.includes('servidor')));
    await page.screenshot({path:'/results/real-comparison.png',fullPage:true});
    checks.push('Manual ROS and CUDA analysis controls, comparable results and synchronized WebM playback');
    await page.getByRole('button',{name:'Turnos y formularios',exact:true}).click();
    await page.locator(`[data-real-shift="${shift.shift_id}"]`).click();
    await page.getByRole('heading',{name:'Antes del turno',exact:true}).waitFor();
    assert((await page.locator('#real-detail').textContent()).includes('Fatiga percibida'));
    await page.locator(`[data-real-shift-label="${shift.shift_id}"]`).click();
    await page.locator('#modal-form [name=label]').fill('QA turno laboratorio');
    await page.getByRole('button',{name:'Guardar etiqueta',exact:true}).click();await page.locator('#modal').waitFor({state:'hidden'});
    await page.locator(`[data-real-shift="${shift.shift_id}"]`).click();
    await page.getByRole('button',{name:'Ver sus piezas',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('#real-filter-form [name=shift_id]').value!=='');
    checks.push('Shift questionnaires, editable shift label and navigation to its pieces');
    await page.getByRole('button',{name:'Opciones del servidor',exact:true}).click();
    assert.equal(await page.locator('[name=ros_metrics_mode]').inputValue(),'manual');
    assert.equal(await page.locator('[name=video_analysis_mode]').inputValue(),'manual');
    await page.getByRole('button',{name:'Guardar opciones',exact:true}).click();await page.locator('#modal').waitFor({state:'hidden'});
    checks.push('Production policies menu is independent and preserves manual defaults');
    await page.getByRole('link',{name:'Operarios y perfiles',exact:true}).click();
    const card=page.locator('.profile-card').filter({hasText:'Operario QA interfaz'});
    await card.getByText('Gestionado por HMI',{exact:true}).waitFor();
    assert.equal(await card.getByRole('button',{name:'Editar perfil',exact:true}).count(),0);
    assert(await page.getByRole('button',{name:'Añadir operario',exact:true}).isVisible());
    await page.getByRole('link',{name:'Laboratorio de visión',exact:true}).click();
    await page.getByRole('button',{name:'Cámara USB',exact:true}).click();
    assert.equal(await page.locator('#vision-camera-mode').inputValue(),'manual');
    checks.push('HMI identities read-only while local operator tools and default camera capture remain available');
    await page.getByRole('link',{name:'Trabajo en entorno real',exact:true}).click();
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await page.screenshot({path:'/results/real-mobile.png',fullPage:true});
    assert.deepEqual(errors,[]);checks.push('No JavaScript errors or mobile overflow');
    fs.writeFileSync('/results/report.json',JSON.stringify({passed:checks.length,checks,errors,source},null,2));
    console.log(JSON.stringify({passed:checks.length,checks}));
  }finally{
    if(shift)await post(`/shifts/${shift.shift_id}/end`,{ended_at:new Date().toISOString(),assessment:{form_id:shift.form_definition.form_id,submitted_at:new Date().toISOString(),answers:{}}}).catch(()=>{});
    await browser.close();
  }
})().catch(e=>{console.error(e);process.exit(1);});
