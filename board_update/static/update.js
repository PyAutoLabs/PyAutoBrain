'use strict';
const statusNode = document.getElementById('status');
const boardOrigin = document.body.dataset.boardOrigin;
const csrf = document.body.dataset.csrf;
let started = false;
function report(message) {
  if (window.opener) window.opener.postMessage({type:'board-update-result', ...message}, boardOrigin);
}
async function post(path, data) {
  const response = await fetch(path, {method:'POST', credentials:'same-origin',
    headers:{'Content-Type':'application/json','X-CSRF-Token':csrf}, body:JSON.stringify(data)});
  const body = await response.json();
  if (!response.ok && !body.login_required) throw Object.assign(new Error(body.error || 'Update failed'), {url:body.url});
  return body;
}
function showLink(url) {
  // Server supplies only allowlisted GitHub workflow/run URLs.
  if (!/^https:\/\/github\.com\/PyAutoLabs\/PyAuto\w+\/actions\/(workflows\/[\w.-]+|runs\/\d+)$/.test(url || '')) return;
  const link = document.getElementById('workflow'); link.href=url; link.hidden=false;
}
async function update(target) {
  if (started) return;
  started = true;
  statusNode.textContent='Requesting update…';
  try {
    const result = await post('/api/dispatch', {target});
    if (result.login_required) {
      statusNode.textContent='Sign in to GitHub to update this board.';
      const login = await post('/api/login', {target});
      location.assign(login.url);
      return;
    }
    statusNode.textContent='Update queued. The board will change after the workflow publishes it.';
    showLink(result.url); report(result);
  } catch (error) {
    statusNode.textContent=error.message; showLink(error.url);
    report({error:error.message});
  }
}
window.addEventListener('message', event => {
  if (event.origin !== boardOrigin || event.source !== window.opener ||
      event.data?.type !== 'board-update-request' || typeof event.data.target !== 'string') return;
  update(event.data.target);
});
document.getElementById('logout').addEventListener('click', async () => {
  try { await post('/api/logout', {}); statusNode.textContent='Signed out. You can close this window.'; }
  catch (error) { statusNode.textContent=error.message; }
});
// OAuth may sever window.opener. The server retains only the explicit pre-login intent.
if (document.body.dataset.pending) update(document.body.dataset.pending);
else if (window.opener) window.opener.postMessage({type:'board-update-ready'}, boardOrigin);
else statusNode.textContent='Open Update from a board to request a refresh.';
