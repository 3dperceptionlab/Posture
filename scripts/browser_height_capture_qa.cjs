/* Disposable Playwright container; camera.y4m is a public sample, credentials via env_file. */
const {chromium}=require('playwright');
const fs=require('fs');
const assert=require('assert/strict');
(async()=>{
  const browser=await chromium.launch({headless:true,args:['--use-fake-device-for-media-stream',
    '--use-fake-ui-for-media-stream','--use-file-for-fake-video-capture=/camera.y4m']});
  const context=await browser.newContext({viewport:{width:1440,height:1050},ignoreHTTPSErrors:true});
  const page=await context.newPage(),base='https://172.19.33.30:8443',prefix='QA altura captura '+Date.now();
  const checks=[],errors=[],operators=[],assets=[],jobs=[];
  let jobRequests=0,jpegRequests=0;
  page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{
    if(r.method()==='POST'&&new URL(r.url()).pathname==='/api/v1/vision/jobs')jobRequests++;
    if(r.method()==='PUT'&&/\/jobs\/[^/]+\/frames\//.test(r.url()))jpegRequests++;
  });
  async function api(path,method='GET',data){
    const r=await page.request.fetch(base+'/api/v1'+path,{method,...(data===undefined?{}:{data})});
    assert(r.ok(),`${method} ${path}: ${r.status()} ${await r.text()}`);
    return r.status()===204?null:r.json();
  }
  async function poll(read,ready,label){
    for(let i=0;i<180;i++){const value=await read();if(ready(value))return value;await page.waitForTimeout(500);}
    throw new Error('Timeout: '+label);
  }
  async function done(id){
    const job=await poll(()=>api('/vision/jobs/'+id),j=>['completed','failed','cancelled'].includes(j.status),'analysis');
    assert.equal(job.status,'completed',job.error);assert(job.processed_frames>0);return job;
  }
  try{
    await page.goto(base+'/#operators');
    await page.locator('[name=username]').fill(process.env.POSTURE_ADMIN_USER);
    await page.locator('[name=password]').fill(process.env.POSTURE_ADMIN_PASSWORD);
    await page.getByRole('button',{name:'Entrar en la plataforma'}).click();
    await page.getByRole('button',{name:'Añadir operario',exact:true}).click();
    assert(await page.locator('[name=stature]').getAttribute('required')!==null);
    await page.locator('#modal-form [name=name]').fill(prefix);
    await page.locator('[name=stature]').fill('175');
    assert.equal(await page.locator('[name=height]').inputValue(),'105');
    assert(await page.locator('[name=height]').evaluate(e=>e.readOnly));
    await page.screenshot({path:'/results/height-automatic.png'});
    await page.getByRole('button',{name:'Crear perfil',exact:true}).click();
    await page.locator('#modal').waitFor({state:'hidden'});
    let op=(await api('/operators')).find(o=>o.display_name===prefix);assert(op);operators.push(op.operator_id);
    assert.equal(op.profile.stature_m,1.75);assert.equal(op.profile.table_height_m,1.05);
    assert.equal(op.profile.table_height_mode,'automatic');
    let p=op.profile;
    p=await api('/operator-profiles/'+p.profile_id,'PUT',{...p,expected_revision:p.revision,stature_m:1.8,table_height_m:.3});
    assert.equal(p.table_height_m,1.08);assert.equal(p.revision,2);
    const stale=await page.request.put(base+'/api/v1/operator-profiles/'+p.profile_id,{data:{...p,expected_revision:1}});
    assert.equal(stale.status(),412);
    const invalid=await page.request.post(base+'/api/v1/operators',{data:{...p,stature_m:0}});
    assert.equal(invalid.status(),422);
    await page.reload();
    await page.locator(`[data-action=edit-profile][data-id="${op.operator_id}"]`).click();
    assert.equal(await page.locator('[name=height]').inputValue(),'108');
    await page.locator('[name=table_height_mode]').selectOption('manual');
    await page.locator('[name=height]').fill('99.5');
    await page.locator('[name=stature]').fill('190');
    assert.equal(await page.locator('[name=height]').inputValue(),'99.5');
    await page.getByRole('button',{name:'Guardar nueva revisión',exact:true}).click();
    await page.locator('#modal').waitFor({state:'hidden'});
    op=(await api('/operators')).find(o=>o.operator_id===op.operator_id);
    assert.equal(op.profile.table_height_m,.995);assert.equal(op.profile.stature_m,1.9);
    assert.equal(op.profile.table_height_rule,null);
    const legacy=await api('/operators','POST',{display_name:prefix+' legacy',presentation_pose:p.presentation_pose,table_height_m:.95});
    operators.push(legacy.operator_id);assert.equal(legacy.stature_m,null);assert.equal(legacy.table_height_mode,'manual');
    checks.push('Operator UI: required stature, automatic preview and server computation, manual override, revision conflicts and legacy compatibility');

    await page.getByRole('link',{name:'Laboratorio de visión',exact:true}).click();
    await page.getByRole('button',{name:'Cámara USB',exact:true}).click();
    assert.equal(await page.locator('#vision-camera-mode').inputValue(),'manual');
    assert.equal(await page.locator('#vision-camera-mode option').count(),3);
    await page.locator('#vision-name').fill(prefix+' manual');
    await page.locator('#vision-operator').selectOption(op.operator_id);
    await page.locator('#vision-fps').selectOption('2');
    await page.locator('#vision-confidence').selectOption('0.6');
    await page.locator('#vision-open-camera').click();
    await page.waitForFunction(()=>!document.querySelector('#vision-start-camera').disabled);
    await page.locator('#vision-start-camera').click();
    await page.waitForFunction(()=>visionState.recording&&visionState.cameraBytes>0);
    const aid=await page.evaluate(()=>visionState.cameraAsset.asset_id);assets.push(aid);
    assert.equal(jobRequests,0);assert.equal(jpegRequests,0);
    assert.equal((await api('/vision/jobs')).filter(j=>j.asset_id===aid).length,0);
    await page.locator('#vision-stop-camera').click();
    await page.waitForFunction(()=>!visionState.saving&&!visionState.recording);
    assert.equal(jobRequests,0);assert.equal(jpegRequests,0);
    let asset=(await api('/vision/assets')).find(a=>a.asset_id===aid);
    assert.equal(asset.status,'ready');assert(asset.size_bytes>0);assert(!asset.analysis_requested_at);
    assert.equal((await api('/vision/jobs')).filter(j=>j.asset_id===aid).length,0);
    await page.reload();
    await page.getByRole('button',{name:'Cámara USB',exact:true}).click();
    const processButton=page.locator(`#vision-pending [data-vision-analyze="${aid}"]`);
    await processButton.waitFor();
    assert.equal(await page.locator('#vision-camera-mode').inputValue(),'manual');
    await page.screenshot({path:'/results/capture-pending.png',fullPage:true});
    await processButton.click();
    let job=await poll(()=>api('/vision/jobs'),list=>list.some(j=>j.asset_id===aid),'manual request');
    job=job.find(j=>j.asset_id===aid);jobs.push(job.job_id);await done(job.job_id);
    assert.equal(job.name,prefix+' manual');assert.equal(job.operator_id,op.operator_id);
    assert.equal(job.options.sample_fps,2);assert.equal(job.options.confidence,.6);
    asset=(await api('/vision/assets')).find(a=>a.asset_id===aid);assert(asset.analysis_requested_at);
    checks.push('Default capture-only: zero job/JPEG requests during and after recording; persisted original/options and manual GPU analysis after reload');

    for(const mode of ['record','live']){
      await page.locator('#vision-camera-mode').selectOption(mode);
      await page.locator('#vision-name').fill(prefix+' '+mode);
      // Reload above closed the stream; open only when needed.
      if(await page.locator('#vision-start-camera').isDisabled()){
        await page.locator('#vision-open-camera').click();
        await page.waitForFunction(()=>!document.querySelector('#vision-start-camera').disabled);
      }
      const requestsBefore=jobRequests;
      await page.locator('#vision-start-camera').click();
      await page.waitForFunction(()=>visionState.recording&&visionState.cameraBytes>0);
      const capture=await page.evaluate(()=>({asset:visionState.cameraAsset.asset_id,job:visionState.cameraJob?.job_id}));
      assets.push(capture.asset);
      if(mode==='record')assert.equal(jobRequests,requestsBefore);
      else{
        assert(capture.job);jobs.push(capture.job);assert(jobRequests>requestsBefore);
        await poll(()=>api('/vision/jobs/'+capture.job),j=>j.processed_frames>0,'live inference');
        assert(jpegRequests>0);
      }
      await page.locator('#vision-stop-camera').click();
      await page.waitForFunction(()=>!visionState.saving&&!visionState.recording);
      const found=await poll(()=>api('/vision/jobs'),list=>list.some(j=>j.asset_id===capture.asset),'automatic analysis');
      const analysis=found.find(j=>j.asset_id===capture.asset);if(!jobs.includes(analysis.job_id))jobs.push(analysis.job_id);
      await done(analysis.job_id);
      checks.push(mode==='record'?'Capture then automatic processing only after stop':'Live capture still streams frames and produces GPU inference');
    }
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await page.screenshot({path:'/results/capture-mobile.png',fullPage:true});
    assert.deepEqual(errors,[]);checks.push('No browser JavaScript errors or mobile overflow');
    fs.writeFileSync('/results/report.json',JSON.stringify({passed:checks.length,checks,jobs,errors},null,2));
    console.log(JSON.stringify({passed:checks.length,checks}));
  }finally{
    if(await page.evaluate(()=>typeof visionState!=='undefined'&&visionState.recording).catch(()=>false)){
      await page.evaluate(()=>visionStopCamera()).catch(()=>{});
    }
    for(const aid of assets){
      const list=await api('/vision/jobs').catch(()=>[]);
      for(const j of list.filter(j=>j.asset_id===aid&&!['completed','failed','cancelled'].includes(j.status))){
        await api('/vision/jobs/'+j.job_id+'/cancel','POST').catch(()=>{});
        await poll(()=>api('/vision/jobs/'+j.job_id),v=>['completed','failed','cancelled'].includes(v.status),'cancel cleanup').catch(()=>{});
      }
      await api('/vision/assets/'+aid,'DELETE');
    }
    for(const oid of operators)await api('/operators/'+oid,'DELETE');
    await browser.close();
  }
})().catch(e=>{console.error(e);process.exit(1);});
