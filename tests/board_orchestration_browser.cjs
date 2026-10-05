// Usage: NODE_PATH=<playwright node_modules> node tests/board_orchestration_browser.cjs <fixture.html> <evidence-dir>
const {chromium}=require('playwright');
const fs=require('fs'),http=require('http'),path=require('path'),assert=require('assert/strict');
(async()=>{
 const fixture=fs.readFileSync(process.argv[2]);const out=process.argv[3];fs.mkdirSync(out,{recursive:true});
 const server=http.createServer((req,res)=>{res.setHeader('Content-Type','text/html; charset=utf-8');res.end(fixture)});
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const browser=await chromium.launch();
 try{
  const context=await browser.newContext({permissions:['clipboard-read','clipboard-write']});const page=await context.newPage();
  const errors=[];page.on('pageerror',e=>errors.push(e.message));const results=[];
  const url=`http://127.0.0.1:${server.address().port}`;
  for(const scheme of ['light','dark'])for(const width of [390,768,820,1024,1440]){
   await page.setViewportSize({width,height:1000});await page.emulateMedia({colorScheme:scheme});await page.goto(url);
   const first=page.locator('#orchestration-first'),second=page.locator('#orchestration-second');
   const direction=first.locator('[data-orchestration-direction]'),preview=first.locator('[data-orchestration-prompt]');
   const base=await preview.inputValue();const other=await second.locator('[data-orchestration-prompt]').inputValue();
   const focus='Review <script>unsafe()</script> & "quotes"\nThen 🧠 science.';
   await direction.fill(focus);
   assert.equal(await preview.inputValue(),base+'\n\nOptional direction (user context):\n'+focus);
   assert.equal(await second.locator('[data-orchestration-prompt]').inputValue(),other);
   const button=first.locator('[data-orchestration-copy]');await button.focus();await page.keyboard.press('Enter');
   await page.waitForFunction(()=>document.querySelector('.orchestration-status').textContent.startsWith('Prompt copied'));
   assert.equal(await page.evaluate(()=>navigator.clipboard.readText()),await preview.inputValue());
   assert((await preview.inputValue()).includes('https://github.com/Example/Work'));
   assert.equal(await first.locator('.orchestration-links a').count(),2);
   await direction.fill('');assert.equal(await preview.inputValue(),base);
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
   assert(await button.evaluate(b=>{const r=b.getBoundingClientRect();return r.height>=44&&r.left>=0&&r.right<=innerWidth+1}));
   if(width===390||width===1440)await page.screenshot({path:path.join(out,`${width}-${scheme}.png`)});
   results.push({scheme,width,passed:true});
  }
  // Clipboard denial still leaves the exact complete request selected for manual copy.
  await page.goto(url);
  await page.evaluate(()=>{Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async()=>{throw Error('denied')}}});document.execCommand=()=>false});
  await page.locator('#orchestration-first [data-orchestration-direction]').fill('Manual 🧠\ncopy');
  await page.locator('#orchestration-first [data-orchestration-copy]').click();
  await page.waitForFunction(()=>document.querySelector('.orchestration-status').textContent.startsWith('Copy unavailable'));
  assert(await page.locator('#orchestration-first [data-orchestration-preview]').evaluate(d=>d.open));
  assert(await page.locator('#orchestration-first [data-orchestration-prompt]').evaluate(t=>t.selectionStart===0&&t.selectionEnd===t.value.length));
  // Whole Unicode prompts are downloadable when over budget; nothing is truncated or copied.
  await page.goto(url);
  await page.evaluate(()=>{window.copyCalls=0;Object.defineProperty(navigator,'clipboard',{value:{writeText:async()=>{window.copyCalls++}}})});
  await page.locator('#orchestration-first [data-orchestration-direction]').fill('🧠'.repeat(50001));
  await page.locator('#orchestration-first [data-orchestration-copy]').click();
  assert.equal(await page.evaluate(()=>window.copyCalls),0);
  const saved=await page.locator('#orchestration-first-budget-status a').evaluate(async a=>(await fetch(a.href)).text());
  assert.equal(saved,await page.locator('#orchestration-first [data-orchestration-prompt]').inputValue());
  await page.locator('#orchestration-second [data-orchestration-copy]').click();
  assert.equal(await page.locator('#orchestration-first-budget-status').count(),1);
  // Editing while a clipboard permission response is pending must not claim the latest text was copied.
  await page.goto(url);
  await page.evaluate(()=>Object.defineProperty(navigator,'clipboard',{value:{writeText:()=>new Promise(resolve=>window.finishCopy=resolve)}}));
  await page.locator('#orchestration-first [data-orchestration-copy]').click();
  await page.locator('#orchestration-first [data-orchestration-direction]').fill('Updated while permission pending');
  await page.evaluate(()=>window.finishCopy());
  await page.waitForFunction(()=>document.querySelector('.orchestration-status').textContent.includes('previous prompt'));
  assert.deepEqual(errors,[]);
  fs.writeFileSync(path.join(out,'results.json'),JSON.stringify({layouts:results,clipboard:true,fallback:true,budget:true,isolation:true,pendingEdit:true},null,2));
  console.log('10 layout/copy cases; denial, budget, isolation and pending-edit checks passed');
 }finally{await browser.close();await new Promise(resolve=>server.close(resolve));}
})().catch(e=>{console.error(e);process.exitCode=1});
