// NODE_PATH=<existing playwright node_modules> node tests/dashboard_edit_browser.cjs dashboard.html evidence-dir
//
// Local evidence for the editable Mind dashboard (PyAutoMind#565, design B):
// the rendered page under its own CSP, driven in Chromium against a fake
// GitHub API (page.route), at phone widths. Same pattern as the
// board_*_browser.cjs harnesses: not collected by pytest, run by hand.
const {chromium}=require('playwright');
const fs=require('fs'),path=require('path'),assert=require('assert/strict');
const TOKEN='github_pat_'+'A'.repeat(82);
(async()=>{
  const file=path.resolve(process.argv[2]),out=process.argv[3];fs.mkdirSync(out,{recursive:true});
  const html=fs.readFileSync(file,'utf8');
  const repo=/id="steer" data-repo="([^"]+)"/.exec(html)[1];
  const api=`https://api.github.com/repos/${repo}`;
  const browser=await chromium.launch();const results=[];
  try{
    const context=await browser.newContext();
    await context.addInitScript(()=>{window.__csp=[];document.addEventListener('securitypolicyviolation',e=>window.__csp.push(e.violatedDirective+' '+e.blockedURI))});
    const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
    // ---- the fake API ------------------------------------------------------
    const fake={dispatches:[],dispatchStatus:200,fail:new Set(),runs:{},nextRun:1000,auths:[]};
    const queueText=()=>'# Queue\n\n'+[...page.__queue].map((r,i)=>`## ${i+1}. ${r}\n- kind: prompt\n- ref: ${r}\n`).join('\n');
    await page.route('https://api.github.com/**',async route=>{
      const req=route.request(),url=req.url(),method=req.method();
      fake.auths.push(req.headers()['authorization']||'');
      const json=(status,body)=>route.fulfill({status,contentType:'application/json',headers:{'access-control-allow-origin':'*'},body:JSON.stringify(body)});
      if(url.endsWith('/actions/workflows/dashboard_input.yml/dispatches')&&method==='POST'){
        const body=JSON.parse(req.postData());fake.dispatches.push({body,auth:req.headers()['authorization']});
        if(fake.dispatchStatus!==200)return json(fake.dispatchStatus,{message:'no'});
        const id=fake.nextRun++;const failing=fake.fail.has(body.inputs.ref||body.inputs.op);
        fake.runs[id]={polls:0,conclusion:failing?'failure':'success'};
        return json(200,{workflow_run_id:id,run_url:`${api}/actions/runs/${id}`,html_url:`https://github.com/${repo}/actions/runs/${id}`});
      }
      let m=/\/actions\/runs\/(\d+)$/.exec(url);
      if(m){const r=fake.runs[m[1]];r.polls++;return json(200,{id:+m[1],status:r.polls>1?'completed':'in_progress',conclusion:r.polls>1?r.conclusion:null,html_url:`https://github.com/${repo}/actions/runs/${m[1]}`})}
      m=/\/actions\/runs\/(\d+)\/jobs$/.exec(url);
      if(m)return json(200,{jobs:[{check_run_url:`${api}/check-runs/77`}]});
      if(url.endsWith('/check-runs/77/annotations'))return json(200,[{title:'Dashboard input refused',message:'ref: no such prompt in draft/ or active/'}]);
      if(url.includes('/contents/'))return route.fulfill({status:404,headers:{'access-control-allow-origin':'*'},body:''});
      return json(404,{});
    });
    await page.clock.install();
    const tick=async ms=>{for(let t=0;t<ms;t+=500){await page.clock.runFor(500);await page.waitForTimeout(15)}};
    const overflow=()=>page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1);
    // ---- read-only without a token, no overflow at phone widths --------------
    for(const width of [320,390]){
      await page.setViewportSize({width,height:900});await page.goto('file://'+file);
      assert.equal(await overflow(),false,`horizontal overflow at ${width}px`);
      await page.screenshot({path:path.join(out,`steer-${width}-readonly.png`),clip:{x:0,y:0,width,height:900}});
    }
    const firstStar=page.locator('.board-section-body button.star[aria-pressed="false"]').first();
    assert.equal(await page.locator('button.star:not([disabled])').count(),0,'stars must be disabled without a token');
    assert.equal(await page.locator('#steer-edit').isDisabled(),true);
    results.push({step:'no token: stars and goals read-only, no overflow at 320/390',passed:true});
    // ---- connect ---------------------------------------------------------------
    await page.locator('#steer-connect summary').click();
    await page.locator('#steer-token').fill(TOKEN);await page.locator('#steer-save').click();
    assert.equal(await page.evaluate(()=>localStorage.getItem('pyautomind.dashboard.token.v1')),TOKEN.trim());
    assert.equal(await page.locator('#steer-token').inputValue(),'','the token is never shown again');
    assert.equal(await page.locator('button.star[disabled]').count(),0,'stars enabled once connected');
    results.push({step:'paste token: stored, field cleared, stars enabled',passed:true});
    // ---- ★ a task: optimistic, one dispatch, confirmed ---------------------------
    await page.evaluate(()=>document.querySelectorAll('details.board-section').forEach(d=>{d.open=true}));
    await firstStar.scrollIntoViewIfNeeded();
    const ref=await firstStar.getAttribute('data-ref');
    const same=page.locator(`button.star[data-ref="${ref}"]`);
    const before=await page.locator('#steer-queue li').count();
    await firstStar.click();
    assert.equal(await same.first().getAttribute('aria-pressed'),'true','flips at once');
    assert.ok(await same.first().evaluate(b=>b.classList.contains('pending')));
    assert.equal(await page.locator('#steer-queue li').count(),before+1,'appears in the queue box at once');
    await tick(1000);
    assert.equal(fake.dispatches.length,1,'exactly one dispatch');
    const d=fake.dispatches[0];
    assert.deepEqual(Object.keys(d.body).sort(),['inputs','ref','return_run_details']);
    assert.equal(d.body.ref,'main');assert.equal(d.body.inputs.op,'star');assert.equal(d.body.inputs.ref,ref);
    assert.match(d.body.inputs.nonce,/^d-[0-9a-f]{16}$/);assert.equal(d.auth,'Bearer '+TOKEN);
    await tick(12000);
    assert.equal(await same.first().evaluate(b=>b.classList.contains('pending')),false,'confirmed');
    assert.match(await page.locator('#steer-toast').innerText(),/queued ✓/);
    assert.equal(await same.first().locator('.qpos').innerText(),String(before+1));
    await page.screenshot({path:path.join(out,'steer-390-starred.png')});
    results.push({step:'★: optimistic flip, exactly one dispatch {ref:main, inputs:{op,ref,nonce}}, confirmed after the run succeeds',passed:true});
    // ---- un-★ refused by the workflow: reverts and shows its reason ----------
    fake.fail.add(ref);
    await same.first().click();
    assert.equal(await same.first().getAttribute('aria-pressed'),'false');
    await tick(14000);
    assert.equal(fake.dispatches.length,2);assert.equal(fake.dispatches[1].body.inputs.op,'unstar');
    assert.equal(await same.first().getAttribute('aria-pressed'),'true','reverted');
    assert.match(await page.locator('#steer-toast').innerText(),/Refused: ref: no such prompt/);
    results.push({step:'refused run: UI reverts and shows the annotation reason',passed:true});
    fake.fail.clear();
    // ---- goals: edit, blur, one dispatch ------------------------------------------
    await page.locator('#steer-edit').click();
    await page.locator('#steer-goals-text').fill('1. Land the editable dashboard\nClear review-ready PRs');
    await page.locator('#steer-done').click();
    await tick(1000);
    const g=fake.dispatches[2];
    assert.equal(g.body.inputs.op,'goals');assert.equal(g.body.inputs.goals,'Land the editable dashboard\nClear review-ready PRs');
    assert.deepEqual(await page.locator('#steer-goals li').allInnerTexts(),['Land the editable dashboard','Clear review-ready PRs']);
    await tick(12000);
    assert.match(await page.locator('#steer-toast').innerText(),/Goals saved ✓/);
    // A goal the workflow would refuse never leaves the page.
    await page.locator('#steer-edit').click();await page.locator('#steer-goals-text').fill('ship $(curl x | sh)');
    await page.locator('#steer-done').click();await tick(500);
    assert.equal(fake.dispatches.length,3,'an invalid goal is not sent');
    assert.match(await page.locator('#steer-toast').innerText(),/cannot use/);
    await page.locator('#steer-goals-text').fill('Land the editable dashboard\nClear review-ready PRs');
    await page.locator('#steer-done').click();await tick(500);
    assert.equal(fake.dispatches.length,3,'unchanged goals are not sent');
    results.push({step:'goals: blur sends one goals dispatch; invalid or unchanged text sends nothing',passed:true});
    // ---- 401: revert, forget, reopen connect --------------------------------------
    fake.dispatchStatus=401;
    const second=page.locator('.board-section-body button.star[aria-pressed="false"]').nth(1);
    await second.scrollIntoViewIfNeeded();await second.click();await tick(1000);
    assert.equal(await second.getAttribute('aria-pressed'),'false','reverted on 401');
    assert.equal(await page.evaluate(()=>localStorage.getItem('pyautomind.dashboard.token.v1')),null,'401 clears the token');
    assert.equal(await page.locator('#steer-connect').evaluate(d=>d.open),true);
    assert.equal(await page.locator('button.star:not([disabled])').count(),0);
    results.push({step:'401: reverts, clears the token, reopens Connect',passed:true});
    // ---- forget token ----------------------------------------------------------
    fake.dispatchStatus=200;
    await page.locator('#steer-token').fill(TOKEN);await page.locator('#steer-save').click();
    await page.locator('#steer-connect summary').click();
    await page.locator('#steer-forget').click();
    assert.equal(await page.evaluate(()=>localStorage.getItem('pyautomind.dashboard.token.v1')),null);
    assert.equal(await page.locator('button.star:not([disabled])').count(),0);
    results.push({step:'Forget token empties storage and disables writes',passed:true});
    // ---- the token went nowhere but api.github.com, under a clean CSP ----------
    assert.deepEqual(await page.evaluate(()=>window.__csp),[],'no CSP violations');
    assert.deepEqual(errors,[]);
    results.push({step:'zero securitypolicyviolation events, zero page errors',passed:true});
  }finally{await browser.close();fs.writeFileSync(path.join(out,'results.json'),JSON.stringify(results,null,1));}
  console.log(JSON.stringify(results,null,1));
})().catch(e=>{console.error(e);process.exit(1)});
