/* Lista wyboru modeli (Studio, Film, Duet). Zasilana WYLACZNIE z API (/api/models) - w JS nie ma zaszytych identyfikatorow.
   Kazda pozycja: nazwa, limit referencji (edycja), znacznik pokrycia planem ("w planie" / "Premium Spark"), "niesprawdzony",
   "nieznany, sprawdź". Własny identyfikator: ostatnia pozycja "Własny identyfikator…" (okno z polem, zapamiętany w przeglądarce). */
(function () {
const DEFAULT_KEY = { image: 'generate', edit: 'edit', video: 'video', flf: 'flf', llm: 'llm' };
const ID_RE = /^[A-Za-z0-9._-]{1,80}$/;
const pickers = [];
let DATA = null, BAL = undefined;

async function api(path, opts) {
  const r = await fetch(path, opts);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail || ('HTTP ' + r.status));
  return j;
}
const store = {
  get: (k, d) => { try { return localStorage.getItem(k) || d; } catch (e) { return d; } },
  set: (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* brak localStorage */ } },
};

function label(e) {
  const bits = [e.label];
  if (e.kind === 'edit' && e.max_refs) bits.push(`${e.max_refs} ref.`);
  bits.push(e.covered ? 'w planie' : 'Premium Spark');
  if (!e.tested) bits.push('niesprawdzony');
  if (!e.known) bits.push('nieznany, sprawdź');
  if (e.available === false) bits.push('niedostępny w katalogu');
  return bits.join(' · ');
}

async function load(force) {
  if (!DATA || force) DATA = await api('/api/models');
  return DATA;
}

function customList(kind) {
  try { return JSON.parse(store.get('mcustom_' + kind, '[]')).filter((x) => ID_RE.test(x)); } catch (e) { return []; }
}

function entryOf(kind, id) {
  return (DATA[kind] || []).find((e) => e.id === id)
    || { id, label: id, kind, covered: false, tested: false, known: false, available: true, note: 'Własny identyfikator.' };
}

async function balance() {
  if (BAL === undefined) { try { BAL = (await api('/api/account')).premium_spark; } catch (e) { BAL = null; } }
  return BAL;
}

/* Tworzy liste w <select>; zwraca {get(), spark(), set(id)}. opts: key (localStorage), onChange. */
async function picker(sel, kind, opts) {
  opts = opts || {};
  await load();
  const key = opts.key || ('model_' + kind);
  const note = document.createElement('div'); note.className = 'muted mpick-note'; note.hidden = true;
  const ok = document.createElement('input'); ok.type = 'checkbox';
  const okLab = document.createElement('label'); okLab.className = 'check'; okLab.hidden = true;
  okLab.append(ok, document.createTextNode(' Potwierdzam zużycie Premium Spark dla tego modelu'));
  sel.after(note); note.after(okLab);

  const api_ = {
    get: () => sel.value, spark: () => ok.checked && !entryOf(kind, sel.value).covered, set,
    entry: () => entryOf(kind, sel.value), fill,
  };

  function fill() {
    const cur = sel.value || opts.initial || (opts.noStore ? '' : store.get(key, '')) || (DATA.defaults || {})[DEFAULT_KEY[kind]] || '';
    sel.innerHTML = '';
    let grp = null, grpName = null;
    (DATA[kind] || []).forEach((e) => {
      const g = `${e.category || 'Inne'}${e.covered ? '' : ' (poza planem)'}`;
      if (g !== grpName) { grp = document.createElement('optgroup'); grp.label = g; sel.append(grp); grpName = g; }
      const o = new Option(label(e), e.id); o.title = e.note || ''; grp.append(o);
    });
    const mine = customList(kind).filter((id) => !(DATA[kind] || []).some((e) => e.id === id));
    if (mine.length) {
      const g = document.createElement('optgroup'); g.label = 'Własne (nieznane, sprawdź)'; sel.append(g);
      mine.forEach((id) => g.append(new Option(`${id} · Premium Spark · nieznany, sprawdź`, id)));
    }
    sel.append(new Option('Własny identyfikator…', '__custom__'));
    if (cur && ![...sel.options].some((o) => o.value === cur) && ID_RE.test(cur)) {
      const g = document.createElement('optgroup'); g.label = 'Własne (nieznane, sprawdź)'; sel.insertBefore(g, sel.lastChild);
      g.append(new Option(`${cur} · Premium Spark · nieznany, sprawdź`, cur));
    }
    sel.value = [...sel.options].some((o) => o.value === cur) ? cur : (sel.options[0] ? sel.options[0].value : '');
    show();
  }

  async function show() {
    const e = entryOf(kind, sel.value);
    note.hidden = !e.note && e.covered; okLab.hidden = e.covered;
    let t = e.note || '';
    if (!e.covered) {
      const b = await balance();
      t = `${DATA.spark_warning || 'Ten model jest poza planem Unlimited. Zadanie zużyje Premium Spark.'} ` +
        (b === null || b === undefined ? 'Saldo Premium Spark nieznane.' : (b > 0 ? `Saldo Premium Spark: ${b}.` : 'Saldo Premium Spark: 0 — zadanie nie ruszy.')) +
        (t ? ' ' + t : '');
      note.style.color = 'var(--warn)'; note.hidden = false;
    } else { note.style.color = ''; ok.checked = false; }
    note.textContent = t;
  }

  function set(id) { sel.value = id; if (sel.value !== id) { fill(); sel.value = id; } show(); }

  sel.addEventListener('change', () => {
    if (sel.value === '__custom__') {
      const id = (window.prompt('Własny identyfikator modelu (litery, cyfry, . _ -). Nieznany model idzie jako Premium Spark, więc sprawdź go w katalogu Sogni.') || '').trim();
      if (!ID_RE.test(id)) { sel.value = (opts.noStore ? opts.initial : store.get(key, '')) || ''; if (sel.value === '__custom__' || !sel.value) fill(); return; }
      const list = customList(kind); if (!list.includes(id)) { list.push(id); store.set('mcustom_' + kind, JSON.stringify(list)); }
      fill(); sel.value = id;
    }
    if (!opts.noStore) store.set(key, sel.value);
    ok.checked = false; show();
    if (opts.onChange) opts.onChange(api_);
  });
  fill();
  if (!opts.transient) pickers.push(api_);
  return api_;
}

async function refreshAll(btn, msgEl) {
  const old = btn ? btn.textContent : '';
  if (btn) { btn.disabled = true; btn.textContent = 'Odświeżam…'; }
  try {
    const r = await api('/api/models/refresh', { method: 'POST' });
    DATA = r; BAL = undefined;
    pickers.forEach((p) => p.fill());
    if (msgEl) msgEl.textContent = r.refresh.ok ? `Katalog odświeżony (${r.refresh.count} pozycji).` : `Katalog z API niedostępny (${r.refresh.error}); używam ${r.source}.`;
  } catch (e) { if (msgEl) msgEl.textContent = e.message; }
  if (btn) { btn.disabled = false; btn.textContent = old; }
}

window.Models = { load, picker, refreshAll, label };
})();
