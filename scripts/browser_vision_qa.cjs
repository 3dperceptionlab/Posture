/* Run in the disposable Playwright container; credentials come from env_file. */
const {chromium}=require('playwright');
const fs=require('fs');
const crypto=require('crypto');
(async()=>{
  const browser=await chromium.launch({headless:true,args:['--use-fake-device-for-media-stream',
    '--use-fake-ui-for-media-stream','--use-file-for-fake-video-capture=/camera.y4m']});
  const errors=[],checks=[],created=[];
  const http='http://172.19.33.30:8080',https='https://172.19.33.30:8443';
  const context=await browser.newContext({viewport:{width:1440,height:1050},ignoreHTTPSErrors:true});
  const page=await context.newPage();
  page.on('pageerror',e=>errors.push(e.message));
  async function login(target){
    await page.goto(target+'/#vision');
    await page.getByRole('heading',{name:'Bienvenido a POSTURE'}).waitFor();
    await page.locator('[name=username]').fill(process.env.POSTURE_ADMIN_USER);
    await page.locator('[name=password]').fill(process.env.POSTURE_ADMIN_PASSWORD);
    await page.getByRole('button',{name:'Entrar en la plataforma'}).click();
    await page.locator('#vision-lab').waitFor();
    await page.waitForFunction(()=>!!document.querySelector('#vision-detail .vision-result'));
  }
  async function jobDone(id){
    let job;
    for(let n=0;n<240;n++){
      const response=await page.request.get((new URL(page.url())).origin+'/api/v1/vision/jobs/'+id);
      job=await response.json();
      if(job.status==='failed')throw new Error(job.error);
      if(job.status==='completed')break;
      await page.waitForTimeout(500);
    }
    if(job.status!=='completed'||job.processed_frames<1)throw new Error(JSON.stringify(job));
    created.push(job);
    return job;
  }
  await login(http);
  await page.getByRole('button',{name:'Cámara USB',exact:true}).click();
  await page.getByRole('heading',{name:'Activa el acceso seguro para usar la cámara'}).waitFor();
  if(!(await page.locator('#vision-open-camera').isDisabled()))throw new Error('HTTP camera was not disabled');
  const certificate=await page.request.get(http+'/api/v1/vision/certificate');
  if(certificate.status()!==200)throw new Error('Certificate unavailable');
  checks.push('HTTP camera guidance and public certificate');
  await page.getByRole('button',{name:'Subir vídeos',exact:true}).click();
  await page.locator('#vision-name').fill('QA visión · subida cliente');
  await page.locator('#vision-file-input').setInputFiles('/project/examples/videos/mmpose-demo.mp4');
  await page.waitForFunction(()=>visionState.jobs.some(j=>j.name==='QA visión · subida cliente'));
  let id=await page.evaluate(()=>visionState.jobs.find(j=>j.name==='QA visión · subida cliente').job_id);
  await jobDone(id);
  await page.waitForFunction(()=>!document.querySelector('#vision-result-video').hidden);
  await page.waitForFunction(()=>document.querySelector('#vision-result-video').videoWidth===1920&&document.querySelector('#vision-result-video').readyState>=2);
  await page.locator('#vision-result-video').evaluate(v=>{v.currentTime=.4;});
  await page.waitForFunction(()=>document.querySelector('#vision-frame-position').textContent.includes('0,4 s'));
  await page.waitForFunction(()=>!document.querySelector('#vision-result-video').seeking);
  await page.locator('.vision-player').screenshot({path:'/results/vision-overlay.png'});
  await page.locator('#vision-detail').scrollIntoViewIfNeeded();
  await page.screenshot({path:'/results/vision-desktop.png',fullPage:true});
  checks.push('Client upload, CUDA detection, synchronized overlay and metrics');
  await page.setViewportSize({width:390,height:844});
  await page.screenshot({path:'/results/vision-mobile.png',fullPage:true});
  if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw new Error('Mobile overflow');
  checks.push('Mobile layout');
  await page.setViewportSize({width:1440,height:1050});
  await page.getByRole('button',{name:'Vídeos del servidor',exact:true}).click();
  await page.locator('[data-vision-folder="videos"]').click();
  await page.locator('#vision-name').fill('QA visión · carpeta servidor');
  await page.getByRole('button',{name:'Analizar todos los vídeos de esta carpeta'}).click();
  await page.waitForFunction(()=>visionState.jobs.some(j=>j.name.startsWith('QA visión · carpeta servidor')));
  id=await page.evaluate(()=>visionState.jobs.find(j=>j.name.startsWith('QA visión · carpeta servidor')).job_id);
  await jobDone(id);checks.push('Server folder import');
  await page.locator('#vision-server-root').selectOption('project');
  await page.locator('[data-vision-import="qa-project-video.mp4"]').waitFor();
  await page.locator('#vision-name').fill('QA visión · raíz del proyecto');
  const privatePath=await page.request.get(http+'/api/v1/vision/files?root=project&path=.runtime');
  if(privatePath.status()!==403)throw new Error('Private project directory listed');
  await page.locator('[data-vision-import="qa-project-video.mp4"]').click();
  await page.waitForFunction(()=>visionState.jobs.some(j=>j.name==='QA visión · raíz del proyecto'));
  id=await page.evaluate(()=>visionState.jobs.find(j=>j.name==='QA visión · raíz del proyecto').job_id);
  await jobDone(id);checks.push('Project-root video import and private directories denied');
  // Use a fresh browser context after HTTPS login so it carries a Secure cookie.
  await context.clearCookies();
  await login(https);
  if(!await page.evaluate(()=>window.isSecureContext))throw new Error('HTTPS is not secure context');
  const cookie=(await context.cookies()).find(c=>c.name==='posture_session');
  if(!cookie?.secure)throw new Error('HTTPS session cookie is not Secure');
  checks.push('HTTPS context and Secure auth cookie');
  await page.getByRole('button',{name:'Cámara USB',exact:true}).click();
  await page.locator('#vision-name').fill('QA visión · cámara directa');
  await page.locator('#vision-camera-mode').selectOption('live');
  await page.locator('#vision-open-camera').click();
  await page.waitForFunction(()=>!document.querySelector('#vision-start-camera').disabled);
  await page.locator('#vision-start-camera').click();
  await page.waitForFunction(()=>visionState.cameraJob?.job_id);
  id=await page.evaluate(()=>visionState.cameraJob.job_id);
  for(let n=0;n<90;n++){
    const j=await(await page.request.get(https+'/api/v1/vision/jobs/'+id)).json();
    if(j.processed_frames>=3)break;
    if(n===89)throw new Error('Live frame processing timed out');
    await page.waitForTimeout(500);
  }
  await page.getByRole('link',{name:'Sesiones',exact:true}).click();
  await page.waitForFunction(()=>location.hash==='#vision'&&visionState.recording);
  await page.locator('#vision-stop-camera').click();
  await page.waitForFunction(()=>!visionState.recording&&!document.querySelector('#vision-start-camera').disabled);
  const live=await jobDone(id);
  if(live.processed_frames<3)throw new Error('Fewer than three live frames');
  checks.push('Live camera: recording, streamed frames, navigation guard, final video');
  await page.locator('#vision-name').fill('QA visión · cámara diferida');
  await page.locator('#vision-camera-mode').selectOption('record');
  await page.locator('#vision-start-camera').click();
  await page.waitForFunction(()=>visionState.recording&&visionState.cameraBytes>0);
  await page.waitForTimeout(1200);
  await page.locator('#vision-stop-camera').click();
  await page.waitForFunction(()=>visionState.jobs.some(j=>j.name==='QA visión · cámara diferida'));
  id=await page.evaluate(()=>visionState.jobs.find(j=>j.name==='QA visión · cámara diferida').job_id);
  const deferred=await jobDone(id);
  checks.push('Deferred camera: record then GPU analysis');
  // Permissions: account creation is QA-scoped, removed before completion.
  const username='visionqa-'+Date.now(),password=crypto.randomBytes(20).toString('hex');
  const user=await page.request.post(https+'/api/v1/users',{data:{username,password,role:'viewer'}});
  if(user.status()!==201)throw new Error('Cannot create QA viewer');
  const viewer=await browser.newContext({ignoreHTTPSErrors:true});
  const auth=await viewer.request.post(https+'/api/v1/auth/login',{data:{username,password}});
  if(auth.status()!==200)throw new Error('QA viewer login failed');
  for(const route of ['/vision/status','/vision/assets','/vision/files','/vision/jobs/'+id+'/video','/vision/jobs/'+id+'/export.json']){
    const denied=await viewer.request.get(https+'/api/v1'+route);
    if(denied.status()!==403)throw new Error('Viewer accessed '+route);
  }
  await viewer.close();await page.request.delete(https+'/api/v1/users/'+username);
  checks.push('Viewer denied originals, pose exports and laboratory management');
  const api=page.request;
  const bad=await api.post(https+'/api/v1/vision/uploads',{data:{name:'qa-invalid.mp4',size_bytes:8}});
  const asset=await bad.json();
  const offset=await api.put(https+'/api/v1/vision/uploads/'+asset.asset_id+'?offset=1',{data:Buffer.from('badvid')});
  if(offset.status()!==409)throw new Error('Invalid upload offset accepted');
  await api.put(https+'/api/v1/vision/uploads/'+asset.asset_id+'?offset=0',{data:Buffer.from('badvideo')});
  await api.post(https+'/api/v1/vision/uploads/'+asset.asset_id+'/complete');
  const badJob=await(await api.post(https+'/api/v1/vision/jobs',{data:{asset_id:asset.asset_id,name:'QA visión · vídeo inválido'}})).json();
  for(let n=0;n<40;n++){
    const j=await(await api.get(https+'/api/v1/vision/jobs/'+badJob.job_id)).json();
    if(j.status==='failed')break;
    if(n===39)throw new Error('Corrupt video did not fail');
    await page.waitForTimeout(500);
  }
  created.push(badJob);
  checks.push('Chunk offsets checked and corrupt video reported');
  // Only delete jobs/assets created by this run. Leave the public demonstration.
  for(const job of created){
    await api.delete(https+'/api/v1/vision/jobs/'+job.job_id);
    const removed=await api.delete(https+'/api/v1/vision/assets/'+job.asset_id);
    if(![202,404].includes(removed.status()))throw new Error('Cannot clean QA asset: '+removed.status());
  }
  if(errors.length)throw new Error('Browser errors: '+JSON.stringify(errors));
  const report={checks,browser_errors:errors,live_frames:live.processed_frames,
    deferred_frames:deferred.processed_frames,mobile_overflow:false,physical_usb_tested:false,
    camera_source:'Chromium virtual camera fed by public MMPose video'};
  fs.writeFileSync('/results/report.json',JSON.stringify(report,null,2));
  await browser.close();console.log(JSON.stringify(report));
})().catch(error=>{console.error(error.stack);process.exit(1);});
