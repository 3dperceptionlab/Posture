const {chromium}=require('playwright');
const assert=require('assert/strict');
const fs=require('fs');
(async()=>{
 const browser=await chromium.launch({headless:true});
 const context=await browser.newContext({ignoreHTTPSErrors:true,viewport:{width:1440,height:1050}});
 const video=fs.readFileSync('/results/input.webm');
 await context.route('**/qa-camera-source.webm',route=>route.fulfill({body:video,contentType:'video/webm'}));
 await context.addInitScript(()=>{
   const media=navigator.mediaDevices;
   Object.defineProperty(media,'enumerateDevices',{value:async()=>['camera-a','camera-b'].map((id,i)=>({deviceId:id,groupId:id,kind:'videoinput',label:'QA USB '+(i+1)}))});
   Object.defineProperty(media,'getUserMedia',{value:async constraints=>{
     const id=constraints.video.deviceId?.exact||'camera-a';
     if(id==='camera-b'&&window.failSecondCamera)throw new DOMException('QA device unavailable','NotReadableError');
     const source=document.createElement('video');source.src='/qa-camera-source.webm';source.muted=true;source.loop=true;await source.play();
     const canvas=document.createElement('canvas');canvas.width=640;canvas.height=360;
     const ctx=canvas.getContext('2d'),draw=()=>{ctx.drawImage(source,0,0,640,360);ctx.fillStyle=id==='camera-a'?'red':'blue';ctx.fillRect(0,0,20,20);};
     draw();const timer=setInterval(draw,40),stream=canvas.captureStream(25),track=stream.getVideoTracks()[0];
     const settings=track.getSettings.bind(track),stop=track.stop.bind(track);
     track.getSettings=()=>({...settings(),deviceId:id,frameRate:25});
     track.stop=()=>{clearInterval(timer);source.pause();stop();};
     return stream;
   }});
 });
 const page=await context.newPage(),base='https://172.19.33.30:8443',errors=[],assets=[],checks=[];
 page.on('pageerror',error=>errors.push(error.message));
 async function api(path,method='GET',data){const r=await page.request.fetch(base+'/api/v1/vision'+path,{method,...(data===undefined?{}:{data})});assert(r.ok(),await r.text());return r.json();}
 async function poll(fn,ready){for(let n=0;n<120;n++){const value=await fn();if(ready(value))return value;await page.waitForTimeout(500);}throw new Error('Timeout');}
 try{
   await page.goto(base+'/#vision');
   await page.getByRole('button',{name:'Cámara USB',exact:true}).click();
   assert.equal(await page.locator('#vision-camera-mode').inputValue(),'manual');
   await page.locator('#vision-fps').selectOption('2');
   await page.locator('#vision-name').fill('QA dual USB '+Date.now());
   await page.locator('#vision-add-camera').click();
   await page.waitForFunction(()=>visionState.secondaryStream&&!visionState.multiOpening);
   assert.equal(await page.locator('#vision-camera-mode').inputValue(),'record');
   assert.equal(await page.locator('#vision-camera-device-2').inputValue(),'camera-b');
   await page.locator('#vision-start-camera').click();
   await page.waitForFunction(()=>visionState.recording&&visionState.multiCapture.sides.every(side=>side.bytes>0));
   let capture=await page.evaluate(()=>({assets:visionState.multiCapture.sides.map(side=>side.asset.asset_id),start_delta:Math.abs(visionState.multiCapture.sides[0].startedAt-visionState.multiCapture.sides[1].startedAt)}));
   assets.push(...capture.assets);assert(capture.start_delta<100);
   await page.waitForTimeout(1800);
   await page.locator('#vision-stop-camera').click();
   await page.waitForFunction(()=>!visionState.saving&&!visionState.recording);
   const pair=await api('/assets');const a=pair.find(a=>a.asset_id===capture.assets[0]),b=pair.find(a=>a.asset_id===capture.assets[1]);
   assert.equal(a.status,'ready');assert.equal(b.status,'ready');
   assert.equal(a.capture.group_id,b.capture.group_id);assert.equal(a.capture.camera_index,1);assert.equal(b.capture.camera_index,2);
   const jobs=await poll(()=>api('/jobs'),list=>capture.assets.every(a=>list.some(j=>j.asset_id===a)));
   const ids=jobs.filter(j=>capture.assets.includes(j.asset_id)).map(j=>j.job_id);assert.equal(ids.length,2);
   await poll(()=>api('/jobs'),list=>ids.every(id=>list.find(j=>j.job_id===id)?.status==='completed'));
   for(const id of ids){const data=await api('/jobs/'+id+'/results');assert(data.samples.length>0);}
   const times=await page.evaluate(()=>visionState.multiCapture.sides.map(side=>({start:side.startedAt,stop:side.stoppedAt})));
   assert(Math.abs(times[0].stop-times[1].stop)<100);
   checks.push({dual_recording:true,independent_gpu_analyses:2,shared_capture_group:true,start_delta_ms:capture.start_delta,stop_delta_ms:Math.abs(times[0].stop-times[1].stop)});
   await page.locator('#vision-camera-mode').selectOption('manual');
   await page.locator('#vision-start-camera').click();
   await page.waitForFunction(()=>visionState.recording&&visionState.multiCapture.sides.every(side=>side.bytes>0));
   capture=await page.evaluate(()=>({assets:visionState.multiCapture.sides.map(side=>side.asset.asset_id)}));assets.push(...capture.assets);
   await page.locator('#vision-stop-camera').click();await page.waitForFunction(()=>!visionState.saving&&!visionState.recording);
   assert(!(await api('/jobs')).some(j=>capture.assets.includes(j.asset_id)));
   checks.push({dual_manual_stores_both_without_inference:true});
   await page.setViewportSize({width:390,height:1000});
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
   await page.locator('.vision-camera-grid').screenshot({path:'/results/dual-mobile.png'});
   await page.locator('#vision-add-camera').click();
   assert.equal(await page.evaluate(()=>visionState.secondaryStream),null);
   assert.equal(await page.locator('#vision-camera-mode').inputValue(),'manual');
   await page.locator('#vision-start-camera').click();
   await page.waitForFunction(()=>visionState.recording&&visionState.cameraBytes>0);
   assets.push(await page.evaluate(()=>visionState.cameraAsset.asset_id));
   await page.locator('#vision-stop-camera').click();await page.waitForFunction(()=>!visionState.recording&&!visionState.saving);
   checks.push({single_camera_preserved:true,mobile_no_overflow:true});
   assert.deepEqual(errors,[]);
   console.log(JSON.stringify({checks,errors}));fs.writeFileSync('/results/report.json',JSON.stringify({checks,errors},null,2));
 }catch(error){
   console.error(JSON.stringify({errors,state:await page.evaluate(()=>({error:document.querySelector('#vision-camera-error')?.textContent,dual:visionState.dualCamera,opening:visionState.multiOpening,primary:!!visionState.stream,secondary:!!visionState.secondaryStream})).catch(()=>null)}));
   throw error;
 }finally{
   if(await page.evaluate(()=>visionState.recording).catch(()=>false))await page.evaluate(()=>visionStopCamera()).catch(()=>{});
   for(const asset of assets)await api('/assets/'+asset,'DELETE').catch(()=>{});
   await browser.close();
 }
})().catch(error=>{console.error(error);process.exitCode=1;});
