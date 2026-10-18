/* Scrub sim web: shared data and helpers (classic script, exposes window.SCRUB).
   Frame: arm base frame, meters, x forward, y left, z up (URDF base link). */
(function () {
  const S = {};

  /* ---------- where things live ---------- */
  const p = location.pathname, q = new URLSearchParams(location.search);
  S.isFile = location.protocol === 'file:';
  let origin = S.isFile ? '' : location.origin, modelsBase, apiBase;
  if (p.startsWith('/web/')) { modelsBase = '/models/'; apiBase = location.origin; }
  else if (p.includes('/sim/web/')) { modelsBase = p.slice(0, p.indexOf('/sim/web/')) + '/sim/models/'; apiBase = 'http://localhost:8002'; }
  else { modelsBase = '/models/'; apiBase = 'http://localhost:8002'; }
  S.modelsBase = q.get('models') || modelsBase;
  S.api = (q.get('api') || apiBase).replace(/\/$/, '');
  S.controller = (q.get('controller') || 'http://localhost:8000').replace(/\/$/, '');
  S.urdfUrl = S.modelsBase + 'so101/so101_new_calib.urdf';

  S.fetchJSON = async function (url, opt, ms) {
    const c = new AbortController(); const t = setTimeout(() => c.abort(), ms || 1500);
    try {
      const r = await fetch(url, Object.assign({ signal: c.signal }, opt || {}));
      if (!r.ok) throw new Error(r.status);
      return await r.json();
    } finally { clearTimeout(t); }
  };

  /* ---------- catalog: contract item ids, aliases, sharp flag ---------- */
  S.CATALOG = {
    surgical: { label: 'Operating room', items: [
      { id: 'scalpel', name: 'scalpel handle', aliases: ['scalpel', 'knife', 'blade', 'ten blade'], sharp: true, color: '#8c3b2e' },
      { id: 'hemostat', name: 'hemostat', aliases: ['kelly', 'clamp', 'hemo'], sharp: false, color: '#46607a' },
      { id: 'mayo_scissors', name: 'Mayo scissors', aliases: ['scissors', 'mayo'], sharp: true, color: '#6b5a2e' } ] },
    bench: { label: 'Robotics bench', items: [
      { id: 'needle_nose_pliers', name: 'needle-nose pliers', aliases: ['needle nose', 'pliers'], sharp: false, color: '#46607a' },
      { id: 'wire_cutters', name: 'wire cutters', aliases: ['cutters', 'snips', 'dikes'], sharp: true, color: '#8c3b2e' },
      { id: 'hex_key', name: 'hex key', aliases: ['allen key', 'allen wrench', 'hex'], sharp: false, color: '#5a6b3a' },
      { id: 'flathead_screwdriver', name: 'flathead screwdriver', aliases: ['flathead', 'flat head'], group: 'screwdriver', variant: 'flathead', sharp: false, color: '#8c3b2e' },
      { id: 'phillips_screwdriver', name: 'Phillips screwdriver', aliases: ['phillips', 'crosshead'], group: 'screwdriver', variant: 'Phillips', sharp: false, color: '#46607a' } ] },
    dental: { label: 'Dental office', items: [
      { id: 'mouth_mirror', name: 'mouth mirror', aliases: ['mirror'], sharp: false, color: '#46607a' },
      { id: 'explorer', name: 'explorer', aliases: ['probe', 'pick'], sharp: true, color: '#8c3b2e' },
      { id: 'cotton_pliers', name: 'cotton pliers', aliases: ['cotton tweezers', 'pickups'], sharp: false, color: '#5a6b3a' } ] }
  };
  /* Trays the pages offer, in order. Other CATALOG keys (dental) still load from a saved layout. */
  S.SHOWN_SETTINGS = ['surgical', 'bench'];
  S.itemInfo = function (id) {
    for (const s in S.CATALOG) for (const it of S.CATALOG[s].items) if (it.id === id) return it;
    return { id, name: id.replace(/_/g, ' '), aliases: [], sharp: false, color: '#555', custom: true };
  };
  S.settingOfItem = id => Object.keys(S.CATALOG).find(s => S.CATALOG[s].items.some(i => i.id === id));

  /* ---------- procedures / kits ----------
     tray: ids the arm can pick today (must be in the setting's catalog).
     extras: instruments the procedure needs that are not in the 3-item catalog yet (flagged, not on the tray).
     spares / consumables: kept on hand beside the tray. */
  S.PROCEDURES = {
    surgical: [
      { id: 'basic', name: 'Basic dissection', tray: ['scalpel', 'hemostat', 'mayo_scissors'], extras: ['forceps, toothed', 'needle driver'], spares: ['spare #10 blade'], consumables: ['gauze 4x4', 'suture 3-0', 'drape towels'] },
      { id: 'suture_removal', name: 'Suture removal', tray: ['hemostat', 'mayo_scissors'], extras: ['suture removal scissors'], spares: [], consumables: ['gauze 4x4', 'antiseptic swab', 'adhesive strips'] },
      { id: 'laceration', name: 'Laceration repair', tray: ['scalpel', 'hemostat', 'mayo_scissors'], extras: ['needle driver', 'forceps, toothed'], spares: ['spare #15 blade'], consumables: ['suture 4-0', 'lidocaine 1%', 'saline irrigation', 'gauze 4x4'] } ],
    bench: [
      { id: 'solder_header', name: 'Solder a header', tray: ['needle_nose_pliers', 'wire_cutters'], extras: ['soldering iron', 'tip cleaner'], spares: ['spare tip'], consumables: ['solder 0.8 mm', 'flux', 'desolder braid', 'headers'] },
      { id: 'servo_swap', name: 'Servo swap', tray: ['hex_key', 'needle_nose_pliers', 'wire_cutters'], extras: ['screwdriver, Phillips'], spares: ['spare servo horn', 'spare M2 screws'], consumables: ['zip ties', 'servo cable'] },
      { id: 'assembly', name: 'Frame assembly', tray: ['hex_key', 'needle_nose_pliers'], extras: ['screwdriver, Phillips'], spares: ['spare M3 screws'], consumables: ['thread locker', 'zip ties'] } ],
    dental: [
      { id: 'cleaning', name: 'Dental cleaning', tray: ['mouth_mirror', 'explorer'], extras: ['scaler', 'curette'], spares: ['spare mirror head'], consumables: ['prophy paste', 'floss', 'cotton rolls', 'gauze 2x2'] },
      { id: 'filling', name: 'Filling (composite)', tray: ['mouth_mirror', 'explorer', 'cotton_pliers'], extras: ['spoon excavator', 'plastic filling instrument'], spares: [], consumables: ['etchant', 'bonding agent', 'composite', 'cotton rolls', 'articulating paper'] },
      { id: 'exam', name: 'Exam and charting', tray: ['mouth_mirror', 'explorer', 'cotton_pliers'], extras: ['periodontal probe'], spares: [], consumables: ['bib', 'gauze 2x2'] } ]
  };

  /* ---------- layout (meters, base frame) ----------
     Internal shape is friendly (objects, radii). The file the sim reads (sim/layout.json) uses arrays:
       tray{center,size}, slots[[x,y]], setting_items{setting:[ids in slot order]}, return_spot[x,y], safe_spot[x,y],
       hand_zone[x,y,z], overhead_cam{pos,fovy}, plus table, handoff_region, poses which this UI keeps untouched.
     fromSim / toSim convert; extras the sim has no field for ride along under tray.yaw_deg and _kit. */
  const PICK_Z = 0.02, ABOVE_Z = 0.12;
  S.PICK_Z = PICK_Z; S.ABOVE_Z = ABOVE_Z;
  S.defaultSim = function () {
    return { setting: 'surgical', table: { center: [0.25, 0.0], size: [0.9, 0.8] }, tray: { center: [0.24, 0.0], size: [0.1, 0.26] },
      slots: [[0.24, -0.08], [0.24, 0.0], [0.24, 0.08]],
      setting_items: { surgical: ['hemostat', 'scalpel', 'mayo_scissors'], bench: ['needle_nose_pliers', 'wire_cutters', 'hex_key', 'flathead_screwdriver', 'phillips_screwdriver'], dental: ['mouth_mirror', 'explorer', 'cotton_pliers'] },
      setting_slots: { bench: [[0.24, -0.08], [0.24, 0.0], [0.24, 0.08], [0.30, -0.05], [0.30, 0.05]] },
      return_spot: [0.17, 0.17], safe_spot: [0.17, -0.18], hand_zone: [0.28, -0.14, 0.14],
      handoff_region: { min: [0.15, -0.25, 0.06], max: [0.4, 0.25, 0.3] },
      poses: { home: [0.0, -1.7, 1.55, 0.9, 0.0, 0.0], carry: [0.0, -0.9, 0.35, 1.48, 0.0, 0.0] }, overhead_cam: { pos: [0.24, 0.0, 0.75], fovy: 55 } };
  };
  S.fromSim = function (raw) {
    const d = S.defaultSim(), r = Object.assign({}, d, raw || {}), sid = S.CATALOG[r.setting] ? r.setting : 'surgical';
    const items = (r.setting_items && r.setting_items[sid]) || d.setting_items[sid];
    const cam = r.overhead_cam || d.overhead_cam, fh = 2 * cam.pos[2] * Math.tan(cam.fovy * Math.PI / 360);
    const yaw = (r.tray && r.tray.yaw_deg) || 0;
    return {
      setting: sid, procedure: (r._kit && r._kit.procedure) || S.PROCEDURES[sid][0].id,
      tray: { x: r.tray.center[0], y: r.tray.center[1], yaw_deg: yaw, d: r.tray.size[0], w: r.tray.size[1] },
      slots: ((r.setting_slots && r.setting_slots[sid]) || r.slots).map((p, i) => ({ item: items[i] || null, x: p[0], y: p[1], z: PICK_Z })),
      return_spot: { x: r.return_spot[0], y: r.return_spot[1], z: PICK_Z, r: 0.035 },
      safe_spot: { x: r.safe_spot[0], y: r.safe_spot[1], z: PICK_Z, r: 0.035 },
      hand_zone: { x: r.hand_zone[0], y: r.hand_zone[1], z: r.hand_zone[2], r: 0.06 },
      camera: { x: cam.pos[0], y: cam.pos[1], z: cam.pos[2], fovy: cam.fovy, fov_h: fh, fov_w: fh * 4 / 3 },
      _sim: JSON.parse(JSON.stringify(r))
    };
  };
  S.defaultLayout = () => S.fromSim(S.defaultSim());
  S.normalizeLayout = function (L) {
    if (!L || typeof L !== 'object') return S.defaultLayout();
    if (Array.isArray(L.slots) && Array.isArray(L.slots[0])) return S.fromSim(L);   // raw sim file
    const d = S.defaultLayout(), o = Object.assign({}, d, L);
    ['tray', 'return_spot', 'safe_spot', 'hand_zone', 'camera'].forEach(k => o[k] = Object.assign({}, d[k], L[k] || {}));
    o.slots = Array.isArray(L.slots) && L.slots.length ? L.slots.map(s => Object.assign({ z: PICK_Z }, s)) : d.slots;
    return o;
  };
  const r3 = v => Math.round(v * 1000) / 1000;
  S.toSim = function (L) {
    const o = JSON.parse(JSON.stringify(L._sim || S.defaultSim())), sid = L.setting, filled = L.slots.filter(s => s.item);
    const known = new Set(S.CATALOG[sid].items.map(i => i.id)), dropped = filled.filter(s => !known.has(s.item)).map(s => s.item);
    const keep = filled.filter(s => known.has(s.item));
    o.setting = sid; o.tray = Object.assign({}, o.tray, { center: [r3(L.tray.x), r3(L.tray.y)], size: [r3(L.tray.d), r3(L.tray.w)] });
    if (L.tray.yaw_deg) o.tray.yaw_deg = L.tray.yaw_deg; else delete o.tray.yaw_deg;
    // Keep other trays' slots when editing one tray, including the unchanged surgical scene.
    o.setting_slots = Object.assign({}, o.setting_slots, { [sid]: keep.map(s => [r3(s.x), r3(s.y)]) });
    if (sid === 'surgical') o.slots = o.setting_slots[sid];
    o.setting_items = Object.assign({}, o.setting_items, { [sid]: keep.map(s => s.item) });
    o.return_spot = [r3(L.return_spot.x), r3(L.return_spot.y)]; o.safe_spot = [r3(L.safe_spot.x), r3(L.safe_spot.y)];
    o.hand_zone = [r3(L.hand_zone.x), r3(L.hand_zone.y), r3(L.hand_zone.z)];
    o.overhead_cam = Object.assign({}, o.overhead_cam, { pos: [r3(L.camera.x), r3(L.camera.y), r3(L.camera.z)] });
    o._kit = { procedure: L.procedure };
    Object.defineProperty(o, '__dropped', { value: dropped, enumerable: false });
    return o;
  };
  S.loadLocalLayout = function () { try { const s = localStorage.getItem('scrub.layout'); return s ? JSON.parse(s) : null; } catch (e) { return null; } };
  S.saveLocalLayout = function (L) { try { localStorage.setItem('scrub.layout', JSON.stringify(L)); } catch (e) {} };
  S.getLayout = async function () {
    try { const L = await S.fetchJSON(S.api + '/layout'); return { layout: S.fromSim(L), from: 'server' }; } catch (e) {}
    const l = S.loadLocalLayout(); if (l) return { layout: S.normalizeLayout(l), from: 'browser' };
    return { layout: S.defaultLayout(), from: 'default' };
  };

  /* ---------- reach: analytic 2-link-plus-wrist estimate ---------- */
  // Defaults read off so101_new_calib.urdf; S.loadKinematics() refines them from the file.
  S.kin = { panX: 0.0388, shoulderR: 0.0304, shoulderZ: 0.1166, L1: 0.116, L2: 0.135, L3: 0.160, panLimit: 1.92, fromUrdf: false };
  S.loadKinematics = async function () {
    try {
      const r = await fetch(S.urdfUrl); if (!r.ok) throw 0;
      const doc = new DOMParser().parseFromString(await r.text(), 'text/xml');
      const xyz = n => { const j = doc.querySelector(`joint[name="${n}"] origin`); return j ? j.getAttribute('xyz').split(/\s+/).map(Number) : null; };
      const pan = xyz('shoulder_pan'), lift = xyz('shoulder_lift'), elbow = xyz('elbow_flex'), wf = xyz('wrist_flex'), wr = xyz('wrist_roll'), tip = xyz('gripper_frame_joint');
      if (!(pan && lift && elbow && wf && wr && tip)) throw 0;
      const k = S.kin;
      k.panX = pan[0]; k.shoulderZ = pan[2] + lift[2]; k.shoulderR = Math.hypot(lift[0], lift[1]) * 0.9;
      k.L1 = Math.hypot(elbow[0], elbow[1]); k.L2 = Math.hypot(wf[0], wf[1]); k.L3 = Math.hypot(wr[1], wr[2]) + Math.hypot(tip[0], tip[2]);
      const lim = doc.querySelector('joint[name="shoulder_pan"] limit'); if (lim) k.panLimit = Math.abs(+lim.getAttribute('upper'));
      k.fromUrdf = true;
    } catch (e) { /* keep defaults */ }
    return S.kin;
  };
  S.maxReach = () => { const k = S.kin; return k.shoulderR + k.L1 + k.L2 + k.L3 * 0.85; };   // horizontal, tool slightly tilted
  S.reachEstimate = function (x, y, z) {
    const k = S.kin, dx = x - k.panX, ang = Math.atan2(y, dx), r = Math.hypot(dx, y);
    const rr = r - k.shoulderR, zz = z - k.shoulderZ, d = Math.hypot(rr, zz);
    const dmax = k.L1 + k.L2 + k.L3 * 0.85, dmin = Math.max(0.05, Math.abs(k.L1 - k.L2) - 0.0) + 0.03;
    let err = 0;
    if (d > dmax) err = d - dmax; else if (d < dmin) err = dmin - d;
    if (r < 0.06 && z < 0.1) err = Math.max(err, 0.06 - r);              // inside the base column
    if (Math.abs(ang) > k.panLimit) err = Math.max(err, 0.05 + (Math.abs(ang) - k.panLimit) * r);
    return { reachable: err < 0.002, error_m: err, estimate: true, margin_m: dmax - d };
  };
  S.reachBatch = async function (pts) {
    try {
      const res = await S.fetchJSON(S.api + '/reach/batch', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ points: pts }) }, 2500);
      if (res && Array.isArray(res.results) && res.results.length === pts.length)
        return { source: 'sim', results: res.results.map(r => ({ reachable: !!r.reachable, error_m: +r.error_m || 0, estimate: false })) };
    } catch (e) {}
    return { source: 'estimate', results: pts.map(p => S.reachEstimate(p[0], p[1], p[2])) };
  };

  /* ---------- usage counts ---------- */
  S.MOCK_USAGE = { hemostat: 14, scalpel: 9, mayo_scissors: 4, mouth_mirror: 11, explorer: 8, cotton_pliers: 3, needle_nose_pliers: 10, wire_cutters: 6, hex_key: 5 };
  S.getUsage = async function () {
    try {
      const s = await S.fetchJSON(S.controller + '/stats', null, 1200);
      const out = {}; const walk = o => { if (o && typeof o === 'object') for (const k in o) { if (S.MOCK_USAGE[k] !== undefined) { const v = o[k]; out[k] = (out[k] || 0) + (typeof v === 'number' ? v : (v && (v.n || v.count || v.total)) || 0); } else walk(o[k]); } };
      walk(s); if (Object.keys(out).length) return { source: 'GET /stats', counts: out };
    } catch (e) {}
    return { source: 'mock counts', counts: S.MOCK_USAGE };
  };

  /* ---------- exports ---------- */
  S.settingJSON = function (L) {
    const sid = L.setting, cat = S.CATALOG[sid];
    return {
      id: sid, label: cat.label,
      items: L.slots.filter(s => s.item).map(s => {
        const it = S.itemInfo(s.item);
        return { id: it.id, name: it.name, aliases: it.aliases.slice(), sharp: !!it.sharp, slot: null,
          ...(it.group ? {group: it.group, variant: it.variant} : {}),
          pick_instruction: 'pick the ' + it.name, return_instruction: 'return the ' + it.name };
      }),
      return_spot: null
    };
  };
  S.layoutJSON = function (L) { return S.toSim(L); };   // the sim/layout.json format

  window.SCRUB = S;
})();
