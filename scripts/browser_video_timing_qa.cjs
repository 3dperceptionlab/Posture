const {chromium}=require('playwright');
const fs=require('fs');
(async()=>{
  const browser=await chromium.launch({headless:true});
  const page=await browser.newPage({viewport:{width:1440,height:1050}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://api:8080/#vision');
  await page.locator('[name=username]').fill(process.env.POSTURE_ADMIN_USER);
  await page.locator('[name=password]').fill(process.env.POSTURE_ADMIN_PASSWORD);
  await page.getByRole('button',{name:'Entrar en la plataforma'}).click();
  await page.locator('#vision-lab').waitFor();
  await page.locator('[data-vision-job="'+process.env.POSTURE_SYNC_JOB+'"]').click();
  await page.waitForFunction(()=>{
    const v=document.querySelector('#vision-result-video');
    return v?.videoWidth===1920&&v.readyState>=2&&visionState.samples.length>120;
  });
  const seeks=[];
  for(const target of [0,.26,1,5,10,15,20,25,28.4]){
    await page.locator('#vision-result-video').evaluate((video,t)=>{video.pause();video.currentTime=t;},target);
    await page.waitForFunction(t=>{
      const v=document.querySelector('#vision-result-video');
      return !v.seeking&&Number.isFinite(v.posturePresentedTime)&&Math.abs(v.posturePresentedTime-t)<.09&&!!visionState.drawSample;
    },target);
    const observation=await page.evaluate(()=>{
      const video=document.querySelector('#vision-result-video');
      return {displayed_frame_s:video.posturePresentedTime,pose_s:visionState.drawSample?.offset_s,
        source_frame_index:visionState.drawSample?.source_frame_index,
        metrics_frame_s:visionState.drawSample?.offset_s};
    });
    if(observation.pose_s>observation.displayed_frame_s+.000001)throw new Error('Future pose after seek: '+JSON.stringify(observation));
    if(observation.displayed_frame_s-observation.pose_s>.321)throw new Error('Stale pose after seek: '+JSON.stringify(observation));
    seeks.push({target_s:target,...observation});
    if([5,15,25].includes(target))await page.locator('.vision-player').screenshot({path:'/results/overlay-'+target+'s.png'});
  }
  await page.locator('#vision-result-video').evaluate(video=>{video.currentTime=3;});
  await page.waitForFunction(()=>{const v=document.querySelector('#vision-result-video');return !v.seeking&&Math.abs(v.posturePresentedTime-3)<.09;});
  await page.evaluate(()=>{
    const video=document.querySelector('#vision-result-video');window.timingAudit=[];
    const next=()=>video.requestVideoFrameCallback((_,meta)=>{
      window.timingAudit.push({video_s:meta.mediaTime,pose_s:visionState.drawSample?.offset_s??null});
      if(!video.paused)next();
    });
    next();video.playbackRate=1.5;return video.play();
  });
  await page.waitForTimeout(3200);
  const playback=await page.evaluate(()=>{document.querySelector('#vision-result-video').pause();return window.timingAudit;});
  if(playback.length<30)throw new Error('Playback did not advance enough');
  const future=playback.filter(f=>f.pose_s!=null&&f.pose_s>f.video_s+.000001);
  const stale=playback.filter(f=>f.pose_s!=null&&f.video_s-f.pose_s>.321);
  const visible=playback.filter(f=>f.pose_s!=null);
  if(visible.length<playback.length*.95)throw new Error('The overlay was not visible during playback');
  if(future.length||stale.length||errors.length)throw new Error(JSON.stringify({future,stale,errors}));
  const report={job_id:process.env.POSTURE_SYNC_JOB,seeks,playback_frames:playback.length,
    visible_pose_frames:visible.length,future_poses:future.length,stale_poses:stale.length,browser_errors:errors};
  fs.writeFileSync('/results/browser-report.json',JSON.stringify(report,null,2));
  await browser.close();console.log(JSON.stringify(report));
})().catch(e=>{console.error(e.stack);process.exit(1);});
