// NODE_PATH=<existing playwright node_modules> node tests/board_freshness_browser.cjs fixture.html evidence-dir [owner.html ...]
const {chromium}=require('playwright');
const fs=require('fs'),path=require('path'),assert=require('assert/strict');
(async()=>{
 const out=process.argv[3];fs.mkdirSync(out,{recursive:true});const snapshot=path.join(out,'fixtures');fs.mkdirSync(snapshot,{recursive:true});const files=[process.argv[2],...process.argv.slice(4)].map((file,i)=>{const target=path.join(snapshot,`${i}-${path.basename(file)}`);fs.copyFileSync(file,target);return target});const browser=await chromium.launch();const results=[];
 try{
  const context=await browser.newContext({permissions:['clipboard-read','clipboard-write']});
  await context.addInitScript(()=>{window.freshnessIntervals=[];const original=window.setInterval;window.setInterval=(fn,ms,...args)=>{window.freshnessIntervals.push(ms);return original(fn,ms,...args)}});
  const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
  for(const file of files)for(const scheme of ['light','dark'])for(const width of [320,390,768,1440]){
   await page.setViewportSize({width,height:1000});await page.emulateMedia({colorScheme:scheme});await page.goto('file://'+path.resolve(file),{waitUntil:'domcontentloaded'});
   const stamps=page.locator('[data-refreshed-at]');if(await stamps.count()===0){assert.equal(await page.locator('.orchestration-freshness').getAttribute('data-freshness'),'grey');assert((await page.locator('.orchestration-freshness').innerText()).includes('Last updated unavailable'));assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));results.push({file:path.basename(file),width,scheme,unknown:true,passed:true});continue;}
   const stamp=await stamps.first().getAttribute('data-refreshed-at');const base=Date.parse(stamp);
   for(const [age,state] of [[0,'green'],[3599999,'green'],[3600000,'yellow'],[86399999,'yellow'],[86400000,'red'],[-1,'grey']]){
    await page.evaluate(now=>updateDashboardFreshness(now),base+age);
    assert.equal(await stamps.first().locator('..').getAttribute('data-freshness'),state);
   }
   await page.evaluate(now=>updateDashboardFreshness(now),base+3600000);
   const summary=stamps.first().locator('summary');assert.equal(await summary.innerText(),'Last updated 1 hour ago');assert((await stamps.first().ariaSnapshot()).includes('group: Last updated 1 hour ago'));
   await summary.focus();await page.keyboard.press('Enter');assert(await stamps.first().evaluate(d=>d.open));
   assert.equal(await stamps.first().locator('time').getAttribute('datetime'),stamp);
   assert((await stamps.first().locator('time').innerText()).includes('UTC'));
   assert.equal(await stamps.first().locator('..').locator('[data-refresh-link]').innerText(),'↻ Update');
   const panel=stamps.first().locator('xpath=ancestor::section[1]');
   const preview=panel.locator('[data-orchestration-preview]');
   if(await preview.count()){
    await preview.locator('summary').click();assert(await preview.evaluate(d=>d.open));assert(await panel.locator('[data-orchestration-prompt]').evaluate(t=>{const r=t.getBoundingClientRect();return r.width>100&&r.left>=0&&r.right<=innerWidth+1}));
    const boxes=await page.evaluate(()=>Array.from(document.querySelectorAll('.orchestration-footer')).map(f=>{const a=f.querySelector('[data-orchestration-preview]>summary').getBoundingClientRect(),b=f.querySelector('.orchestration-freshness').getBoundingClientRect();return {overlap:a.left<b.right&&a.right>b.left&&a.top<b.bottom&&a.bottom>b.top,small:parseFloat(getComputedStyle(f).fontSize)<parseFloat(getComputedStyle(f.closest('.orchestration-panel')).fontSize)}}));
    assert(boxes.every(b=>!b.overlap&&b.small),'footer labels overlap or are not smaller');
   }
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'horizontal overflow');
   assert(await page.evaluate(()=>freshnessIntervals.includes(30000)));
   await page.reload({waitUntil:'domcontentloaded'});assert.equal(await stamps.first().getAttribute('data-refreshed-at'),stamp);
   await page.evaluate(now=>{Date.now=()=>now;document.dispatchEvent(new Event('visibilitychange'))},base+86400000);
   assert.equal(await stamps.first().locator('..').getAttribute('data-freshness'),'red');
   if(file===files[0]&&(width===390||width===1440))await page.screenshot({path:path.join(out,`${width}-${scheme}.png`),fullPage:true});
   results.push({file:path.basename(file),width,scheme,passed:true});
  }
  await page.clock.install({time:new Date('2026-10-07T10:59:45.000Z')});
  await page.goto('file://'+path.resolve(files[0]));
  assert.equal(await page.locator('.orchestration-freshness').first().getAttribute('data-freshness'),'green');
  await page.clock.fastForward(30000);
  assert.equal(await page.locator('.orchestration-freshness').first().getAttribute('data-freshness'),'yellow');
  const stamps=page.locator('[data-refreshed-at]');const first=stamps.first();const second=stamps.nth(1);const stamp=await first.getAttribute('data-refreshed-at');
  await first.evaluate(e=>e.dataset.refreshedAt='invalid');await page.evaluate(()=>updateDashboardFreshness());assert.equal(await first.locator('..').getAttribute('data-freshness'),'grey');
  await first.evaluate((e,s)=>e.dataset.refreshedAt=s,stamp);await second.evaluate(e=>e.dataset.refreshedAt='2026-10-07T11:00:00+01:00');
  await page.evaluate(()=>updateDashboardFreshness(Date.parse('2026-10-07T10:30:00Z')));assert.equal(await second.locator('..').getAttribute('data-freshness'),'green');
  assert.deepEqual(errors,[]);fs.writeFileSync(path.join(out,'freshness-results.json'),JSON.stringify(results,null,2));console.log(`${results.length} freshness browser layout cases passed; boundaries, disclosure, reload, visibility, invalid and timezone checked`);
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
