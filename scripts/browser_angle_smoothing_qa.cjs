const {chromium}=require('playwright');
const assert=require('assert/strict');
const fs=require('fs');
(async()=>{
 const browser=await chromium.launch({headless:true});
 const page=await browser.newPage({viewport:{width:1440,height:1050}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 const base=process.env.POSTURE_TEST_URL||'http://api:8080';
 try {
   await page.goto(base+'/#vision');
   await page.locator('#vision-angle-window').waitFor();
   const jid=await page.evaluate(()=>visionState.jobs.find(j=>j.name==='Con Robot')?.job_id);
   assert(jid,'Con Robot fixture must exist');
   await page.locator(`[data-vision-job="${jid}"]`).click();
   await page.waitForFunction(()=>visionState.samples.length>=140);
   await page.evaluate(()=>clearInterval(visionState.poll));
   await page.waitForFunction(()=>!visionState.polling);
   const checks=[];
   for(const width of [1440,390]){
     await page.setViewportSize({width,height:1050});
     const result=await page.evaluate(()=>{
       const video=document.querySelector('#vision-result-video');video.pause();
       const stored=visionState.samples,original=JSON.stringify(stored);
       const base=stored.find(r=>r.metrics?.angles)?.metrics;
       const make=(t,value,persons=1)=>({offset_s:t,persons_detected:persons,selection_confidence:.9,keypoints:[],scores:[],
         metrics:{...base,rula:persons?3:null,reba:persons?4:null,angles:Object.fromEntries(visionAngleFields.map(([,key])=>[key,value]))}});
       const rows=[make(0,10),make(.2,20),make(.4,null,0),make(.6,30),make(.8,900),make(2,40)];
       const untouched=JSON.stringify(rows);
       visionState.samples=rows;visionState.angleWindowS=1;visionState.drawSample=undefined;
       const mean=visionSmoothedAngles(rows,rows[3],1);
       if(mean.trunk!==20)throw new Error('Invalid causal mean: '+JSON.stringify(mean));
       if(visionSmoothedAngles(rows,rows[3],0).trunk!==30)throw new Error('Raw mode changed');
       if(visionSmoothedAngles(rows,rows[5],1).trunk!==40)throw new Error('History crossed a long gap');
       if(visionSmoothedAngles(rows,rows[2],1).trunk!==null)throw new Error('Missing detection was imputed');
       const partial=make(.6,30);partial.metrics.angles.neck=null;
       if(visionSmoothedAngles(rows,partial,1).neck!==null)throw new Error('Missing joint was imputed');
       visionShowSample(rows[3]);
       const grid=document.querySelector('.vision-angle-grid'),cells=[...grid.querySelectorAll('strong')];
       if(cells[0].textContent!=='20°')throw new Error('Smoothed angle not rendered: '+cells[0].textContent);
       const before=grid.getBoundingClientRect(),height=document.querySelector('#vision-frame-metrics').getBoundingClientRect().height;
       for(let i=0;i<20;i++){
         visionShowSample(null);
         if(document.querySelector('.vision-angle-grid')!==grid)throw new Error('Grid replaced on dropout');
         if(!cells.every((cell,n)=>cell===grid.querySelectorAll('strong')[n]&&cell.textContent==='—'))throw new Error('Missing values/layout unstable');
         const after=grid.getBoundingClientRect();
         if(Math.abs(after.height-before.height)>.1||Math.abs(after.top-before.top)>.1)throw new Error('Dropout changed layout: '+JSON.stringify({before:before.toJSON(),after:after.toJSON()}));
         if(Math.abs(document.querySelector('#vision-frame-metrics').getBoundingClientRect().height-height)>.1)throw new Error('Metric holder height changed');
         visionShowSample(rows[3]);
       }
       if(JSON.stringify(rows)!==untouched)throw new Error('Input metrics mutated');
       if(JSON.stringify(stored)!==original)throw new Error('Stored samples mutated');
       visionState.samples=stored;visionState.drawSample=undefined;
       return {causal_one_second_mean:true,raw_mode:true,no_gap_carry:true,missing_values:true,persistent_nodes:true,dropouts:20,raw_data_unchanged:true};
     });
     checks.push({width,...result});
     assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
   }
   await page.selectOption('#vision-angle-window','0');
   assert.equal(await page.evaluate(()=>visionState.angleWindowS),0);
   await page.selectOption('#vision-angle-window','1');
   // Actual VFR playback: the overlay clock must retain its no-future-sample rule.
   await page.locator('#vision-result-video').evaluate(video=>{video.currentTime=5;});
   await page.waitForFunction(()=>{
     const v=document.querySelector('#vision-result-video');
     return !v.seeking&&Math.abs(v.posturePresentedTime-5)<.09&&visionState.drawSample;
   });
   const timing=await page.evaluate(()=>{
     const video=document.querySelector('#vision-result-video');
     return {presented_time_s:video.posturePresentedTime,pose_s:visionState.drawSample.offset_s};
   });
   assert(timing.pose_s<=timing.presented_time_s+1e-6);
   await page.locator('#vision-frame-metrics').screenshot({path:'/results/mobile.png'});
   await page.setViewportSize({width:1440,height:1050});
   await page.locator('#vision-frame-metrics').screenshot({path:'/results/desktop.png'});
   assert.deepEqual(errors,[]);
   const report={checks,selector_works:true,real_vfr_playback:timing,errors};
   fs.writeFileSync('/results/report.json',JSON.stringify(report,null,2));
   console.log(JSON.stringify(report));
 } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
