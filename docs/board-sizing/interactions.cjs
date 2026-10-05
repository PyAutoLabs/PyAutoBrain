const {chromium}=require('playwright');const fs=require('fs');const assert=require('assert/strict');
(async()=>{
 const browser=await chromium.launch();const context=await browser.newContext();await context.route('**/*',r=>r.abort());
 const page=await context.newPage();const results=[];
 const css=fs.readFileSync('theme.css','utf8'),js=fs.readFileSync('theme.js','utf8');
 for(const colorScheme of ['light','dark']) for(const width of [390,735,736,768,820,1024,1440]){
  await page.emulateMedia({colorScheme});await page.setViewportSize({width,height:900});
  const long='https://example.invalid/'+'very_long_title_and_path_'.repeat(18);
  await page.setContent(`<meta name="viewport" content="width=device-width,initial-scale=1"><style>${css}</style><header class="hero"><h1>${long}</h1><p>Centred masthead</p></header><p id="prose">${long} ${'Explanatory prose. '.repeat(50)}</p><p class="verdict">A status panel</p><div class="task"><button class="copy" data-cmd="Use the health skill.">Copy</button><p>${long}</p></div><details><summary>${long}</summary><div class="board-prose">${long}</div><pre>${long}</pre></details><div id="scroller" role="region" aria-label="Dense table" tabindex="0" style="max-width:100%;overflow-x:auto"><table style="min-width:740px"><tr><th>Topic</th><th>Status</th><th>Action</th></tr><tr><td>${long}</td><td>Unknown</td><td><button id="action">Inspect</button></td></tr></table></div><script>${js}</script>`);
  await page.evaluate(()=>Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async t=>{window.copied=t}}}));
  const summary=page.locator('summary');await summary.focus();await page.keyboard.press('Enter');assert(await page.locator('details').evaluate(e=>e.open));
  await page.locator('button.copy').focus();await page.keyboard.press('Enter');assert.equal(await page.evaluate(()=>window.copied),'Use the health skill.');
  await page.locator('#action').focus();const action=await page.locator('#action').boundingBox();assert(action.x>=0&&action.x+action.width<=width+1);
  const m=await page.evaluate(()=>({overflow:document.documentElement.scrollWidth-innerWidth,body:document.body.getBoundingClientRect().width,prose:document.querySelector('#prose').getBoundingClientRect().width,measure:parseFloat(getComputedStyle(document.querySelector('#prose')).maxWidth),gutter:parseFloat(getComputedStyle(document.body).paddingLeft)}));
  assert(m.overflow<=1);assert.equal(m.body,Math.min(width,1240));assert(m.prose<=m.measure+.1);assert.equal(m.gutter,width<736?16:24);
  if(width===390){await page.locator('#scroller').evaluate(e=>e.scrollLeft=0);await page.locator('#scroller').focus();await page.keyboard.press('ArrowRight');await page.waitForTimeout(120);assert(await page.locator('#scroller').evaluate(e=>e.scrollLeft>0));}
  results.push({case:'stress',width,colorScheme,...m,keyboard:'pass'});
 }
 for(const key of ['brain','ears','pulse']) for(const colorScheme of ['light','dark']){
  await page.emulateMedia({colorScheme});await page.setViewportSize({width:390,height:900});await page.setContent(fs.readFileSync(`after/${key}.html`,'utf8'));
  await page.evaluate(()=>Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async t=>{window.copied=t}}}));
  const summary=page.locator('details > summary').filter({visible:true}).first();await summary.focus();const initial=await summary.evaluate(e=>e.parentElement.open);await page.keyboard.press('Enter');assert.notEqual(await summary.evaluate(e=>e.parentElement.open),initial);
  const button=page.locator('button.copy,button.copy-action,button[data-copy],#copy-checkin').filter({visible:true}).first();await button.focus();await page.keyboard.press('Enter');await page.waitForTimeout(100);const copied=await page.evaluate(()=>window.copied);assert(copied?.length>0,`${key} clipboard`);
  const box=await button.boundingBox();assert(box.x>=0&&box.x+box.width<=391);
  results.push({case:'published',key,colorScheme,disclosure:'pass',copy:'pass',reachable:'pass'});
 }
 fs.writeFileSync('interaction-results.json',JSON.stringify(results,null,2));console.log(`${results.length} interaction/stress checks passed`);await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
