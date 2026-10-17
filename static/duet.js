/* Widok "Duet": dwie osoby w jednym kadrze (odpowiednik film.js). Wymaga static/models.js i static/film.js (nawigacja).
   NIE TESTOWANY prawdziwym renderem do czasu weryfikacji opisanej w DUET_RAPORT.md; interfejs sprawdzony w przegladarce na mocku. */
(function () {
const $ = (i) => document.getElementById(i);
const J = { 'Content-Type': 'application/json' };
async function api(path, opts) {
  const r = await fetch(path, opts);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof j.detail === 'string' ? j.detail : ('HTTP ' + r.status));
  return j;
}
const post = (p, b) => api(p, { method: 'POST', headers: J, body: JSON.stringify(b || {}) });
const store = {
  get: (k, d) => { try { return localStorage.getItem(k) || d; } catch (e) { return d; } },
  set: (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* brak localStorage */ } },
};
const say = (t, bad) => { $('duMsg').textContent = t; $('duMsg').style.color = bad ? 'var(--bad)' : ''; };
const el = (tag, attrs, ...kids) => {
  const e = document.createElement(tag);
  Object.entries(attrs || {}).forEach(([k, v]) => { if (k === 'class') e.className = v; else if (k === 'text') e.textContent = v; else if (k.startsWith('on')) e[k] = v; else e.setAttribute(k, v); });
  kids.flat().forEach((c) => { if (c) e.append(c.nodeType ? c : document.createTextNode(c)); });
  return e;
};

const S = { a: null, b: null, lib: null, fmt: '16:9', shot: null, sel: null, flfStart: null, flfEnd: null, clips: [], opened: false };
const P = {};            // listy modeli: edit, vid
let LIB = [], CFG = {}, previewTimer, lastSig = '';

/* ---------- postacie ---------- */
async function loadChars() {
  const cs = await api('/api/characters');
  // bez zapamietanego wyboru: A = najstarszy bohater, B = najstarszy partner (a gdy go brak - inna postac)
  const asc = [...cs].sort((x, y) => x.id - y.id);
  const fill = (sel, cur, skip, pref) => {
    sel.innerHTML = '';
    asc.filter((c) => c.id !== skip).forEach((c) => sel.add(new Option(`${c.name}${c.kind === 'partner' ? ' (partner)' : ''}${c.archetype ? ' · ' + c.archetype : ''}`, c.id)));
    const want = [...sel.options].some((o) => +o.value === cur) ? cur : (asc.find((c) => c.id !== skip && pref(c)) || {}).id;
    if (want) sel.value = want;
  };
  fill($('duA'), +store.get('duA', 0) || S.a, null, (c) => c.kind !== 'partner');
  S.a = +$('duA').value || null;
  fill($('duB'), +store.get('duB', 0) || S.b, S.a, (c) => c.kind === 'partner');
  S.b = +$('duB').value || null;
}
async function coverage() {
  const chip = (cov) => Object.entries(cov).filter(([k]) => ['face', 'body'].includes(k))
    .map(([k, v]) => `<span class="chip ${v ? 'y' : 'n'}">${k === 'face' ? 'twarz' : 'sylwetka'}</span>`).join('');
  $('duACov').innerHTML = S.a ? 'Kanon: ' + chip(await api(`/api/coverage?character_id=${S.a}`)) : '';
  $('duBCov').innerHTML = S.b ? 'Kanon: ' + chip(await api(`/api/coverage?character_id=${S.b}`)) : '';
}
async function createChar(form, kind) {
  const f = new FormData(form);
  const c = await post('/api/characters', { name: f.get('name'), archetype: f.get('archetype') || '', traits: f.get('traits') || '',
    outfit: f.get('outfit') || '', style: f.get('style') || '', adult_fictional: !!f.get('adult_fictional'), kind });
  form.reset(); store.set(kind === 'lead' ? 'duA' : 'duB', c.id); await loadChars(); await onPick(); say(`Utworzono postać: ${c.name}.`);
}
$('duNewA').addEventListener('submit', (e) => { e.preventDefault(); createChar(e.target, 'lead').catch((x) => say(x.message, true)); });
$('duNewB').addEventListener('submit', (e) => { e.preventDefault(); createChar(e.target, 'partner').catch((x) => say(x.message, true)); });
async function onPick() {
  S.a = +$('duA').value || null; S.b = +$('duB').value || null;
  store.set('duA', S.a || ''); store.set('duB', S.b || ''); S.shot = null; S.sel = S.flfStart = S.flfEnd = null;
  await loadChars(); await coverage(); preview(); refresh(true);
}
$('duA').addEventListener('change', onPick);
$('duB').addEventListener('change', () => { S.b = +$('duB').value || null; store.set('duB', S.b || ''); S.shot = null; coverage(); preview(); refresh(true); });

/* kanon partnera */
$('duCanonUp').addEventListener('submit', async (e) => {
  e.preventDefault();
  if (!S.b) { say('Najpierw wybierz partnera B.', true); return; }
  try {
    const f = new FormData(e.target);
    await api(`/api/characters/${S.b}/canon`, { method: 'POST', body: f });
    e.target.reset(); await coverage(); preview(); say('Dodano do kanonu B.');
  } catch (x) { say(x.message, true); }
});
$('duCanonGen').onclick = async () => {
  if (!S.b) { say('Najpierw wybierz partnera B.', true); return; }
  try {
    const r = await post('/api/duet/partner-canon', { partner_id: S.b, image_model: null, edit_model: null, fmt: S.fmt,
      allow_spark: false });
    say(r.items.length ? `Zlecono ${r.items.length} obrazy kanonu B (zatwierdź je poniżej).` : 'Kanon B ma już twarz i sylwetkę.');
    refresh(true);
  } catch (x) { say(x.message, true); }
};
async function canonCands() {
  const box = $('duCanonCands'); box.innerHTML = '';
  if (!S.b) return;
  const arts = (await api(`/api/artifacts?character_id=${S.b}`)).filter((a) => (a.label || '').startsWith('arkusz:') && a.kind === 'image');
  arts.slice(0, 6).forEach((a) => {
    const role = (a.label.split(':')[1] || 'face');
    box.append(el('div', {}, el('img', { src: '/files/' + a.path }),
      el('button', { class: 'alt', text: role === 'body' ? 'jako sylwetka B' : 'jako twarz B', onclick: async () => {
        const f = new FormData(); f.append('role', role === 'body' ? 'body' : 'face');
        await api(`/api/artifacts/${a.id}/approve`, { method: 'POST', body: f }); coverage(); say('Zatwierdzono do kanonu B.');
      } })));
  });
}

/* ---------- biblioteka interakcji ---------- */
async function loadLib() {
  LIB = await api('/api/duet/interactions');
  const box = $('duLib'); box.innerHTML = '';
  box.append(el('button', { class: 'pill' + (S.lib ? '' : ' on'), text: 'bez pozycji', onclick: () => pickLib(null) }));
  LIB.forEach((it) => box.append(el('button', { class: 'pill' + (S.lib === it.slug ? ' on' : ''), title: it.description,
    onclick: () => pickLib(it.slug) }, it.name, it.image_url ? el('span', { class: 'dot', title: 'ma obraz referencyjny' }) : null,
    it.builtin ? null : el('span', { class: 'muted', text: ' ·własna' }))));
}
function pickLib(slug) {
  S.lib = slug; store.set('duLib', slug || '');
  const it = LIB.find((x) => x.slug === slug);
  if (it && (!$('duInter').value.trim() || LIB.some((x) => x.description === $('duInter').value.trim()))) $('duInter').value = it.description;
  S.shot = null; loadLib(); preview();
}
$('duLibForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  try {
    await api('/api/duet/interactions', { method: 'POST', body: new FormData(e.target) });
    e.target.reset(); await loadLib(); say('Dodano pozycję do biblioteki.');
  } catch (x) { say(x.message, true); }
});

/* ---------- ujecie ---------- */
const body = () => ({ a_id: S.a, b_id: S.b, az: +$('duAz').value, el: +$('duEl').value, dist: +$('duDi').value / 10, fov: 35, fmt: S.fmt,
  action: $('duAction').value, outfit: $('duOutA').value, outfit_b: $('duOutB').value, interaction: $('duInter').value });
const sparkOk = (p) => p && (p.entry().covered || p.spark());
function labels() { $('duAzv').textContent = $('duAz').value + '°'; $('duElv').textContent = $('duEl').value + '°'; $('duDiv').textContent = ($('duDi').value / 10).toFixed(1) + ' m'; }
function changed() { S.shot = null; labels(); ['duAz', 'duEl', 'duDi', 'duInter', 'duAction', 'duOutA', 'duOutB'].forEach((i) => store.set(i, $(i).value)); preview(); }
['duAz', 'duEl', 'duDi', 'duInter', 'duAction', 'duOutA', 'duOutB'].forEach((i) => $(i).addEventListener('input', changed));
document.querySelectorAll('[data-dufmt]').forEach((b) => b.onclick = () => {
  document.querySelectorAll('[data-dufmt]').forEach((x) => x.classList.remove('on')); b.classList.add('on');
  S.fmt = b.dataset.dufmt; store.set('duFmt', S.fmt); changed();
});
function preview() {
  clearTimeout(previewTimer);
  previewTimer = setTimeout(async () => {
    if (!S.a || !S.b) { $('duPrompt').textContent = 'Wybierz postać A i partnera B.'; $('duRefs').textContent = ''; return; }
    try {
      const p = await post('/api/duet/plan', { ...body(), edit_model: P.edit ? P.edit.get() : null, interaction_id: S.lib });
      $('duPrompt').textContent = p.prompt;
      $('duRefs').textContent = `1. twarz A, 2. twarz B${p.pose_used ? ', 3. obraz interakcji (tylko ułożenie ciał)' : ''} · limit modelu: ${p.max_refs}`;
      $('duWarn').style.color = p.warnings.length ? 'var(--warn)' : '';
      $('duWarn').textContent = p.warnings.join(' ');
    } catch (e) { $('duWarn').style.color = 'var(--bad)'; $('duWarn').textContent = e.message; $('duPrompt').textContent = ''; $('duRefs').textContent = ''; }
  }, 300);
}
$('duGen').onclick = async () => {
  try {
    if (!S.a || !S.b) throw new Error('Wybierz postać A i partnera B.');
    if (!S.shot) S.shot = (await post('/api/duet/shots', body())).id;
    const r = await post(`/api/duet/shots/${S.shot}/generate`, { count: +$('duCount').value, edit_model: P.edit.get() || null,
      interaction_id: S.lib, allow_spark: sparkOk(P.edit) });
    say(`Zlecono ${r.jobs.length} warianty (${r.model}, referencje: ${r.refs.length + (r.pose ? 1 : 0)}).` + (r.warnings.length ? ' ' + r.warnings.join(' ') : ''));
    refresh(true);
  } catch (e) { say(e.message, true); }
};

/* ---------- wyniki ---------- */
async function refresh(force) {
  if (!S.a) return;
  const [jobs, arts] = await Promise.all([api(`/api/jobs?character_id=${S.a}`),
    S.b ? api(`/api/duet/artifacts?a=${S.a}&b=${S.b}`) : Promise.resolve([])]);
  const sig = JSON.stringify([jobs.map((j) => [j.id, j.status]), arts.map((a) => [a.id, a.face_score, a.face_score_b]), S.sel, S.flfStart, S.flfEnd, S.clips]);
  if (!force && sig === lastSig) return;
  lastSig = sig;
  $('duJobs').innerHTML = '';
  jobs.slice(0, 10).forEach((j) => $('duJobs').append(el('div', { class: 'job' }, `#${j.id} ${j.kind} `, el('span', { class: 's-' + j.status, text: j.status }),
    j.error ? el('div', { class: 'muted', text: j.error }) : null)));
  const g = $('duGallery'); g.innerHTML = '';
  arts.forEach((a) => {
    const d = el('div', {});
    if (a.kind === 'video') d.append(el('video', { src: '/files/' + a.path, controls: '', loop: '', muted: '' }));
    else if (a.kind === 'image') d.append(el('img', { src: '/files/' + a.path, style: 'cursor:pointer' + (S.sel === a.id ? ';outline:2px solid var(--acc)' : ''),
      onclick: () => { S.sel = a.id; lastSig = ''; refresh(true); } }));
    const fs = (v) => (v == null ? '—' : (+v).toFixed(2));
    d.append(el('div', { class: 'muted', style: 'padding:2px 4px', text: `#${a.id} · A ${fs(a.face_score)} / B ${fs(a.face_score_b)}${a.label ? ' · ' + a.label : ''}` }));
    const tools = el('div', { class: 'tools' });
    if (a.kind === 'image') {
      tools.append(el('button', { class: 'alt', text: S.flfStart === a.id ? 'start ✓' : 'start', onclick: () => { S.flfStart = a.id; S.shot = null; lastSig = ''; refresh(true); } }),
        el('button', { class: 'alt', text: S.flfEnd === a.id ? 'koniec ✓' : 'koniec', onclick: () => { S.flfEnd = a.id; lastSig = ''; refresh(true); } }),
        el('button', { class: 'alt', text: 'zmierz', onclick: async () => { try { await api(`/api/artifacts/${a.id}/measure`, { method: 'POST' }); refresh(true); } catch (x) { say(x.message, true); } } }));
    } else if (a.kind === 'video') {
      const cb = el('input', { type: 'checkbox' }); cb.checked = S.clips.includes(a.id);
      cb.onchange = () => { S.clips = cb.checked ? [...S.clips, a.id] : S.clips.filter((x) => x !== a.id); lastSig = ''; };
      tools.append(el('label', { class: 'muted' }, cb, ' sklej'));
    }
    d.append(tools); g.append(d);
  });
  canonCands().catch(() => {});
}
const shotOf = async (artId) => (await api(`/api/duet/artifacts?a=${S.a}&b=${S.b}`)).find((x) => x.id === artId);
$('duClip').onclick = async () => {
  try {
    if (!S.sel) throw new Error('Kliknij obraz pary w wynikach, z którego ma powstać klip.');
    const a = await shotOf(S.sel);
    const r = await post(`/api/duet/shots/${a.shot_id}/video`, { source_artifact_id: S.sel, video_model: P.vid.get() || null, allow_spark: sparkOk(P.vid) });
    say(`Zlecono klip (${r.jobs.length}).`); refresh(true);
  } catch (e) { say(e.message, true); }
};
$('duFlf').onclick = async () => {
  try {
    if (!S.flfStart || !S.flfEnd) throw new Error('Wybierz w wynikach obraz "start" i obraz "koniec" (te same proporcje).');
    const a = await shotOf(S.flfStart);
    const r = await post(`/api/duet/shots/${a.shot_id}/video`, { source_artifact_id: S.flfStart, end_artifact_id: S.flfEnd, allow_spark: false });
    say(`Zlecono klip start→koniec (${r.jobs.length}).`); refresh(true);
  } catch (e) { say(e.message, true); }
};
$('duStitch').onclick = async () => {
  try {
    if (S.clips.length < 2) throw new Error('Zaznacz co najmniej 2 klipy ("sklej").');
    const r = await post('/api/stitch', { artifact_ids: S.clips, fade: +$('duFade').value || 0, audio_mode: 'normalize' });
    say('Sklejono: ' + r.path); refresh(true);
  } catch (e) { say(e.message, true); }
};

/* ---------- start widoku ---------- */
async function open() {
  if (!S.opened) {
    S.opened = true;
    try { CFG = await api('/api/duet/config'); } catch (e) { CFG = {}; }
    ['duAz', 'duEl', 'duDi', 'duInter', 'duAction', 'duOutA', 'duOutB'].forEach((i) => { const v = store.get(i, ''); if (v !== '') $(i).value = v; });
    S.fmt = store.get('duFmt', '16:9');
    document.querySelectorAll('[data-dufmt]').forEach((x) => x.classList.toggle('on', x.dataset.dufmt === S.fmt));
    S.lib = store.get('duLib', '') || null;
    P.edit = await Models.picker($('duEdit'), 'edit', { key: 'duEdit', defaultId: CFG.partner_model, onChange: preview });
    P.vid = await Models.picker($('duVid'), 'video', { key: 'duVid' });
    $('duRefresh').onclick = () => Models.refreshAll($('duRefresh'), $('duCat'));
    labels();
  }
  await loadChars(); await coverage(); await loadLib(); preview(); refresh(true);
}
setInterval(() => { if (!$('duetView').hidden) refresh(false).catch(() => {}); }, 3000);
window.Duet = { open };
})();
