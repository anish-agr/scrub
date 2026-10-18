/* Scrub Status Board. Plain JS, no build step. Talks to the controller in docs/CONTRACTS.md.
   Options: ?api=http://localhost:8000   ?mock=1   ?cam=http://localhost:8001/stream
   Evan: to drop in, copy index.html, app.js, style.css into dashboard/ (served by the controller at "/"). */
'use strict';
const Q = new URLSearchParams(location.search);
const MOCK = Q.get('mock') === '1';
const API = (Q.get('api') || (location.protocol.startsWith('http') ? location.origin : 'http://localhost:8000')).replace(/\/$/, '');
const CAMS = { vision: Q.get('cam') || 'http://localhost:8001/stream', sim: 'http://localhost:8002/stream' };
const $ = id => document.getElementById(id);

const SETTING_IDS = { surgical: 'Operating room', bench: 'Robotics bench' };
const LIGHTS = ['bright', 'normal', 'dim'];
const RAIL = ['finding', 'picking', 'checking', 'moving_to_hand', 'setting_down', 'waiting_for_pull', 'releasing', 'returning', 'homing'];
const LABEL = { idle: 'Idle', finding: 'Finding', picking: 'Picking', checking: 'Checking grip', moving_to_hand: 'To the hand',
  setting_down: 'Setting down', waiting_for_pull: 'Waiting for pull', releasing: 'Releasing', homing: 'Going home',
  returning: 'Returning', stopped: 'Stopped', error: 'Error' };
const SUB = {
  idle: 'Waiting for a request.', finding: 'Locating the item on the tray.', picking: 'Gripper closing on the handle.',
  checking: 'Verifying the item is held.', moving_to_hand: 'Handle first, toward the open palm.',
  setting_down: 'Putting the item down at the safe spot.', waiting_for_pull: 'Hold still. Pull to take it, or say "got it".',
  releasing: 'Gripper opening.', homing: 'Arm returning to the home pose.', returning: 'Putting the item back in its slot.',
  stopped: 'Arm frozen. Press Clear stop to open the gripper and go home.', error: 'The request failed. A person needs to take over.' };
const GOOD = ['handed', 'picked', 'released', 'returned', 'set_down'];
const BAD = ['missed', 'error', 'stopped'];

const S = { conn: 'connecting', step: 'idle', item: null, queue: [], out: [], setting: null, lighting: null, fake_arm: null,
  hand_seen: null, say: null, heard: null, retries: 0, reqT0: null, reqDone: null, visited: new Set(), rejected: null,
  items: [], handoffs: [], log: [], stats: null, cam: 'vision' };
const seen = new Set();   // events already in the log (t + type + step), so reconnects do not duplicate

/* ---------- API ---------- */
async function api(method, path, body) {
  if (MOCK) return mockApi(method, path, body);
  const r = await fetch(API + path, { method, headers: { 'content-type': 'application/json' }, body: body ? JSON.stringify(body) : undefined });
  let j = null; try { j = await r.json(); } catch (e) { /* no body */ }
  if (!r.ok) { const err = new Error((j && j.detail) || ('HTTP ' + r.status)); err.status = r.status; throw err; }
  return j;
}
function say(msg, bad) { const d = $('dockMsg'); d.textContent = msg; d.className = 'dockmsg' + (bad ? ' bad' : ''); }
function name(id) {
  if (!id) return 'none';
  const f = S.items.find(i => i.id === id);
  return f ? f.name : id.replace(/_/g, ' ');
}

/* ---------- connection ---------- */
let ws = null, wsTimer = null, backoff = 1000;
function setConn(c) {
  S.conn = c;
  const el = $('conn'), b = $('banner');
  const txt = { live: 'LIVE', connecting: 'CONNECTING', down: 'DISCONNECTED', mock: 'MOCK STREAM' }[c];
  el.textContent = txt; el.className = 'conn ' + (c === 'connecting' ? '' : c);
  b.hidden = c !== 'down' && c !== 'mock';
  b.textContent = c === 'down' ? 'NOT CONNECTED to the controller at ' + API + '. Retrying. STOP will not reach the arm until this says LIVE.'
    : 'MOCK MODE: scripted fake events, no controller. STOP only stops the fake run.';
  b.style.background = c === 'mock' ? 'var(--amber)' : 'var(--red)';
}
function connect() {
  if (MOCK) { setConn('mock'); startMock(); return; }
  clearTimeout(wsTimer);
  try { ws = new WebSocket(API.replace(/^http/, 'ws') + '/events'); } catch (e) { return retry(); }
  ws.onopen = async () => { backoff = 1000; setConn('live'); await resync(); };
  ws.onmessage = m => { try { onEvent(JSON.parse(m.data)); } catch (e) { console.warn('bad event', e); } };
  ws.onclose = () => { setConn('down'); retry(); };
  ws.onerror = () => { try { ws.close(); } catch (e) { /* ignore */ } };
}
function retry() { clearTimeout(wsTimer); wsTimer = setTimeout(connect, backoff); backoff = Math.min(backoff * 1.5, 5000); }
async function resync() {          // on load and on every reconnect
  await refreshState(); await refreshSetting(); await refreshStats();
  try { const rec = await api('GET', '/events/recent?n=50'); rec.forEach(e => addLog(e, true)); rec.forEach(trackTimes); renderAll(); } catch (e) { /* optional endpoint */ }
}

/* ---------- data refresh ---------- */
async function refreshState() {
  try {
    const s = await api('GET', '/state');
    const changed = s.setting !== S.setting;
    Object.assign(S, { step: s.step, item: s.item, queue: s.queue || [], out: s.out || [], setting: s.setting, lighting: s.lighting, fake_arm: s.fake_arm, hand_seen: s.hand_seen });
    if (changed) refreshSetting();
    renderAll();
  } catch (e) { /* the WS status already shows trouble */ }
}
async function refreshSetting() {
  try { const s = await api('GET', '/setting'); S.items = (s && s.items) || []; renderCmds(); } catch (e) { /* keep old */ }
}
async function refreshStats() {
  try { S.stats = await api('GET', '/stats'); renderStats(); } catch (e) { /* keep old */ }
}
let stateTimer = null;
function scheduleState() { clearTimeout(stateTimer); stateTimer = setTimeout(refreshState, 150); }
setInterval(() => { if (S.conn === 'live' || MOCK) refreshState(); }, 2000);
setInterval(() => { if (S.conn === 'live' || MOCK) refreshStats(); }, 10000);

/* ---------- events ---------- */
function trackTimes(ev) {
  if ((ev.type === 'handed' || ev.type === 'set_down') && ev.request_to_hand_s != null) {
    if (!S.handoffs.some(h => h.t === ev.t)) { S.handoffs.push({ t: ev.t, item: ev.item, s: ev.request_to_hand_s }); S.handoffs.sort((a, b) => a.t - b.t); }
  }
}
function onEvent(ev) {
  addLog(ev, false); trackTimes(ev);
  if (ev.step) { S.step = ev.step; S.visited.add(ev.step); }
  if (ev.item !== undefined && ev.type !== 'command') S.item = ev.item;
  if (ev.say) S.say = ev.say;
  if (ev.retries != null) S.retries = ev.retries;
  if (ev.lighting) S.lighting = ev.lighting;
  if (ev.setting) S.setting = ev.setting;
  if (ev.type === 'command') {
    if (ev.action === 'handover' || ev.action === 'return') {
      if (ev.accepted) { S.heard = ev.heard || (ev.source || 'command') + ': ' + ev.action + ' ' + name(ev.item); S.reqT0 = ev.t; S.reqDone = null; S.retries = 0; S.visited = new Set(); S.rejected = null; }
      else S.rejected = (ev.reason || 'rejected') + '';
    }
  }
  if (ev.type === 'handed' || ev.type === 'set_down') S.reqDone = ev.request_to_hand_s;
  if (['missed', 'error', 'stopped', 'returned'].includes(ev.type) && S.reqDone == null) S.reqDone = -1;
  if (ev.type === 'stopped') S.queue = [];
  renderAll(); scheduleState();
  if (['handed', 'set_down', 'missed', 'returned', 'released'].includes(ev.type)) setTimeout(refreshStats, 400);
}
function addLog(ev, quiet) {
  const key = ev.t + '|' + ev.type + '|' + ev.step + '|' + (ev.command_id || '');
  if (seen.has(key)) return; seen.add(key);
  S.log.push(ev); S.log.sort((a, b) => a.t - b.t); if (S.log.length > 200) S.log.shift();
  if (!quiet) renderLog();
}

/* ---------- render ---------- */
const fmtT = t => new Date(t * 1000).toLocaleTimeString([], { hour12: false });
const median = a => { if (!a.length) return null; const s = [...a].sort((x, y) => x - y), m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };
const f1 = n => n == null ? '--' : (Math.round(n * 10) / 10).toFixed(1);

function renderPickers() {
  const ss = $('setSeg'); ss.innerHTML = '';
  Object.keys(SETTING_IDS).forEach(id => {
    const b = document.createElement('button'); b.textContent = SETTING_IDS[id]; b.setAttribute('aria-pressed', S.setting === id);
    b.onclick = async () => {
      try { await api('POST', '/setting', { setting: id }); say('Tray set to ' + SETTING_IDS[id] + '.'); await refreshState(); }
      catch (e) { say(e.status === 409 ? 'Cannot switch trays now: wait for idle or press STOP first.' : 'Setting change failed: ' + e.message, true); }
    };
    ss.append(b);
  });
  const ls = $('litSeg'); ls.innerHTML = '';
  LIGHTS.forEach(id => {
    const b = document.createElement('button'); b.textContent = id; b.setAttribute('aria-pressed', S.lighting === id);
    b.onclick = async () => {
      try { await api('POST', '/lighting', { lighting: id, lux: null }); say('Lighting tagged ' + id + '.'); await refreshState(); }
      catch (e) { say('Lighting change failed: ' + e.message, true); }
    };
    ls.append(b);
  });
}
let pickerKey = '';
function renderCmds() {
  const c = $('cmds'); c.innerHTML = '';
  const add = (label, body) => {
    const b = document.createElement('button'); b.textContent = label;
    b.onclick = async () => {
      try {
        const r = await api('POST', '/command', Object.assign({ id: (crypto.randomUUID ? crypto.randomUUID() : String(Math.random())), source: 'dashboard', t: Date.now() / 1000 }, body));
        say(r.accepted ? (r.say || 'Accepted.') : 'Rejected: ' + (r.reason || 'unknown'), !r.accepted);
      } catch (e) { say('Command failed: ' + e.message, true); }
    };
    c.append(b);
  };
  S.items.forEach(i => add('Hand ' + i.name, { action: 'handover', item: i.id, heard: 'dashboard button: ' + i.name }));
  add('Return item', { action: 'return', item: null });
  add('Count', { action: 'count', item: null });
  add('Got it', { action: 'got_it', item: null });
}
function renderState() {
  const bad = S.step === 'stopped' || S.step === 'error';
  $('resetBtn').hidden = !bad;
  $('stepBig').textContent = LABEL[S.step] || S.step; $('stepBig').className = 'step-big' + (bad ? ' bad' : '');
  $('stepCode').textContent = 'step: ' + S.step;
  $('stepSub').textContent = S.rejected ? 'Request not accepted: ' + S.rejected : (SUB[S.step] || '');
  $('rqHeard').textContent = S.heard || 'none yet';
  $('rqItem').textContent = S.step === 'idle' && !S.item ? 'none' : name(S.item);
  $('rqQueue').textContent = S.queue.length ? S.queue.map(name).join(', ') : 'empty';
  $('rqRetry').textContent = S.retries;
  $('rqSay').textContent = S.say || 'none';
  $('armState').textContent = 'arm: ' + (S.fake_arm == null ? 'unknown' : S.fake_arm ? 'fake (no hardware)' : 'real');
  $('handState').textContent = 'hand: ' + (S.hand_seen == null ? 'unknown' : S.hand_seen ? 'seen' : 'not seen');
  const rail = $('rail'); rail.innerHTML = '';
  RAIL.concat(['stopped']).forEach(st => {
    const d = document.createElement('div'); d.textContent = LABEL[st];
    if (st === S.step) d.className = 'on' + (st === 'stopped' ? ' bad' : ''); else if (S.visited.has(st) && st !== 'stopped') d.className = 'done';
    rail.append(d);
  });
  $('outN').textContent = S.out.length; $('outN').className = 'count' + (S.out.length ? ' nz' : '');
  const ol = $('outList'); ol.innerHTML = '';
  if (!S.out.length) { const li = document.createElement('li'); li.className = 'none'; li.textContent = 'Everything is on the tray.'; ol.append(li); }
  S.out.forEach(id => { const li = document.createElement('li'); li.textContent = name(id); ol.append(li); });
}
function renderClock() {
  const el = $('rqClock');
  if (S.reqT0 == null) { el.textContent = '--'; return; }
  if (S.reqDone != null && S.reqDone >= 0) el.textContent = f1(S.reqDone) + ' s (done)';
  else if (S.reqDone === -1) el.textContent = 'no handoff';
  else el.textContent = f1(Date.now() / 1000 - S.reqT0) + ' s';
}
setInterval(renderClock, 100);
function renderTimes() {
  const h = S.handoffs, last = h.length ? h[h.length - 1].s : null;
  const med = (S.stats && S.stats.median_request_to_hand_s != null) ? S.stats.median_request_to_hand_s : median(h.map(x => x.s));
  $('tLast').innerHTML = f1(last) + '<small>s</small>'; $('tMed').innerHTML = f1(med) + '<small>s</small>'; $('tN').textContent = h.length;
  const bars = $('bars'); bars.innerHTML = '';
  if (!h.length) { bars.innerHTML = '<span class="none">No handoff yet.</span>'; return; }
  const recent = h.slice(-8).reverse(), mx = Math.max(...recent.map(x => x.s), 1);
  recent.forEach(x => {
    const r = document.createElement('div'); r.className = 'bar';
    r.innerHTML = '<span></span><i></i><b></b>'; r.children[0].textContent = name(x.item);
    r.children[1].style.width = Math.max(2, x.s / mx * 100) + '%'; r.children[2].textContent = f1(x.s) + ' s';
    bars.append(r);
  });
}
function renderLog() {
  const ol = $('log'); ol.innerHTML = '';
  if (!S.log.length) { ol.innerHTML = '<li class="none">No events yet.</li>'; return; }
  S.log.slice().reverse().forEach(ev => {
    const li = document.createElement('li');
    let text = '';
    if (ev.type === 'command') text = (ev.accepted === false ? 'REJECTED (' + (ev.reason || '?') + '): ' : '') + (ev.source || '') + ' ' + (ev.action || '') + (ev.heard ? ' "' + ev.heard + '"' : '');
    else if (ev.type === 'step') text = LABEL[ev.step] || ev.step || '';
    else if (ev.type === 'count') text = 'out: ' + ((ev.out || []).map(name).join(', ') || 'nothing');
    else if (ev.type === 'error') text = ev.error || 'error';
    else if (ev.request_to_hand_s != null) text = f1(ev.request_to_hand_s) + ' s request to hand' + (ev.retries ? ', ' + ev.retries + ' retry' : '');
    else if (ev.retries) text = ev.retries + ' retry';
    const cls = BAD.includes(ev.type) ? ' bad' : GOOD.includes(ev.type) ? ' good' : '';
    li.innerHTML = '<span class="t"></span><span class="ty' + cls + '"></span><span class="it"></span><span class="say"></span>';
    li.children[0].textContent = fmtT(ev.t); li.children[1].textContent = ev.type; li.children[2].textContent = ev.item ? name(ev.item) : '';
    li.children[3].textContent = text + (text && ev.say ? '  ' : '');
    if (ev.say) { const q = document.createElement('q'); q.textContent = '"' + ev.say + '"'; li.children[3].append(q); }
    ol.append(li);
  });
}
function normStats(obj) {
  const rows = [];
  if (!obj) return rows;
  const list = Array.isArray(obj) ? obj.map(r => [r.item || r.lighting || r.id || r.key, r]) : Object.entries(obj);
  list.forEach(([k, v]) => {
    if (typeof v !== 'object' || v === null) return;
    const ok = v.ok ?? v.successes ?? v.success ?? 0;
    const missed = v.missed ?? v.failed ?? v.failures ?? 0;
    const tries = v.tries ?? v.n ?? v.attempts ?? (ok + missed);
    rows.push({ k, tries, ok, rate: tries ? ok / tries : null, med: v.median_s ?? v.median_request_to_hand_s ?? v.median ?? null });
  });
  return rows;
}
function fillTable(id, rows, label) {
  const tb = $(id); tb.innerHTML = '';
  if (!rows.length) { tb.innerHTML = '<tr><td class="none" colspan="5"></td></tr>'; tb.querySelector('td').textContent = label; return; }
  rows.forEach(r => {
    const tr = document.createElement('tr');
    tr.innerHTML = '<td></td><td></td><td></td><td class="rate"></td><td></td>';
    tr.children[0].textContent = name(r.k); tr.children[1].textContent = r.tries; tr.children[2].textContent = r.ok;
    tr.children[3].textContent = r.rate == null ? '--' : Math.round(r.rate * 100) + '%'; if (r.rate != null && r.rate < 0.8) tr.children[3].classList.add('lo');
    tr.children[4].textContent = f1(r.med); tb.append(tr);
  });
}
function renderStats() {
  const st = S.stats || {};
  fillTable('tbItem', normStats(st.by_item), 'No results yet.');
  fillTable('tbLit', normStats(st.by_lighting), st.by_item ? 'Not reported by this stats source.' : 'No results yet.');
  $('statNote').textContent = 'GET /stats' + (st.source ? ', ' + st.source : '');
  renderTimes();
}
function renderAll() { renderPickers(); renderState(); renderLog(); renderTimes(); }

/* ---------- STOP (always works; says so when it could not reach the controller) ---------- */
let stopping = false;
async function doStop() {
  if (stopping) return; stopping = true; setTimeout(() => stopping = false, 250);
  say('STOP sent...');
  try { await api('POST', '/stop'); say('STOP sent. Arm frozen.'); refreshState(); }
  catch (e) { say('STOP NOT SENT: cannot reach the controller (' + e.message + '). Cut arm power.', true); }
}
$('stopBtn').onclick = doStop;
/* Clear stop: POST /reset opens the gripper, homes, clears out (409 while busy) */
$('resetBtn').onclick = async () => {
  try { await api('POST', '/reset'); say('Reset. Ready.'); refreshState(); }
  catch (e) { say(e.status === 409 ? 'Cannot reset while the arm is busy.' : 'Reset failed: ' + e.message, true); }
};
document.addEventListener('keydown', e => {
  if (e.code !== 'Space' || e.repeat) return;
  e.preventDefault(); doStop();     // space always stops, even if a button has focus
});
document.addEventListener('keyup', e => { if (e.code === 'Space') e.preventDefault(); });

/* ---------- camera ---------- */
let camTimer = null;
function camStart() {
  clearTimeout(camTimer);
  const img = $('camImg'), off = $('camOff');
  $('camVision').setAttribute('aria-pressed', S.cam === 'vision'); $('camSim').setAttribute('aria-pressed', S.cam === 'sim');
  const url = CAMS[S.cam];
  $('camNote').textContent = url;
  if (MOCK) { img.removeAttribute('src'); off.hidden = false; off.innerHTML = 'Mock mode<small>No camera in mock mode. Pick a stream below to try one.</small>'; if (!Q.get('cam')) return; }
  img.onload = () => { off.hidden = true; };
  img.onerror = () => {
    off.hidden = false; off.innerHTML = 'Camera offline<small></small>';
    off.querySelector('small').textContent = url + ' is not answering. Retrying every 5 s.';
    camTimer = setTimeout(() => { img.src = url + (url.includes('?') ? '&' : '?') + '_=' + Date.now(); }, 5000);
  };
  img.src = url;
}
function pickCam(c) { S.cam = c; try { localStorage.setItem('scrubCam', c); } catch (e) { /* ignore */ } camStart(); }
$('camVision').onclick = () => pickCam('vision'); $('camSim').onclick = () => pickCam('sim');
try { const c = localStorage.getItem('scrubCam'); if (c === 'sim' || c === 'vision') S.cam = c; } catch (e) { /* ignore */ }

/* ---------- mock mode: a tiny fake controller with the same shapes ---------- */
const M = { step: 'idle', item: null, queue: [], out: [], setting: 'surgical', lighting: 'normal', timers: [], busy: false, hist: [], cmd: null,
  items: { surgical: [['scalpel', 'scalpel', true], ['hemostat', 'hemostat', false], ['mayo_scissors', 'Mayo scissors', false]],
    dental: [['mouth_mirror', 'mouth mirror', false], ['explorer', 'explorer', true], ['cotton_pliers', 'cotton pliers', false]],
    bench: [['needle_nose_pliers', 'needle-nose pliers', false], ['wire_cutters', 'wire cutters', false], ['hex_key', 'hex key', false]] } };
const mItems = () => M.items[M.setting].map(([id, n, sharp]) => ({ id, name: n, sharp, aliases: [], slot: null }));
function mEmit(type, o) {
  const ev = Object.assign({ type, item: M.item, step: M.step, say: null, request_to_hand_s: null, retries: null, setting: M.setting, lighting: M.lighting, command_id: M.cmd && M.cmd.id, t: Date.now() / 1000 }, o || {});
  M.hist.push(ev); onEvent(ev); return ev;
}
function mStep(step, item) { M.step = step; if (item !== undefined) M.item = item; mEmit('step'); }
function mLater(ms, fn) { M.timers.push(setTimeout(fn, ms)); }
function mockApi(method, path, body) {
  return new Promise(res => setTimeout(() => res(mockRoute(method, path, body)), 30));
}
function mockRoute(method, path, body) {
  if (path === '/state') return { step: M.step, item: M.item, queue: M.queue.map(c => c.item), out: [...M.out], setting: M.setting, lighting: M.lighting, fake_arm: true, hand_seen: M.step === 'waiting_for_pull', t: Date.now() / 1000 };
  if (path === '/setting' && method === 'GET') return { id: M.setting, label: SETTING_IDS[M.setting], items: mItems(), return_spot: null };
  if (path === '/setting') { if (!['idle', 'stopped'].includes(M.step)) { const e = new Error('busy'); e.status = 409; throw e; } M.setting = body.setting; M.out = []; M.step = 'idle'; M.item = null; mEmit('step', { item: null }); return mockRoute('GET', '/setting'); }
  if (path === '/lighting') { M.lighting = body.lighting; return { ok: true }; }
  if (path === '/stop') { M.timers.forEach(clearTimeout); M.timers = []; M.queue = []; M.busy = false; M.step = 'stopped'; mEmit('stopped', { say: 'Stopped.' }); return { accepted: true }; }
  if (path === '/reset') { M.step = 'idle'; M.item = null; M.out = []; mEmit('step', { item: null, say: 'Reset. Ready.' }); return { accepted: true }; }
  if (path.startsWith('/events/recent')) return M.hist.slice(-50);
  if (path === '/stats') {
    const by = {}, ts = []; M.hist.forEach(e => { if (['handed', 'set_down', 'missed'].includes(e.type) && e.item) { const r = by[e.item] || (by[e.item] = { ok: 0, missed: 0 }); e.type === 'missed' ? r.missed++ : r.ok++; if (e.request_to_hand_s) ts.push(e.request_to_hand_s); } });
    return { source: 'mock', by_item: by, median_request_to_hand_s: median(ts) };
  }
  if (path === '/command') return mockCommand(body);
  throw new Error('mock: no route ' + path);
}
function mockCommand(c) {
  M.cmd = c; const it = M.items[M.setting].find(x => x[0] === c.item);
  if (c.action === 'count') { mEmit('command', { item: null, action: 'count', source: c.source, accepted: true }); const s = M.out.length ? 'Out: ' + M.out.join(', ') + '.' : "Everything's on the tray."; mEmit('count', { item: null, say: s, out: [...M.out] }); return { accepted: true, say: s }; }
  if (c.action === 'got_it') { const ok = M.step === 'waiting_for_pull'; mEmit('command', { action: 'got_it', source: c.source, accepted: ok, reason: ok ? null : 'not holding anything out' }); if (ok && M.pull) M.pull(); return { accepted: ok, reason: ok ? null : 'not holding anything out' }; }
  if (c.action === 'handover' && !it) { mEmit('command', { action: 'handover', item: c.item, heard: c.heard, source: c.source, accepted: false, reason: c.item + ' is not in ' + M.setting, say: "That's not on this tray." }); return { accepted: false, reason: 'not in setting' }; }
  if (c.action === 'return') { const id = c.item || M.out[M.out.length - 1];
    if (!id) { mEmit('command', { action: 'return', source: c.source, accepted: false, reason: 'nothing is out', say: "Nothing's out." }); return { accepted: false, reason: 'nothing is out' }; }
    mEmit('command', { action: 'return', item: id, source: c.source, accepted: true }); mStep('returning', id);
    mLater(1500, () => { M.out.splice(M.out.indexOf(id), 1); mEmit('returned', { say: id.replace(/_/g, ' ') + ' back in its slot.' }); mStep('homing'); mLater(800, () => mStep('idle', null)); }); return { accepted: true }; }
  const busy = M.step !== 'idle' && M.step !== 'stopped';
  mEmit('command', { action: 'handover', item: c.item, heard: c.heard, source: c.source, accepted: true, say: it[1] + (busy ? ' next.' : ' coming.') });
  if (busy) { M.queue.push(c); return { accepted: true }; }
  mRun(c, it); return { accepted: true };
}
function mRun(c, it) {
  M.cmd = c; const t0 = Date.now() / 1000, miss = !!c.miss;
  mStep('finding', it[0]);
  mLater(700, () => { mStep('picking'); mLater(1200, () => { mStep('checking');
    mLater(600, () => {
      let retries = 0, extra = 0;
      if (miss) { retries = 1; extra = 2000; mEmit('missed', { say: 'Missed the ' + it[1] + ', trying again.', retries: 1 }); mStep('picking'); mStep('checking'); }
      mLater(extra, () => {
        mEmit('picked', { retries });
        if (it[2]) { mStep('setting_down'); mLater(1200, () => { M.out.push(it[0]); mEmit('set_down', { say: it[1] + ' down.', request_to_hand_s: +(Date.now() / 1000 - t0).toFixed(2), retries }); mHome(); }); return; }
        mStep('moving_to_hand'); mLater(1500, () => { mStep('waiting_for_pull');
          mEmit('handed', { request_to_hand_s: +(Date.now() / 1000 - t0).toFixed(2), retries });
          M.pull = () => { M.pull = null; mStep('releasing'); mLater(500, () => { M.out.push(it[0]); mEmit('released'); mHome(); }); };
          mLater(2500, () => M.pull && M.pull()); });
      });
    }); }); });
}
function mHome() { mStep('homing'); mLater(900, () => { mStep('idle', null); const n = M.queue.shift(); if (n) { const it = M.items[M.setting].find(x => x[0] === n.item); mRun(n, it); } }); }
function startMock() {
  const script = [[1000, { action: 'handover', item: 'hemostat', heard: 'hemostat please' }], [11000, { action: 'handover', item: 'scalpel', heard: 'scalpel' }],
    [20000, { action: 'count' }], [22000, { action: 'handover', item: 'mayo_scissors', heard: 'mayo scissors', miss: true }], [34000, { action: 'return', item: null }],
    [39000, { action: 'handover', item: 'banana', heard: 'banana' }]];
  const play = () => script.forEach(([ms, c]) => setTimeout(() => mockCommand(Object.assign({ id: String(Math.random()), source: 'voice', t: Date.now() / 1000 }, c)), ms));
  play(); setInterval(() => { M.out = []; play(); }, 45000);
  resync();
}

/* ---------- go ---------- */
renderAll(); renderCmds(); camStart(); connect();
