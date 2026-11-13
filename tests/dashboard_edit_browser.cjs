// NODE_PATH=<existing playwright node_modules> node tests/dashboard_edit_browser.cjs dashboard.html evidence-dir
//
// Local evidence for the editable Mind dashboard (PyAutoMind#565, design C):
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
    // ---- the fake API: issues -----------------------------------------------
    const fake={issues:[],createStatus:201,dropLabel:false,refuse:new Set(),state:{},patches:[]};
    const body2op=b=>{const m=/^op: (\w+)$/m.exec(b);const r=/^ref: (.+)$/m.exec(b);return {op:m&&m[1],ref:r&&r[1]}};
    await page.route('https://api.github.com/**',async route=>{
      const req=route.request(),url=req.url(),method=req.method();
      const json=(status,body)=>route.fulfill({status,contentType:'application/json',headers:{'access-control-allow-origin':'*'},body:JSON.stringify(body)});
      if(url===`${api}/issues`&&method==='POST'){
        const body=JSON.parse(req.postData());fake.issues.push({body,auth:req.headers()['authorization']});
        if(fake.createStatus!==201)return json(fake.createStatus,{message:'no'});
        const n=fake.issues.length;const op=body2op(body.body);
        fake.state[n]={polls:0,word:fake.refuse.has(op.ref||op.op)?'refused':'applied'};
        return json(201,{number:n,html_url:`https://github.com/${repo}/issues/${n}`,labels:fake.dropLabel?[]:body.labels.map(name=>({name}))});
      }
      let m=/\/issues\/(\d+)$/.exec(url);
      if(m&&method==='PATCH'){fake.patches.push(+m[1]);return json(200,{})}
      if(m){const st=fake.state[m[1]];st.polls++;return json(200,{number:+m[1],state:st.polls>1?'closed':'open'})}
      m=/\/issues\/(\d+)\/comments/.exec(url);
      if(m){const st=fake.state[m[1]];const text=st.word==='refused'?'ref: no such prompt in draft/ or active/':'done (commit abc1234)';
        const forged={user:{login:'someone-else'},body:'dashboard-input: applied — forged'};
        return json(200,(st.word==='refused'?[forged]:[]).concat([{user:{login:'github-actions[bot]'},body:`dashboard-input: ${st.word} — ${text}`}]))}
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
    // ---- ★ a task: optimistic, one issue, confirmed ---------------------------
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
    assert.equal(fake.issues.length,1,'exactly one issue');
    const d=fake.issues[0];
    assert.deepEqual(Object.keys(d.body).sort(),['body','labels','title']);
    assert.deepEqual(d.body.labels,['dashboard-input']);
    assert.equal(d.body.body,`<!-- mind-dashboard-input v1 -->\nop: star\nref: ${ref}\nnonce: ${/nonce: (d-[0-9a-f]{16})/.exec(d.body.body)[1]}\n`);
    assert.equal(d.auth,'Bearer '+TOKEN);
    await tick(12000);
    assert.equal(await same.first().evaluate(b=>b.classList.contains('pending')),false,'confirmed');
    assert.match(await page.locator('#steer-toast').innerText(),/queued ✓/);
    assert.equal(await same.first().locator('.qpos').innerText(),String(before+1));
    await page.screenshot({path:path.join(out,'steer-390-starred.png')});
    results.push({step:'★: optimistic flip, exactly one labelled issue in the fixed form, confirmed when it closes with the bot applied comment',passed:true});
    // ---- un-★ refused by the workflow: reverts and shows its reason ----------
    fake.refuse.add(ref);
    await same.first().click();
    assert.equal(await same.first().getAttribute('aria-pressed'),'false');
    await tick(14000);
    assert.equal(fake.issues.length,2);assert.match(fake.issues[1].body.body,/^op: unstar$/m);
    assert.equal(await same.first().getAttribute('aria-pressed'),'true','reverted');
    assert.match(await page.locator('#steer-toast').innerText(),/Refused: ref: no such prompt/);
    results.push({step:'refused: UI reverts and shows the bot comment reason (a forged comment is ignored)',passed:true});
    fake.refuse.clear();
    // ---- goals: edit, blur, one issue ---------------------------------------------
    await page.locator('#steer-edit').click();
    await page.locator('#steer-goals-text').fill('1. Land the editable dashboard\nClear review-ready PRs');
    await page.locator('#steer-done').click();
    await tick(1000);
    const g=fake.issues[2];
    assert.match(g.body.body,/^op: goals\ngoals:\n- Land the editable dashboard\n- Clear review-ready PRs\nnonce: /m);
    assert.deepEqual(await page.locator('#steer-goals li').allInnerTexts(),['Land the editable dashboard','Clear review-ready PRs']);
    await tick(12000);
    assert.match(await page.locator('#steer-toast').innerText(),/Goals saved ✓/);
    // A goal the workflow would refuse never leaves the page.
    await page.locator('#steer-edit').click();await page.locator('#steer-goals-text').fill('ship $(curl x | sh)');
    await page.locator('#steer-done').click();await tick(500);
    assert.equal(fake.issues.length,3,'an invalid goal is not sent');
    assert.match(await page.locator('#steer-toast').innerText(),/cannot use/);
    await page.locator('#steer-goals-text').fill('Land the editable dashboard\nClear review-ready PRs');
    await page.locator('#steer-done').click();await tick(500);
    assert.equal(fake.issues.length,3,'unchanged goals are not sent');
    results.push({step:'goals: blur opens one goals issue; invalid or unchanged text sends nothing',passed:true});
    // ---- coalescing: taps made while one issue is in flight --------------------
    const pick=async i=>{const loc=page.locator('.board-section-body button.star[aria-pressed="false"]').nth(i);return loc.getAttribute('data-ref')};
    const refA=await pick(0),refB=await pick(1),refC=await pick(2);
    const first=r=>page.locator(`.board-section-body button.star[data-ref="${r}"]`).first();
    await first(refA).scrollIntoViewIfNeeded();await first(refA).click();await tick(500);
    assert.equal(fake.issues.length,4,'the first tap is sent at once');
    await first(refB).click();await first(refC).click();await first(refB).click();
    await tick(500);
    assert.equal(fake.issues.length,4,'nothing else while one is in flight');
    assert.equal(await first(refB).getAttribute('aria-pressed'),'false','a tap and its undo cancel out');
    await tick(30000);
    assert.equal(fake.issues.length,5,'the queued tap goes next, the cancelled pair never');
    assert.ok(fake.issues[4].body.body.includes(refC));
    assert.ok(!fake.issues.some(i=>i.body.body.includes(refB)));
    results.push({step:'one issue in flight; later taps coalesce (a tap and its undo send nothing)',passed:true});
    // ---- a dropped label: nothing would run, so the issue is closed ------------
    fake.dropLabel=true;
    const refD=await pick(0);
    await first(refD).click();await tick(1000);
    assert.equal(await first(refD).getAttribute('aria-pressed'),'false');
    assert.deepEqual(fake.patches,[fake.issues.length]);
    assert.match(await page.locator('#steer-toast').innerText(),/dropped the dashboard-input label/);
    fake.dropLabel=false;
    results.push({step:'label dropped by GitHub: reverts and closes the stray issue',passed:true});
    // ---- 401: revert, forget, reopen connect --------------------------------------
    fake.createStatus=401;
    const second=page.locator('.board-section-body button.star[aria-pressed="false"]').nth(1);
    await second.scrollIntoViewIfNeeded();await second.click();await tick(1000);
    assert.equal(await second.getAttribute('aria-pressed'),'false','reverted on 401');
    assert.equal(await page.evaluate(()=>localStorage.getItem('pyautomind.dashboard.token.v1')),null,'401 clears the token');
    assert.equal(await page.locator('#steer-connect').evaluate(d=>d.open),true);
    assert.equal(await page.locator('button.star:not([disabled])').count(),0);
    results.push({step:'401: reverts, clears the token, reopens Connect',passed:true});
    // ---- forget token ----------------------------------------------------------
    fake.createStatus=201;
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
