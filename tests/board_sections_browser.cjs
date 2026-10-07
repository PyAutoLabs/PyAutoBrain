// NODE_PATH=<playwright node_modules> node tests/board_sections_browser.cjs <fixture-dir> <evidence-dir>
const {chromium}=require('playwright');
const fs=require('fs'),path=require('path'),assert=require('assert/strict');
(async()=>{
 const folder=path.resolve(process.argv[2]),out=path.resolve(process.argv[3]);fs.mkdirSync(out,{recursive:true});const browser=await chromium.launch();
 const results=[];
 try{
 for(const file of fs.readdirSync(folder).filter(f=>f.endsWith('.html')&&!f.startsWith('.'))){
  const page=await browser.newPage();await page.addInitScript(()=>{Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async text=>{window.copiedText=text}}})});const errors=[];page.on('pageerror',e=>errors.push(e.message));
  for(const colorScheme of ['light','dark'])for(const width of [390,768,820,1024,1440]){
   await page.setViewportSize({width,height:1000});await page.emulateMedia({colorScheme});
   await page.goto('file://'+path.join(folder,file));
   const structure=await page.evaluate(()=>{
    const nav=document.querySelector('.board-nav'),panel=document.querySelector('.orchestration-panel');
    const sections=[...document.querySelectorAll('details.board-section')];
    return {nav:!!nav,panel:!!panel,order:!nav||!panel||!!(panel.compareDocumentPosition(nav)&Node.DOCUMENT_POSITION_FOLLOWING),sections:sections.length,open:sections.filter(x=>x.open).length,overflow:document.documentElement.scrollWidth>innerWidth+1};
   });
   assert(structure.order,`${file}: panel order`);assert(!structure.open,`${file}: initially collapsed`);
   assert(!structure.overflow,`${file}: ${width} ${colorScheme} overflow`);
   const copy=page.locator('.orchestration-copy').first();
   if(await copy.count()){await copy.click();assert(await page.evaluate(()=>typeof window.copiedText==='string'&&window.copiedText.length>0),`${file}: copy prompt`);}
   if(width===390&&colorScheme==='light')await page.screenshot({path:path.join(out,file+'.png'),fullPage:false});
   const links=await page.locator('.board-nav a[href^="#"]').evaluateAll(nodes=>nodes.map(n=>n.getAttribute('href')));
   for(const hash of links){
    const exists=await page.evaluate(h=>!!document.getElementById(decodeURIComponent(h.slice(1))),hash);
    assert(exists,`${file}: missing ${hash}`);
    await page.locator(`.board-nav a[href="${hash}"]`).first().click();await page.waitForTimeout(30);
    assert(await page.evaluate(h=>{let t=document.getElementById(decodeURIComponent(h.slice(1)));for(let p=t;p;p=p.parentElement)if(p.tagName==='DETAILS'&&!p.open)return false;return true},hash),`${file}: unopened ${hash}`);
   }
   // Direct deep links and repeated navigation must reopen a closed parent.
   if(links.length){
    const hash=links[0];await page.goto('file://'+path.join(folder,file)+hash);await page.waitForTimeout(30);
    await page.evaluate(()=>document.querySelectorAll('details.board-section').forEach(d=>d.open=false));
    await page.locator(`.board-nav a[href="${hash}"]`).first().click();await page.waitForTimeout(30);
    assert(await page.evaluate(h=>{let t=document.getElementById(decodeURIComponent(h.slice(1)));for(let p=t;p;p=p.parentElement)if(p.tagName==='DETAILS'&&!p.open)return false;return true},hash),`${file}: repeated anchor`);
   }
   const deep=await page.locator('details.board-section .board-section-body [id]').evaluateAll(nodes=>nodes.find(n=>n.closest('details:not(.board-section)'))?.id);
   if(deep){
    await page.goto('file://'+path.join(folder,file)+'#'+encodeURIComponent(deep));await page.waitForTimeout(30);
    assert(await page.evaluate(id=>{for(let p=document.getElementById(id);p;p=p.parentElement)if(p.tagName==='DETAILS'&&!p.open)return false;return true},deep),`${file}: deep link`);
   }
   const summary=page.locator('details.board-section>summary').first();
   if(await summary.count()){
    await summary.evaluate(s=>s.parentElement.open=false);await summary.focus();await page.keyboard.press('Enter');
    assert(await summary.evaluate(s=>s.parentElement.open),`${file}: keyboard`);
   }
   results.push({file,width,colorScheme,sections:structure.sections});
  }
  assert.equal(errors.length,0,`${file}: ${errors.join('; ')}`);await page.close();
 }
 fs.writeFileSync(path.join(out,'browser-results.json'),JSON.stringify(results,null,2));console.log(`${results.length} browser cases passed`);
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
