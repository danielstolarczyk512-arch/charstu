/* Widok "Film": lista filmow, planowanie AI, edycja scen i ujec, produkcja, montaz. */
(function () {
const $ = (i) => document.getElementById(i);
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
async function api(path, opts) {
  const r = await fetch(path, opts);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail || ('HTTP ' + r.status));
  return j;
}
const J = { 'Content-Type': 'application/json' };
const post = (p, b) => api(p, { method: 'POST', headers: J, body: JSON.stringify(b || {}) });
const patch = (p, b) => api(p, { method: 'PATCH', headers: J, body: JSON.stringify(b || {}) });
const del = (p) => api(p, { method: 'DELETE' });

function h(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === 'class') e.className = v;
    else if (k === 'text') e.textContent = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined && v !== false) e.setAttribute(k, v === true ? '' : v);
  }
  kids.flat().forEach((c) => { if (c !== null && c !== undefined && c !== false) e.append(c.nodeType ? c : document.createTextNode(c)); });
  return e;
}

let FID = null, TREE = null, lastSig = '', OUT = [], OUT_CID = null;
const STATUS = { draft: 'szkic', producing: 'produkcja…', paused: 'wstrzymany', ready: 'gotowy do montażu', needs_attention: 'wymaga uwagi' };
const msg = (t, bad) => { const m = $('fmMsg'); if (m) { m.textContent = t; m.style.color = bad ? 'var(--bad)' : ''; } };

/* ---------- nawigacja ---------- */
function show(view) {
  const film = view === 'film';
  const duet = view === 'duet';
  $('filmView').hidden = !film; $('studioView').hidden = film || duet; $('duetView').hidden = !duet;
  $('navFilm').classList.toggle('on', film); $('navStudio').classList.toggle('on', !film && !duet);
  $('navDuet').classList.toggle('on', duet);
  if (film) { loadChars(); loadList(); }
  if (duet && window.Duet) window.Duet.open();
}
window.showView = show;
$('navStudio').onclick = () => show('studio');
$('navFilm').onclick = () => show('film');
$('navDuet').onclick = () => show('duet');

async function loadChars() {
  const cs = await api('/api/characters');
  const sel = $('fmChar'); sel.innerHTML = '';
  cs.forEach((c) => sel.add(new Option(c.name + (c.archetype ? ' · ' + c.archetype : ''), c.id)));
}

/* ---------- lista filmow ---------- */
async function loadList() {
  const fs = await api('/api/films');
  const box = $('fmList'); box.innerHTML = '';
  if (!fs.length) box.append(h('div', { class: 'muted', text: 'Brak filmów.' }));
  fs.forEach((f) => {
    const p = f.progress;
    box.append(h('div', { class: 'char' + (f.id === FID ? ' on' : ''), onclick: () => open(f.id) },
      h('div', { text: f.title }),
      h('div', { class: 'muted', text: `${STATUS[f.status] || f.status} · klipy ${p.clips}/${p.shots} · ${f.fmt}` })));
  });
}
$('fmNew').addEventListener('submit', async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  try {
    const t = await post('/api/films', { title: f.get('title'), character_id: +f.get('character_id'), fmt: f.get('fmt') });
    e.target.reset(); $('fmNewBox').open = false; FID = t.film.id; await loadList(); render(t);
  } catch (err) { alert(err.message); }
});

async function open(id) { FID = id; lastSig = ''; await refresh(true); loadList(); }

/* ---------- odswiezanie ---------- */
async function refresh(force) {
  if (!FID) return;
  const t = await api(`/api/films/${FID}`);
  if (OUT_CID !== t.film.character_id) {   // szafa bohatera: podpowiedzi w polu stroju ujecia
    OUT = await api(`/api/characters/${t.film.character_id}/outfits`).catch(() => []); OUT_CID = t.film.character_id;
  }
  const sig = JSON.stringify(t);
  if (!force && sig === lastSig) return;
  const ae = document.activeElement;
  if (!force && ae && $('fmMain').contains(ae) && /INPUT|TEXTAREA|SELECT/.test(ae.tagName)) return; // nie przeszkadzamy w pisaniu
  lastSig = sig; render(t);
}
setInterval(() => { if (!$('filmView').hidden) { refresh(false).catch(() => {}); } }, 3000);

/* ---------- renderowanie ---------- */
function field(label, input) { return h('label', { class: 'fm-f' }, h('span', { class: 'muted', text: label }), input); }
function num(v, min, max, step, onchange, w) {
  const i = h('input', { type: 'number', min, max, step, value: v, style: `width:${w || 64}px` });
  i.addEventListener('change', () => onchange(+i.value)); return i;
}
function txt(v, onchange, ph, tag) {
  const i = h(tag || 'input', { placeholder: ph || '' }); i.value = v || '';
  i.addEventListener('change', () => onchange(i.value)); return i;
}
async function act(fn) { try { const t = await fn(); if (t && t.film) { lastSig = JSON.stringify(t); render(t); } loadList(); } catch (err) { msg(err.message, true); } }

function shotCard(sc, s, i, n) {
  const st = s.state;
  const thumb = st.image ? h('img', { src: '/files/' + st.image.path, class: 'fm-img' }) : h('div', { class: 'fm-ph', text: 'brak obrazu' });
  const cands = st.candidates.length > 1 || (st.candidates.length && !st.image)
    ? h('div', { class: 'fm-cands' }, st.candidates.map((c) => h('img', { src: '/files/' + c.path, class: c.id === s.image_artifact_id ? 'sel' : '',
        title: c.face_score != null ? 'twarz ' + c.face_score.toFixed(2) : 'wybierz', onclick: () => act(() => post(`/api/film-shots/${s.id}/pick`, { artifact_id: c.id })) }))) : null;
  const clip = st.clip ? h('video', { src: '/files/' + st.clip.path, controls: true, loop: true, muted: true, preload: 'none', class: 'fm-vid' }) : null;
  const chipCls = { 'klip gotowy': 'y', 'błąd': 'n' }[st.label] || '';
  const P = (body) => act(() => patch(`/api/film-shots/${s.id}`, body));
  return h('div', { class: 'fm-shot' },
    h('div', {}, thumb, h('span', { class: 'chip ' + chipCls, text: st.label }), cands, clip),
    h('div', {},
      h('div', { class: 'fm-row' }, txt(s.title, (v) => P({ title: v }), 'Tytuł'),
        field('czas (s)', num(s.duration, 2, 20, 1, (v) => P({ duration: v }))),
        h('label', { class: 'muted' }, h('input', { type: 'checkbox', checked: !!s.link_next, onchange: (e) => P({ link_next: e.target.checked }) }),
          ' płynnie w następne', ),
      ),
      txt(s.action, (v) => P({ action: v }), 'Co się dzieje (angielski)', 'textarea'),
      h('div', { class: 'fm-row' },
        field('kąt', num(s.az, -180, 180, 5, (v) => P({ az: v }))), field('wys.', num(s.el, -60, 85, 5, (v) => P({ el: v }))),
        field('dyst.', num(s.dist, 1.2, 8, 0.1, (v) => P({ dist: v }))), field('fov', num(s.fov, 20, 80, 1, (v) => P({ fov: v })))),
      h('div', { class: 'fm-row' }, txt(s.dialogue, (v) => P({ dialogue: v }), 'Kwestia lektora (angielski)'),
        (() => { const o = txt(s.outfit, (v) => P({ outfit: v }), 'Strój (puste = kanon; podpowiedzi z szafy)'); o.setAttribute('list', 'fmOutfits'); return o; })()),
      s.note ? h('div', { class: 'muted', style: 'color:var(--warn)', text: s.note }) : null,
      h('div', { class: 'fm-row' },
        h('button', { class: 'alt', onclick: () => act(() => post(`/api/film-shots/${s.id}/generate`, { role: 'image', count: 1 })) }, 'Obraz'),
        h('button', { class: 'alt', onclick: () => act(() => post(`/api/film-shots/${s.id}/generate`, { role: 'clip' })) }, 'Klip'),
        s.dialogue ? h('button', { class: 'alt', onclick: () => act(() => post(`/api/film-shots/${s.id}/generate`, { role: 'speech' })) }, 'Kwestia') : null,
        h('button', { class: 'alt', title: 'Wyczyść wybrany obraz, klip i kwestię (np. po zmianie opisu)', onclick: () => act(() => post(`/api/film-shots/${s.id}/reset`, { what: 'all' })) }, 'Reset'),
        i > 0 ? h('button', { class: 'alt', onclick: () => act(() => post(`/api/film-shots/${s.id}/move`, { scene_id: sc.id, idx: i - 1 })) }, '↑') : null,
        i < n - 1 ? h('button', { class: 'alt', onclick: () => act(() => post(`/api/film-shots/${s.id}/move`, { scene_id: sc.id, idx: i + 1 })) }, '↓') : null,
        h('button', { class: 'alt', onclick: () => { if (confirm('Usunąć ujęcie?')) act(() => del(`/api/film-shots/${s.id}`)); } }, 'Usuń'))));
}

function sceneCard(sc) {
  const PS = (body) => act(() => patch(`/api/scenes/${sc.id}`, body));
  return h('div', { class: 'fm-scene' },
    h('div', { class: 'fm-row' }, h('strong', { text: `Scena ${sc.idx + 1}` }), txt(sc.title, (v) => PS({ title: v }), 'Tytuł sceny'),
      h('button', { class: 'alt', onclick: () => { if (confirm('Usunąć scenę wraz z ujęciami?')) act(() => del(`/api/scenes/${sc.id}`)); } }, 'Usuń scenę')),
    txt(sc.summary, (v) => PS({ summary: v }), 'Co się dzieje (po polsku)'),
    h('div', { class: 'fm-row' }, txt(sc.location, (v) => PS({ location: v }), 'Miejsce (angielski, stałe w scenie)'),
      txt(sc.lighting, (v) => PS({ lighting: v }), 'Światło (angielski, stałe w scenie)')),
    sc.shots.map((s, i) => shotCard(sc, s, i, sc.shots.length)),
    h('button', { class: 'alt', onclick: () => act(() => post(`/api/scenes/${sc.id}/shots`, { title: 'Nowe ujęcie', action: '' })) }, '+ ujęcie'));
}

function render(t) {
  TREE = t; const f = t.film, p = t.progress, e = t.estimate || {}, sp = t.spent || {};
  const root = $('fmMain'); root.innerHTML = '';
  const PF = (body) => act(() => patch(`/api/films/${f.id}`, body));
  const pct = p.shots ? Math.round(100 * p.clips / p.shots) : 0;
  const planning = (f.plan_state || '').startsWith('planning');
  const asm = f.assemble_state || '';
  root.append(
    h('div', { class: 'fm-row' }, h('h2', { text: 'Film' }), h('span', { class: 'chip ' + (f.status === 'ready' ? 'y' : f.status === 'needs_attention' ? 'n' : ''), text: STATUS[f.status] || f.status }),
      h('span', { id: 'fmMsg', class: 'muted' })),
    h('div', { class: 'fm-row' }, txt(f.title, (v) => PF({ title: v }), 'Tytuł'), txt(f.logline, (v) => PF({ logline: v }), 'Logline (jedno zdanie)')),
    txt(f.synopsis, (v) => PF({ synopsis: v }), 'Streszczenie fabuły (po polsku)', 'textarea'),
    h('div', { class: 'box', id: 'fmModels' },
      h('div', { class: 'muted', text: 'Modele filmu (puste = domyślne z .env). Model poza planem zużywa Premium Spark i wymaga zgody.' }),
      h('div', { class: 'fm-row' }, field('model obrazu (bez kanonu)', h('select', { id: 'fmMGen' })), field('model edycji (z kanonem)', h('select', { id: 'fmMEdit' }))),
      h('label', { class: 'muted', title: 'Zgoda na zużycie Premium Spark przy modelach spoza planu Unlimited' },
        h('input', { type: 'checkbox', checked: !!f.allow_spark, onchange: (ev) => PF({ allow_spark: ev.target.checked }) }), ' zgoda na zużycie Premium Spark (modele poza planem)')),
    h('div', { class: 'fm-row' }, txt(f.music_prompt, (v) => PF({ music_prompt: v }), 'Podkład muzyczny (angielski: nastrój, instrumenty, BPM, tonacja)'),
      field('budżet (Spark)', num(f.budget_spark, 0, 100000, 10, (v) => PF({ budget_spark: v }), 80)),
      h('label', { class: 'muted', title: 'Producent sam wybiera najlepszy obraz spośród kandydatów' },
        h('input', { type: 'checkbox', checked: !!f.auto_pick, onchange: (ev) => PF({ auto_pick: ev.target.checked }) }), ' auto-wybór obrazu')),

    h('div', { class: 'box' },
      h('div', { class: 'muted', text: 'Reżyser AI: opisz pomysł po polsku, a program zaplanuje sceny, ujęcia, kamerę, kwestie i podkład.' }),
      h('textarea', { id: 'fmIdea', rows: 2, placeholder: 'np. Łowczyni żegna się z doliną i rusza w drogę o świcie…' }),
      h('div', { class: 'fm-row' },
        field('sceny', num(4, 1, 8, 1, () => {}, 56)), field('ujęć/scenę', num(3, 1, 6, 1, () => {}, 56)),
        h('label', { class: 'muted' }, h('input', { type: 'checkbox', id: 'fmReplace' }), ' zastąp istniejące sceny'),
        h('button', { disabled: planning, onclick: () => {
          const ins = root.querySelectorAll('.box input[type=number]');
          act(() => post(`/api/films/${f.id}/plan`, { idea: $('fmIdea').value, scenes: +ins[0].value, shots_per_scene: +ins[1].value, replace: $('fmReplace').checked }));
        } }, planning ? 'Planuję…' : 'Zaplanuj (AI)')),
      f.plan_state ? h('div', { class: 'muted', style: f.plan_state.startsWith('error') ? 'color:var(--bad)' : '', text: 'Plan: ' + f.plan_state }) : null),

    h('div', { class: 'box' },
      h('div', { class: 'fm-row' },
        h('div', { class: 'fm-bar' }, h('div', { style: `width:${pct}%` })),
        h('span', { class: 'muted', text: `ujęcia ${p.shots} · obrazy ${p.images} · klipy ${p.clips}/${p.shots} · kwestie ${p.speech_done}/${p.speech_needed} · podkład ${p.bed ? 'tak' : p.bed_needed ? 'brak' : '—'}${p.failed ? ' · błędy ' + p.failed : ''} · ok. ${t.est_seconds} s` })),
      h('div', { class: 'muted', text: `Do zrobienia: ${e.jobs ?? 0} zadań (≈ ${e.est_spark ?? 0} Spark wartości z planu). Zużyto w tym uruchomieniu: ${sp.spark ?? 0} z budżetu ${f.budget_spark} (${sp.source || '—'}).` }),
      f.note ? h('div', { class: 'muted', style: 'color:var(--warn)', text: f.note }) : null,
      h('div', { class: 'fm-row' },
        h('button', { disabled: !p.shots, onclick: () => {
          if (!confirm(`Zlecić produkcję? ${e.jobs} zadań, szacunkowo ${e.est_spark} Spark wartości z planu Unlimited (budżet ${f.budget_spark}). ` +
                       'Program wstrzyma się po przekroczeniu budżetu lub przy limicie Sogni i wznowi go, gdy będzie to możliwe.')) return;
          act(() => post(`/api/films/${f.id}/produce`));
        } }, f.status === 'producing' ? 'Produkuję…' : 'Produkuj wszystko'),
        h('button', { class: 'alt', onclick: () => act(() => post(`/api/films/${f.id}/pause`)) }, 'Pauza'),
        h('button', { class: 'alt', onclick: () => { if (confirm('Usunąć cały film? (obrazy i klipy zostają w galerii Studia)')) { FID = null; del(`/api/films/${f.id}`).then(() => { $('fmMain').innerHTML = '<div class="muted">Film usunięty.</div>'; loadList(); }); } } }, 'Usuń film'))),

    h('div', { class: 'box' },
      h('div', { class: 'muted', text: 'Montaż: klipy w kolejności planu, głośność wyrównana do -16 LUFS, podkład ściszany pod lektorem, napisy z kwestii.' }),
      h('div', { class: 'fm-row' },
        field('przenikanie (s)', num(0.4, 0, 2, 0.1, () => {}, 60)),
        h('label', { class: 'fm-f' }, h('span', { class: 'muted', text: 'dźwięk klipów' }), h('select', {}, h('option', { value: 'normalize', text: 'normalizuj' }), h('option', { value: 'keep', text: 'zachowaj' }), h('option', { value: 'mute', text: 'wycisz' }))),
        h('label', { class: 'fm-f' }, h('span', { class: 'muted', text: 'napisy' }), h('select', {}, h('option', { value: 'sidecar', text: 'plik SRT' }), h('option', { value: 'burn', text: 'wypalone w obrazie' }), h('option', { value: 'none', text: 'brak' }))),
        h('label', { class: 'muted' }, h('input', { type: 'checkbox', id: 'fmPartial' }), ' montaż częściowy'),
        h('button', { disabled: asm === 'assembling', onclick: (ev) => {
          const box = ev.target.closest('.box'); const nums = box.querySelectorAll('input[type=number]'); const sels = box.querySelectorAll('select');
          act(() => post(`/api/films/${f.id}/assemble`, { fade: +nums[0].value, audio_mode: sels[0].value, subtitles: sels[1].value, allow_partial: $('fmPartial').checked }));
        } }, asm === 'assembling' ? 'Montuję…' : 'Zmontuj film')),
      asm.startsWith('error') ? h('div', { style: 'color:var(--bad)', text: asm }) : null,
      asm.startsWith('done') ? h('div', { class: 'muted', text: summary(asm) }) : null,
      f.final ? h('div', {}, h('video', { src: '/files/' + f.final.path, controls: true, class: 'fm-final' }),
        f.srt_path ? h('div', {}, h('a', { href: '/files/' + f.srt_path, target: '_blank', text: 'Napisy (SRT)' })) : null) : null),

    h('datalist', { id: 'fmOutfits' }, OUT.map((o) => h('option', { value: o.description, label: o.name }))),
    ...t.scenes.map(sceneCard),
    h('button', { class: 'alt', onclick: () => act(() => post(`/api/films/${f.id}/scenes`, { title: 'Nowa scena' })) }, '+ scena'));
  const mp = (id, kind, cur) => Models.picker($(id), kind, { transient: true, noStore: true, initial: cur || undefined,
    onChange: (pk) => { PF({ [kind === 'edit' ? 'edit_model' : 'image_model']: pk.get() }); } }).catch(() => {});
  mp('fmMGen', 'image', f.image_model); mp('fmMEdit', 'edit', f.edit_model);
}

function summary(asm) {
  try {
    const r = JSON.parse(asm.slice(6));
    return `Gotowe: ${r.clips} klipów, ${r.duration.toFixed(1)} s, ${r.mixed_lufs != null ? r.mixed_lufs.toFixed(1) + ' LUFS, ' : ''}napisy: ${r.subtitles}` +
      (r.missing && r.missing.length ? `, pominięte: ${r.missing.length}` : '');
  } catch (e) { return asm.slice(0, 120); }
}
})();
