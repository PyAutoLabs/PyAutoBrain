const {chromium}=require('playwright');
const fs=require('fs'); const path=require('path');
(async()=>{
 const browser=await chromium.launch({headless:true});
 const rows=JSON.parse(fs.readFileSync('published.json'));
 const results=process.env.VARIANT ? JSON.parse(fs.readFileSync('layout-results.json')).filter(r=>r.variant!==process.env.VARIANT) : [];
 for(const variant of (process.env.VARIANT ? [process.env.VARIANT] : ['before','after'])) {
  const context=await browser.newContext();
  await context.route('**/*',r=>r.abort());
  const page=await context.newPage();
  for(const row of rows) {
   const html=fs.readFileSync(`${variant}/${row.key}.html`,'utf8');
   for(const colorScheme of ['light','dark']) {
    await page.emulateMedia({colorScheme});
    for(const width of [390,768,820,1024,1440]) {
     await page.setViewportSize({width,height:900});
     await page.setContent(html,{waitUntil:'domcontentloaded'});
     // Expand native disclosures, including nested tables and explanations.
     await page.evaluate(()=>document.querySelectorAll('details').forEach(d=>d.open=true));
     const result=await page.evaluate(()=>{
      const width=document.documentElement.clientWidth;
      const rect=document.body.getBoundingClientRect();
      const overflow=document.documentElement.scrollWidth-width;
      const escaped=overflow>1?[...document.querySelectorAll('body *')].filter(e=>{
       const r=e.getBoundingClientRect(); if(!r.width||r.right<=width+1) return false;
       for(let p=e.parentElement;p&&p!==document.body;p=p.parentElement){if(['auto','scroll','hidden'].includes(getComputedStyle(p).overflowX))return false;}
       return true;
      }).slice(0,5).map(e=>({tag:e.tagName,cls:e.className,text:e.textContent.slice(0,70),right:e.getBoundingClientRect().right})):[];
      return {bodyWidth:rect.width,gutter:getComputedStyle(document.body).paddingLeft,overflow,escaped,scrollers:[...document.querySelectorAll('body *')].filter(e=>getComputedStyle(e).overflowX==='auto'&&e.scrollWidth>e.clientWidth+1).length};
     });
     results.push({variant,key:row.key,colorScheme,width,...result});
     if(colorScheme==='light'&&[390,1440].includes(width)&&['brain','ears','pulse'].includes(row.key)) await page.screenshot({path:`${variant}/${row.key}-${width}.png`});
    }
   }
   console.log(variant,row.key,results.filter(r=>r.variant===variant&&r.key===row.key&&r.overflow>1).map(r=>`${r.width}/${r.colorScheme}:+${r.overflow}`).join(' ')||'no page overflow');
   fs.writeFileSync('layout-results.json',JSON.stringify(results,null,2));
  }
  await context.close();
 }
 const regressions=results.filter(after=>after.variant==='after' && after.overflow>1 &&
  !results.some(before=>before.variant==='before' && before.key===after.key &&
   before.width===after.width && before.colorScheme===after.colorScheme && before.overflow>1));
 await browser.close();
 if(regressions.length) throw new Error(`New page overflow: ${JSON.stringify(regressions)}`);
 console.log(`${results.length} layout cases; no new whole-page overflow`);
})().catch(e=>{console.error(e);process.exit(1)});
