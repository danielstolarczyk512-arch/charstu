(function () {
const $ = (i) => document.getElementById(i);
const rad = (x) => x * Math.PI / 180;
const dark = matchMedia('(prefers-color-scheme: dark)').matches;
const S = { az: 40, el: 5, di: 4, fv: 35, ea: -35, ee: 22, fmt: '16:9', char: null, shot: null };
let CFG = {};

async function api(path, opts) {
  const r = await fetch(path, opts);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail || ('HTTP ' + r.status));
  return j;
}
const post = (p, body) => api(p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
const say = (t, bad) => { $('msg').textContent = t; $('msg').style.color = bad ? 'var(--bad)' : ''; };
const shotBody = () => ({ character_id: S.char, az: S.az, el: S.el, dist: S.di, fov: S.fv, fmt: S.fmt,
  action: $('action').value, outfit: $('outfit').value,
  image_model: $('mGen').value.trim() || null, edit_model: $('mEdit').value.trim() || null, use_refs: $('useRefs').checked });

/* ---------- scena 3D ---------- */
const cv = $('cv'), wrap = $('wrap'), frame = $('frame'), tag = $('tag');
const R = new THREE.WebGLRenderer({ canvas: cv, antialias: true });
R.setScissorTest(true);
const scene = new THREE.Scene();
scene.add(new THREE.HemisphereLight(0xffffff, 0x888888, 0.9));
const dl = new THREE.DirectionalLight(0xffffff, 0.8); dl.position.set(3, 6, 4); scene.add(dl);
const grid = new THREE.GridHelper(12, 24, dark ? 0x666666 : 0xaaaaaa, dark ? 0x3a3a3a : 0xd5d5d5); scene.add(grid);
const mat = new THREE.MeshStandardMaterial({ color: dark ? 0xb4b2a9 : 0x888780, roughness: 0.7 });
const acc = new THREE.MeshStandardMaterial({ color: 0x378add, roughness: 0.5 });
const man = new THREE.Group();
const add = (g, m, x, y, z) => { const o = new THREE.Mesh(g, m); o.position.set(x, y, z); man.add(o); return o; };
add(new THREE.SphereGeometry(0.13, 24, 18), mat, 0, 1.62, 0);
add(new THREE.ConeGeometry(0.03, 0.08, 12), acc, 0, 1.61, 0.14).rotation.x = Math.PI / 2;
add(new THREE.CylinderGeometry(0.05, 0.05, 0.08, 12), mat, 0, 1.5, 0);
add(new THREE.BoxGeometry(0.4, 0.55, 0.2), mat, 0, 1.15, 0);
add(new THREE.CylinderGeometry(0.045, 0.04, 0.55, 12), mat, -0.27, 1.15, 0);
add(new THREE.CylinderGeometry(0.045, 0.04, 0.55, 12), mat, 0.27, 1.15, 0);
add(new THREE.CylinderGeometry(0.07, 0.055, 0.8, 12), mat, -0.1, 0.4, 0);
add(new THREE.CylinderGeometry(0.07, 0.055, 0.8, 12), mat, 0.1, 0.4, 0);
add(new THREE.BoxGeometry(0.4, 0.04, 0.05), acc, 0, 1.3, 0.11);
scene.add(man);
const shot = new THREE.PerspectiveCamera(35, 16 / 9, 0.1, 40);
const helper = new THREE.CameraHelper(shot); scene.add(helper);
const edit = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
let D;

const aspect = () => S.fmt === '16:9' ? 16 / 9 : 9 / 16;
const ty = () => 1.0 + 0.6 * Math.max(0, Math.min(1, (4 - S.di) / 2.5));
function updShot() {
  const e = rad(S.el), a = rad(S.az), t = ty();
  shot.position.set(S.di * Math.sin(a) * Math.cos(e), t + S.di * Math.sin(e), S.di * Math.cos(a) * Math.cos(e));
  shot.fov = S.fv; shot.aspect = aspect(); shot.updateProjectionMatrix();
  shot.lookAt(0, t, 0); shot.updateMatrixWorld(true); helper.update();
}
function updEdit() {
  const e = rad(S.ee), a = rad(S.ea);
  edit.position.set(9 * Math.sin(a) * Math.cos(e), 1 + 9 * Math.sin(e), 9 * Math.cos(a) * Math.cos(e));
  edit.lookAt(0, 1, 0);
}
function size() {
  const W = wrap.clientWidth, H = wrap.clientHeight;
  R.setPixelRatio(Math.min(devicePixelRatio || 1, 2)); R.setSize(W, H, false);
  edit.aspect = W / H; edit.updateProjectionMatrix();
  const iw = aspect() > 1 ? 240 : 108, ih = Math.round(iw / aspect());
  frame.style.width = iw + 'px'; frame.style.height = ih + 'px';
  tag.style.right = '14px'; tag.style.bottom = (ih + 14) + 'px';
  return { W, H, iw, ih };
}
function render() {
  const bg = dark ? 0x262624 : 0xf1efe8, bg2 = dark ? 0x1a1a19 : 0xffffff;
  R.setViewport(0, 0, D.W, D.H); R.setScissor(0, 0, D.W, D.H); R.setClearColor(bg); R.clear();
  helper.visible = true; R.render(scene, edit);
  const x = D.W - 10 - D.iw, y = 10;
  R.setViewport(x, y, D.iw, D.ih); R.setScissor(x, y, D.iw, D.ih); R.setClearColor(bg2); R.clear();
  helper.visible = false; R.render(scene, shot);
}

/* ---------- opis kamery (ta sama logika co app/camera.py) ---------- */
function describe() {
  const a = Math.abs(S.az), an = a <= 22 ? 'przód' : a <= 67 ? '3/4' : a <= 112 ? 'profil' : a <= 157 ? '3/4 z tyłu' : 'tył';
  const hn = S.el < -15 ? 'z dołu' : S.el <= 15 ? 'poziom oczu' : S.el <= 50 ? 'z góry' : 'z lotu ptaka';
  const d = S.di, pn = d < 2.2 ? 'zbliżenie twarzy' : d < 3.2 ? 'półzbliżenie' : d < 4.5 ? 'plan średni' : d < 6 ? 'cała postać' : 'plan ogólny';
  return `${an}, ${hn}, ${pn}, ok. ${Math.round(12 / Math.tan(rad(S.fv / 2)))} mm`;
}
let previewTimer;
function labels() {
  $('azv').textContent = Math.round(S.az) + '°'; $('elv').textContent = Math.round(S.el) + '°';
  $('div').textContent = S.di.toFixed(1) + ' m'; $('fvv').textContent = Math.round(S.fv) + '°';
  $('camPl').textContent = describe();
}
function changed() {
  S.shot = null; labels(); updShot(); updEdit(); render();
  clearTimeout(previewTimer);
  previewTimer = setTimeout(async () => {
    if (!S.char) { $('prompt').textContent = 'Wybierz postać, aby zobaczyć prompt.'; return; }
    try {
      const p = await post('/api/preview', shotBody());
      $('prompt').textContent = p.image_prompt;
      const lab = { delta: 'instrukcja zmiany (edycja)', rich_caption: 'gęsty opis (Krea)', compact: 'zwięzły opis (Z-Image)',
        natural: 'jeden spójny opis', spatial: 'opis z relacjami przestrzennymi (Qwen)' }[p.style] || p.style;
      $('mNote').style.color = ''; $('mNote').textContent = `Operacja: ${p.kind === 'edit' ? 'edycja z kanonem' : 'generowanie'} · model: ${p.model} · styl promptu: ${lab}`;
    } catch (e) { $('mNote').style.color = 'var(--bad)'; $('mNote').textContent = e.message; $('prompt').textContent = ''; }
  }, 250);
}
['az', 'el', 'di', 'fv'].forEach((k) => $(k).addEventListener('input', function () {
  S[k] = k === 'di' ? this.value / 10 : +this.value; changed();
}));
document.querySelectorAll('[data-az]').forEach((b) => b.onclick = () => { S.az = +b.dataset.az; $('az').value = S.az; changed(); });
document.querySelectorAll('[data-fmt]').forEach((b) => b.onclick = () => {
  document.querySelectorAll('[data-fmt]').forEach((x) => x.classList.remove('on')); b.classList.add('on');
  S.fmt = b.dataset.fmt; D = size(); changed();
});
$('action').addEventListener('input', changed);
$('outfit').addEventListener('input', changed);
let drag = null;
cv.addEventListener('pointerdown', (ev) => {
  const r = cv.getBoundingClientRect(), x = ev.clientX - r.left, y = ev.clientY - r.top;
  drag = { m: (x >= D.W - 10 - D.iw && y >= D.H - 10 - D.ih) ? 's' : 'e', x: ev.clientX, y: ev.clientY };
  cv.setPointerCapture(ev.pointerId); cv.style.cursor = 'grabbing';
});
cv.addEventListener('pointermove', (ev) => {
  if (!drag) return;
  const dx = ev.clientX - drag.x, dy = ev.clientY - drag.y; drag.x = ev.clientX; drag.y = ev.clientY;
  if (drag.m === 's') {
    S.az = ((S.az - dx * 0.6 + 540) % 360) - 180; S.el = Math.max(-60, Math.min(85, S.el + dy * 0.3));
    $('az').value = S.az; $('el').value = S.el; changed();
  } else { S.ea -= dx * 0.5; S.ee = Math.max(-10, Math.min(85, S.ee + dy * 0.3)); updEdit(); render(); }
});
cv.addEventListener('pointerup', () => { drag = null; cv.style.cursor = 'grab'; });
window.addEventListener('resize', () => { D = size(); render(); });

/* ---------- postacie i kanon ---------- */
async function loadChars() {
  const list = await api('/api/characters');
  $('chars').innerHTML = '';
  list.forEach((c) => {
    const d = document.createElement('div');
    d.className = 'char' + (c.id === S.char ? ' on' : '');
    d.textContent = c.name + (c.archetype ? ' · ' + c.archetype : '');
    d.onclick = () => { S.char = c.id; S.shot = null; loadChars(); refresh(); changed(); loadCharCard(); };
    $('chars').appendChild(d);
  });
  $('canonBox').hidden = !S.char;
}
$('charForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  try {
    const c = await post('/api/characters', {
      name: f.get('name'), archetype: f.get('archetype'), traits: f.get('traits'),
      outfit: f.get('outfit'), style: f.get('style'), adult_fictional: f.get('adult_fictional') === 'on' });
    S.char = c.id; e.target.reset(); await loadChars(); refresh(); changed(); say('Postać utworzona.');
  } catch (err) { say(err.message, true); }
});
$('canonForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  try { await api(`/api/characters/${S.char}/canon`, { method: 'POST', body: new FormData(e.target) }); e.target.reset(); refresh(); say('Dodano do kanonu.'); }
  catch (err) { say(err.message, true); }
});

/* Kreator cech: listy wyboru dopisuja angielskie frazy do pola "Cechy" (zamiast pisac z glowy). Wybor tej samej grupy zastepuje poprzedni. */
const ATTRS = {
  'włosy kolor': ['silver', 'platinum blonde', 'golden blonde', 'auburn', 'copper red', 'jet black', 'chestnut brown', 'dark brown', 'white', 'pastel pink', 'deep blue'],
  'włosy fryzura': ['long braid', 'long loose waves', 'short bob', 'pixie cut', 'high ponytail', 'twin braids', 'messy bun', 'shaved sides with long top', 'curly afro'],
  'oczy': ['green eyes', 'blue eyes', 'amber eyes', 'grey eyes', 'brown eyes', 'violet eyes', 'heterochromia'],
  'skóra': ['pale skin', 'fair skin with freckles', 'olive skin', 'tan skin', 'brown skin', 'dark skin'],
  'budowa': ['slim build', 'athletic build', 'curvy build', 'muscular build', 'petite frame', 'tall and lean'],
  'wiek (dorosły)': ['in her early twenties', 'in her late twenties', 'in her thirties', 'in her forties', 'in her fifties'],
  'znak szczególny': ['a scar on the left cheek', 'a beauty mark under the right eye', 'a tattoo on the forearm', 'a nose piercing', 'pointed elven ears', 'no distinguishing marks'],
};
function buildAttrs(box, input) {
  const groups = {};
  Object.entries(ATTRS).forEach(([g, opts]) => {
    const s = document.createElement('select'); s.title = g;
    s.append(new Option(g, ''));
    opts.forEach((o) => s.append(new Option(o, o)));
    s.onchange = () => {
      const parts = input.value.split(',').map((x) => x.trim()).filter(Boolean).filter((x) => x !== groups[g]);
      if (s.value) parts.push(s.value);
      groups[g] = s.value; input.value = parts.join(', '); s.value = '';
    };
    box.append(s);
  });
}
document.querySelectorAll('.attrs').forEach((b) => buildAttrs(b, b.closest('form').elements.traits));

async function loadPoses() {
  const sel = $('poseSel'), keep = sel.value;
  sel.innerHTML = '<option value="">Bez pozy z referencji</option>';
  const pr = $('poseForm').elements.preset;
  if (!S.char) return;
  const r = await api(`/api/characters/${S.char}/poses`);
  if (pr.options.length <= 1) r.presets.forEach((p) => pr.append(new Option(p, p)));
  r.poses.forEach((a) => sel.append(new Option(a.label.replace('poza:', '') + ' #' + a.id, a.id)));
  if ([...sel.options].some((o) => o.value === keep)) sel.value = keep;
}
$('poseForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  try {
    const fd = new FormData(e.target);
    if (!fd.get('file') || !fd.get('file').name) fd.delete('file');
    await api(`/api/characters/${S.char}/poses`, { method: 'POST', body: fd });
    e.target.reset(); await loadPoses(); lastSig = ''; say('Dodano pozę do biblioteki.');
  } catch (err) { say(err.message, true); }
});

let lastSig = '';
let picked = [];  // kolejnosc zaznaczenia = kolejnosc w sklejce
let bedId = null, voiceIds = [];
$('stitchBtn').onclick = async () => {
  try {
    say('Sklejanie…');
    const r = await post('/api/stitch', { artifact_ids: picked, fade: +$('fade').value || 0, audio_mode: $('aMode').value,
      bed_artifact_id: bedId, bed_db: +$('bedDb').value || -20, voice_artifact_ids: voiceIds });
    picked = []; voiceIds = []; lastSig = ''; refresh();
    const loud = r.info.mixed_lufs !== undefined ? `, głośność ${r.info.mixed_lufs.toFixed(1)} LUFS` : '';
    say(`Sklejono ${r.info.clips} klipy (${r.info.duration.toFixed(1)} s${loud}). Skok na granicach (różnica pikseli): ` +
        r.boundary_jumps.map((j) => j.pixel_diff).join(', '));
  } catch (err) { say(err.message, true); }
};

$('sheetBtn').onclick = async () => {
  if (!confirm('Wygenerować arkusz postaci (8 obrazów z kanonu: 4 widoki i 4 miny)? Zużyje ok. 30-40 Spark wartości z planu.')) return;
  try { const r = await post(`/api/characters/${S.char}/sheet`, { fmt: S.fmt }); say(`Zlecono arkusz: ${r.items.length} obrazów. Wyniki pojawią się w galerii; najlepsze zatwierdź do kanonu.`); lastSig = ''; }
  catch (err) { say(err.message, true); }
};

/* ---------- edycja postaci i szafa ---------- */
async function loadCharCard() {
  $('charEdit').hidden = !S.char;
  loadPoses().catch(() => {});
  if (!S.char) return;
  const c = (await api('/api/characters')).find((x) => x.id === S.char);
  if (!c) return;
  const f = $('charEditForm');
  ['name', 'archetype', 'traits', 'outfit', 'style'].forEach((k) => { f[k].value = c[k] || ''; });
  const ws = await api(`/api/characters/${S.char}/outfits`);
  const box = $('wardrobe'); box.innerHTML = '';
  if (!ws.length) box.innerHTML = '<div class="muted">Pusta szafa. Dodaj stroje, a potem wybieraj je w ujęciach.</div>';
  ws.forEach((o) => {
    const row = document.createElement('div'); row.className = 'job';
    row.innerHTML = `<b>${esc(o.name)}</b><div class="muted">${esc(o.description)}</div>`;
    const use = document.createElement('button'); use.textContent = 'użyj w ujęciu'; use.className = 'alt';
    use.onclick = () => { $('outfit').value = o.description; $('outfit').dispatchEvent(new Event('input')); say(`Strój „${o.name}” wpisany w pole stroju ujęcia.`); };
    const rm = document.createElement('button'); rm.textContent = 'usuń'; rm.className = 'alt';
    rm.onclick = async () => { await api('/api/outfits/' + o.id, { method: 'DELETE' }); loadCharCard(); };
    row.append(use, ' ', rm); box.appendChild(row);
  });
}
$('charEditForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const f = e.target;
  try {
    await api(`/api/characters/${S.char}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(Object.fromEntries(['name', 'archetype', 'traits', 'outfit', 'style'].map((k) => [k, f[k].value]))) });
    await loadChars(); changed(); say('Zapisano kartę postaci. Nowe ujęcia użyją nowego opisu.');
  } catch (err) { say(err.message, true); }
});
$('charDel').onclick = async () => {
  if (!S.char || !confirm('Usunąć postać wraz z kanonem i szafą? (wyniki w galerii zostają w plikach)')) return;
  try { await api(`/api/characters/${S.char}`, { method: 'DELETE' }); S.char = null; await loadChars(); $('charEdit').hidden = true; say('Postać usunięta.'); }
  catch (err) { say(err.message, true); }
};
$('wardForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const f = e.target;
  try { await post(`/api/characters/${S.char}/outfits`, { name: f.name.value, description: f.description.value }); f.reset(); loadCharCard(); }
  catch (err) { say(err.message, true); }
});

/* ---------- glos, kwestie, muzyka ---------- */
async function loadVoice() {
  if (!S.char) { $('voiceInfo').textContent = 'Wybierz postać.'; return; }
  const v = await api(`/api/characters/${S.char}/voice`);
  if (!$('vSel').options.length) v.studio_voices.forEach((x) => $('vSel').add(new Option(x, x)));
  $('vSel').value = v.voice || 'serena';
  $('voiceInfo').textContent = v.mode === 'clone'
    ? `Głos: klon zaprojektowanej próbki (#${v.ref_artifact_id}), ${v.language}`
    : `Głos: studyjny „${v.voice}”, ${v.language}`;
}
$('vSet').onclick = async () => {
  try { await api(`/api/characters/${S.char}/voice`, { method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ voice: $('vSel').value, language: 'english' }) }); await loadVoice(); say('Ustawiono głos studyjny.'); }
  catch (err) { say(err.message, true); }
};
$('vDesign').onclick = async () => {
  try { if (!$('vDesc').value.trim()) throw new Error('Wpisz opis głosu (po angielsku).');
    await post(`/api/characters/${S.char}/voice/design`, { description: $('vDesc').value, language: 'english' });
    say('Projektuję głos (jednorazowo). Po wygenerowaniu próbki postać przełączy się na jej klon.'); lastSig = ''; }
  catch (err) { say(err.message, true); }
};
$('vSpeak').onclick = async () => {
  try { await post('/api/speech', { character_id: S.char, text: $('vText').value }); $('vText').value = ''; say('Zlecono kwestię.'); lastSig = ''; }
  catch (err) { say(err.message, true); }
};
$('mMake').onclick = async () => {
  try { await post('/api/music', { character_id: S.char, prompt: $('mPrompt').value, duration: +$('mDur').value || 30 }); say('Zlecono muzykę.'); lastSig = ''; }
  catch (err) { say(err.message, true); }
};
async function refresh() {
  if (!S.char) return;
  const [canon, cov, jobs, arts] = await Promise.all([
    api(`/api/characters/${S.char}/canon`), api(`/api/coverage?character_id=${S.char}`),
    api(`/api/jobs?character_id=${S.char}`), api(`/api/artifacts?character_id=${S.char}`)]);
  const sig = JSON.stringify([canon, cov, jobs.map((j) => [j.id, j.status, j.error]), arts.map((a) => [a.id, a.approved, a.face_score, a.face_min])]);
  if (sig === lastSig) return;
  lastSig = sig;
  loadVoice().catch(() => {});
  $('coverage').innerHTML = Object.entries(cov).map(([k, v]) => `<span class="chip ${v ? 'y' : 'n'}">${k}</span>`).join('');
  $('canon').innerHTML = '';
  canon.forEach((a) => {
    const d = document.createElement('div');
    d.innerHTML = `<img src="/files/${a.path}"><div style="padding:2px 4px">${a.role} · ${a.tier}</div>`;
    const b = document.createElement('button'); b.textContent = 'usuń';
    b.onclick = async () => { await api('/api/canon/' + a.id, { method: 'DELETE' }); refresh(); };
    d.appendChild(b); $('canon').appendChild(d);
  });
  $('jobs').innerHTML = jobs.slice(0, 12).map((j) =>
    `<div class="job">#${j.id} ${j.kind} <span class="s-${j.status}">${j.status}</span>` +
    (j.error ? `<div class="muted">${esc(j.error)}</div>` : '') + '</div>').join('') || '<div class="muted">Brak zadań.</div>';
  $('gallery').innerHTML = '';
  arts.forEach((a) => {
    const d = document.createElement('div');
    const media = a.kind === 'video'
      ? `<video src="/files/${a.path}" controls loop muted></video>`
      : a.kind === 'audio' ? `<audio src="/files/${a.path}" controls style="width:100%"></audio>` : `<img src="/files/${a.path}">`;
    d.innerHTML = media;
    const info = document.createElement('div'); info.className = 'muted'; info.style.padding = '2px 4px';
    if (a.kind === 'audio') {
      info.textContent = a.label || ('audio #' + a.id);
    } else if (a.face_note) {
      const n = JSON.parse(a.face_note);
      const none = a.face_score === null || a.face_score === undefined;
      info.textContent = none ? 'twarz: brak wykrycia' : `twarz ${a.face_score.toFixed(2)}` +
        (a.face_min !== null ? ` (min ${a.face_min.toFixed(2)})` : '') + ' vs ' + n.vs;
      info.title = 'Miara orientacyjna (ArcFace). Na stylizowanych twarzach nie odróżnia tej samej postaci od nowej o tym samym opisie, ' +
        'a kąt kamery obniża wynik. W klipie liczy się trend względem kadru źródłowego.' +
        (n.frames ? ' Klatki: ' + n.frames.map((v) => v === null ? '—' : v).join(', ') : '');
    } else {
      const mb = document.createElement('button'); mb.textContent = 'zmierz twarz';
      mb.onclick = async () => { mb.textContent = '…'; try { await post(`/api/artifacts/${a.id}/measure`, {}); lastSig = ''; refresh(); }
        catch (err) { say(err.message, true); mb.textContent = 'zmierz twarz'; } };
      info.appendChild(mb);
    }
    d.appendChild(info);
    if (a.label && a.kind !== 'audio') {
      const lb = document.createElement('div'); lb.className = 'muted'; lb.style.padding = '0 4px';
      lb.textContent = a.label.replace(/^arkusz:\w+:/, 'arkusz: '); d.appendChild(lb);
    }
    const t = document.createElement('div'); t.className = 'tools';
    if (a.kind === 'video') {
      const lab = document.createElement('label'); lab.className = 'muted';
      const cb = document.createElement('input'); cb.type = 'checkbox'; cb.checked = picked.includes(a.id);
      cb.onchange = () => { picked = cb.checked ? [...picked, a.id] : picked.filter((x) => x !== a.id); };
      lab.append(cb, ' #' + a.id + ' do sklejki'); t.appendChild(lab);
    }
    if (a.kind === 'audio') {
      const bedB = document.createElement('button'); bedB.textContent = bedId === a.id ? '✓ podkład' : 'podkład';
      bedB.title = 'Podkład muzyczny pod całą sklejką';
      bedB.onclick = () => { bedId = bedId === a.id ? null : a.id; lastSig = ''; refresh(); };
      const lab = document.createElement('label'); lab.className = 'muted';
      const cb = document.createElement('input'); cb.type = 'checkbox'; cb.checked = voiceIds.includes(a.id);
      cb.onchange = () => { voiceIds = cb.checked ? [...voiceIds, a.id] : voiceIds.filter((x) => x !== a.id); };
      lab.append(cb, ' kwestia'); lab.title = 'I-ta zaznaczona kwestia startuje przy i-tym klipie';
      t.append(bedB, lab);
    }
    if (a.kind === 'image') {
      const sel = document.createElement('select');
      ['front', 'three_quarter', 'profile', 'back', 'face', 'body'].forEach((r) => sel.add(new Option(r, r)));
      const mr = /^arkusz:(\w+):/.exec(a.label || ''); if (mr) sel.value = mr[1];   // arkusz podpowiada role kanonu
      const fix = document.createElement('button'); fix.textContent = 'popraw'; fix.title = 'Zmień jedną cechę tego obrazu, reszta zostaje';
      fix.onclick = async () => {
        const ins = prompt('Co zmienić w tym obrazie? (najlepiej po angielsku, np. "make her braid longer and add a thin scar on her left cheek")');
        if (!ins) return;
        try { await post(`/api/characters/${S.char}/refine`, { source_artifact_id: a.id, instruction: ins, count: 2 }); say('Zlecono 2 warianty poprawki.'); lastSig = ''; }
        catch (err) { say(err.message, true); }
      };
      const ok = document.createElement('button'); ok.textContent = a.approved ? 'w kanonie' : 'do kanonu';
      ok.onclick = async () => {
        const f = new FormData(); f.append('role', sel.value);
        await api(`/api/artifacts/${a.id}/approve`, { method: 'POST', body: f }); refresh();
      };
      const clip = document.createElement('button'); clip.textContent = 'klip stąd';
      clip.onclick = () => generate('video', a.id);
      const st = document.createElement('button'); st.textContent = flf.start === a.id ? '✓ start' : 'start';
      st.title = 'Pierwsza klatka klipu start→koniec';
      st.onclick = () => { flf.start = a.id; lastSig = ''; say(`Klip start→koniec: start #${flf.start}, koniec ${flf.end ? '#' + flf.end : '—'}`); refresh(); };
      const en = document.createElement('button'); en.textContent = flf.end === a.id ? '✓ koniec' : 'koniec';
      en.title = 'Ostatnia klatka klipu start→koniec (te same proporcje co start)';
      en.onclick = () => { flf.end = a.id; lastSig = ''; say(`Klip start→koniec: start ${flf.start ? '#' + flf.start : '—'}, koniec #${flf.end}`); refresh(); };
      t.append(sel, ok, fix, clip, st, en);
    }
    d.appendChild(t); $('gallery').appendChild(d);
  });
}

async function ensureShot() {
  if (!S.char) throw new Error('Najpierw wybierz lub utwórz postać.');
  if (!S.shot) S.shot = (await post('/api/shots', shotBody())).id;
  return S.shot;
}
const flf = { start: null, end: null };
async function generate(kind, sourceId, endId) {
  try {
    const sid = await ensureShot();
    const r = await post(`/api/shots/${sid}/generate`, { kind, count: endId ? 1 : +$('count').value,
      source_artifact_id: sourceId || null, end_artifact_id: endId || null,
      image_model: $('mGen').value.trim() || null, edit_model: $('mEdit').value.trim() || null, use_refs: $('useRefs').checked,
      pose_artifact_id: kind === 'image' && $('poseSel').value ? +$('poseSel').value : null });
    say(`Zlecono ${r.jobs.length} zadań (${r.kind}${r.refs.length ? ', ref: ' + r.refs.length : ', bez referencji'}).`); refresh();
  } catch (err) { say(err.message, true); }
}
$('genImg').onclick = () => generate('image');
$('genVid').onclick = () => generate('video');
$('genFlf').onclick = () => {
  if (!flf.start || !flf.end) { say('Wybierz w wynikach obraz "start" i obraz "koniec" (te same proporcje).', true); return; }
  generate('video', flf.start, flf.end);
};
$('est').onclick = async () => {
  try { const sid = await ensureShot(); say('Wycena: ' + JSON.stringify(await post(`/api/shots/${sid}/estimate`, { kind: 'image' })).slice(0, 300)); }
  catch (err) { say(err.message, true); }
};

/* ---------- asystent ---------- */
const aiHistory = [];
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
function setCamera(s) {
  S.az = s.az; S.el = s.el; S.di = s.dist; S.fv = s.fov; S.fmt = s.fmt;
  $('az').value = s.az; $('el').value = s.el; $('di').value = Math.round(s.dist * 10); $('fv').value = s.fov;
  document.querySelectorAll('[data-fmt]').forEach((x) => x.classList.toggle('on', x.dataset.fmt === s.fmt));
  $('action').value = s.action || ''; $('outfit').value = s.outfit || '';
  D = size(); changed();
}
function aiCard(html, btnText, onclick) {
  const d = document.createElement('div'); d.className = 'job'; d.innerHTML = html;
  const b = document.createElement('button'); b.textContent = btnText; b.style.marginTop = '4px'; b.onclick = onclick;
  d.appendChild(b); return d;
}
$('aiGo').onclick = async () => {
  const msg = $('aiMsg').value.trim();
  if (!msg) { $('aiState').textContent = 'Wpisz polecenie.'; return; }
  $('aiState').textContent = 'myślę…'; $('aiGo').disabled = true;
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 150000);  // panel nigdy nie wisi dluzej niz 150 s
  try {
    const rs = await fetch('/api/assistant', { method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: ctl.signal,
      body: JSON.stringify({ message: msg, history: aiHistory, character_id: S.char,
        camera: { az: S.az, el: S.el, dist: S.di, fov: S.fv, fmt: S.fmt } }) });
    const r = await rs.json().catch(() => ({}));
    if (!rs.ok) throw new Error(r.detail || ('HTTP ' + rs.status));
    aiHistory.push({ role: 'user', content: msg }, { role: 'assistant', content: r.reply });
    const out = $('aiOut'); out.innerHTML = '';
    const rep = document.createElement('div'); rep.style.margin = '6px 0'; rep.textContent = r.reply;
    if (r.refused) rep.style.color = 'var(--bad)';
    out.appendChild(rep);
    if (r.character) {
      const c = r.character;
      out.appendChild(aiCard(`<b>Postać:</b> ${esc(c.name) || '—'}<br><span class="muted">${esc(c.archetype)}; ${esc(c.traits)}; ${esc(c.outfit)}; ${esc(c.style)}</span>`,
        'Wczytaj do formularza postaci', () => {
          const f = $('charForm'); document.querySelector('details').open = true;
          for (const k of ['name', 'archetype', 'traits', 'outfit', 'style']) f[k].value = c[k] || '';
          say('Formularz postaci uzupełniony. Zaznacz potwierdzenie (fikcyjna i dorosła) i kliknij "Utwórz".');
        }));
    }
    (r.shots || []).forEach((s, i) => {
      out.appendChild(aiCard(`<b>${i + 1}. ${esc(s.title) || 'Ujęcie'}</b><br><span class="muted">kąt ${Math.round(s.az)}°, wys. ${Math.round(s.el)}°, ` +
        `${s.dist.toFixed(1)} m, ${esc(s.fmt)}</span><br>${esc(s.action)}${s.outfit ? '<br><span class="muted">strój: ' + esc(s.outfit) + '</span>' : ''}`,
        'Wczytaj do kamery', () => { setCamera(s); say(`Wczytano ujęcie ${i + 1}. Sprawdź i kliknij "Generuj obraz".`); }));
    });
    $('aiMsg').value = ''; $('aiState').textContent = '';
  } catch (err) {
    $('aiState').textContent = ''; $('aiOut').innerHTML = '';
    say(err.name === 'AbortError' ? 'Asystent nie odpowiedział w 150 s. Spróbuj krótszego polecenia albo zapytaj ponownie.' : err.message, true);
  }
  clearTimeout(timer);
  $('aiGo').disabled = false;
};

/* ---------- wybor modelu ---------- */
async function initModels() {
  const m = await api('/api/models');
  const opt = (p) => { const o = document.createElement('option'); o.value = p.id;
    o.label = `${p.label}${p.tested ? ' (sprawdzony)' : ''}`; return o; };
  m.generate.forEach((p) => $('dlGen').appendChild(opt(p)));
  m.edit.forEach((p) => $('dlEdit').appendChild(opt(p)));
  const load = (k, d) => { try { return localStorage.getItem(k) || d; } catch (e) { return d; } };
  $('mGen').value = load('mGen', m.defaults.generate); $('mEdit').value = load('mEdit', m.defaults.edit);
  try { $('useRefs').checked = localStorage.getItem('useRefs') !== '0'; } catch (e) { /* brak localStorage */ }
  const save = () => { try { localStorage.setItem('mGen', $('mGen').value); localStorage.setItem('mEdit', $('mEdit').value);
    localStorage.setItem('useRefs', $('useRefs').checked ? '1' : '0'); } catch (e) { /* ignoruj */ } changed(); };
  ['mGen', 'mEdit'].forEach((i) => $(i).addEventListener('change', save));
  $('useRefs').addEventListener('change', save);
}

/* ---------- start ---------- */
(async function init() {
  D = size(); await initModels(); changed();
  CFG = await api('/api/config');
  $('status').textContent = `dostawca: ${CFG.provider} · filtr treści: ${CFG.safe_content_filter ? 'włączony' : 'wyłączony'} · rozliczenie: ${CFG.billing_mode}`;
  await loadChars();
  setInterval(refresh, 3000);
})();
})();
