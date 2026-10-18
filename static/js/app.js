(() => {
  'use strict';
  const API = '/api';
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const store = {
    get(k, d) { try { const v = JSON.parse(localStorage.getItem(k)); return v ?? d; } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* ignore */ } }
  };

  // ---------- language ----------
  const META = window.LANG_META, DICT = window.I18N;
  const detectLang = () => { const n = (navigator.language || 'en').slice(0, 2).toLowerCase(); return META[n] ? n : 'en'; };
  let lang = store.get('hpf_lang', null); if (!META[lang]) lang = detectLang();
  const t = (k, v = {}) => String((DICT[lang] && DICT[lang][k]) ?? DICT.en[k] ?? k).replace(/\{(\w+)\}/g, (_, x) => v[x] ?? '');
  const tr = (txt, key) => (lang !== 'en' && txt === DICT.en[key] && DICT[lang][key]) ? DICT[lang][key] : txt;
  const loc = () => META[lang].locale;
  const fmtDate = d => { try { return new Date(d).toLocaleDateString(loc(), { year: 'numeric', month: 'short', day: 'numeric' }); } catch { return new Date(d).toDateString(); } };
  const fmtDT = d => { try { return new Date(d).toLocaleString(loc(), { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }); } catch { return new Date(d).toLocaleString(); } };
  const money = (minor, cur) => { try { return new Intl.NumberFormat(loc(), { style: 'currency', currency: cur, minimumFractionDigits: 0, maximumFractionDigits: 2 }).format(minor / 100); } catch { return cur + ' ' + (minor / 100); } };
  const fmtSize = n => n > 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB';

  async function api(path, { method = 'GET', body } = {}) {
    const opts = { method, headers: { 'X-Requested-With': 'fetch' }, credentials: 'same-origin' };
    if (body instanceof FormData) opts.body = body;
    else if (body !== undefined) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
    const r = await fetch(API + path, opts); let data = null; try { data = await r.json(); } catch { /* not json */ }
    if (!r.ok) throw new Error((data && data.error) || `Request failed (${r.status})`);
    return data;
  }
  function toast(msg, type = 'ok') { const x = document.createElement('div'); x.className = 'toast' + (type === 'err' ? ' err' : ''); x.textContent = msg; $('#toasts').appendChild(x); setTimeout(() => x.remove(), 3800); }
  const setMsg = (el, text, ok) => { el.textContent = text; el.className = 'msg ' + (ok ? 'ok' : 'err'); };
  const spinner = '<div class="skeleton" style="height:140px"></div>';

  // ---------- state ----------
  const state = { q: '', category: '', tag: '', sort: 'new', saved: false, alang: '', page: 1, pages: 1, loaded: false };
  let bookmarks = store.get('hpf_bookmarks', []), likes = store.get('hpf_likes', []), history_ = store.get('hpf_history', []);
  let me = null, site = {}, cats = [];

  // ---------- comfort ----------
  const cf = Object.assign({ theme: 'dark', size: 100, space: 'normal', motion: false, contrast: false }, store.get('hpf_comfort', {}));
  const reduced = () => cf.motion || matchMedia('(prefers-reduced-motion: reduce)').matches;
  function applyComfort() {
    const h = document.documentElement;
    h.setAttribute('data-theme', cf.theme); h.style.setProperty('--zoom', cf.size / 100); h.style.setProperty('--lh', cf.space === 'relaxed' ? 1.85 : 1.55);
    h.classList.toggle('reduce-motion', cf.motion); if (cf.contrast) h.setAttribute('data-contrast', 'high'); else h.removeAttribute('data-contrast');
    $$('#cf-theme button').forEach(b => b.classList.toggle('on', b.dataset.v === cf.theme));
    $$('#cf-size button').forEach(b => b.classList.toggle('on', +b.dataset.v === +cf.size));
    $$('#cf-space button').forEach(b => b.classList.toggle('on', b.dataset.v === cf.space));
    $('#cf-motion').checked = cf.motion; $('#cf-contrast').checked = cf.contrast; store.set('hpf_comfort', cf);
  }
  $('#comfort-btn').addEventListener('click', e => { e.stopPropagation(); const p = $('#comfort-panel'); p.classList.toggle('hidden'); e.currentTarget.setAttribute('aria-expanded', !p.classList.contains('hidden')); });
  $('#comfort-panel').addEventListener('click', e => {
    e.stopPropagation(); const b = e.target.closest('button'); if (!b) return;
    if (b.id === 'cf-reset') Object.assign(cf, { theme: 'dark', size: 100, space: 'normal', motion: false, contrast: false });
    else { const g = b.parentElement.id; if (g === 'cf-theme') cf.theme = b.dataset.v; if (g === 'cf-size') cf.size = +b.dataset.v; if (g === 'cf-space') cf.space = b.dataset.v; }
    applyComfort();
  });
  $('#cf-motion').addEventListener('change', e => { cf.motion = e.target.checked; applyComfort(); });
  $('#cf-contrast').addEventListener('change', e => { cf.contrast = e.target.checked; applyComfort(); });
  document.addEventListener('click', e => { if (!e.target.closest('.comfort-wrap')) $('#comfort-panel').classList.add('hidden'); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') $('#comfort-panel').classList.add('hidden'); });
  $('#menu-btn').addEventListener('click', () => $('#nav-links').classList.toggle('open'));

  // ---------- static text / language switch ----------
  function applyStatic() {
    const h = document.documentElement; h.lang = lang; h.dir = META[lang].dir;
    $$('[data-i18n]').forEach(el => { el.textContent = t(el.dataset.i18n); });
    $$('[data-i18n-ph]').forEach(el => { el.placeholder = t(el.dataset.i18nPh); });
    $$('[data-i18n-aria]').forEach(el => { el.setAttribute('aria-label', t(el.dataset.i18nAria)); el.title = t(el.dataset.i18nAria); });
    $('#lang-sel').value = lang;
    $('#lang-filter').innerHTML = `<option value="">${esc(t('lang_all'))}</option>` + Object.entries(META).map(([k, m]) => `<option value="${k}"${state.alang === k ? ' selected' : ''}>${esc(m.name)}</option>`).join('');
    const a = $('#announce'), txt = siteText('announcement'); a.textContent = txt; a.classList.toggle('hidden', !txt);
    updateAcctBtn();
  }
  const siteText = k => site[k + '_' + lang] || site[k] || '';
  function setLang(l) {
    lang = l; store.set('hpf_lang', l); applyStatic(); state.loaded = false; renderSlider(); loadMeta(); loadReco(); renderChips(); route();
  }
  $('#lang-sel').addEventListener('change', e => setLang(e.target.value));
  $('#lang-filter').addEventListener('change', e => { state.alang = e.target.value; loadArticles(); });

  // ---------- text rendering ----------
  const inline = s => esc(s).replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1 ↗</a>').replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/\*(.+?)\*/g, '<em>$1</em>');
  function renderBody(body) {
    const toc = []; let h = 0;
    const html = body.split(/\n{2,}/).map(b => {
      b = b.trim(); if (!b) return '';
      if (b.startsWith('## ')) { const id = 'h-' + (h++); toc.push({ id, text: b.slice(3) }); return `<h3 id="${id}">${inline(b.slice(3))}</h3>`; }
      if (b.startsWith('> ')) return `<blockquote>${inline(b.slice(2))}</blockquote>`;
      const lines = b.split('\n');
      if (lines.every(l => l.startsWith('- '))) return '<ul>' + lines.map(l => `<li>${inline(l.slice(2))}</li>`).join('') + '</ul>';
      return `<p>${inline(b).replace(/\n/g, '<br>')}</p>`;
    }).join('');
    return { html, toc };
  }
  const who = a => t(a === 'premium' ? 'who_premium' : 'who_members');
  const lockBadge = a => a && a !== 'public' ? `<span class="lock">🔒 ${esc(who(a))}</span>` : '';
  const hash = s => [...s].reduce((a, c) => (a * 31 + c.charCodeAt(0)) >>> 0, 7);
  const cover = (a, cls = 'cover') => a.cover ? `<img class="${cls}" src="${esc(a.cover)}" alt="" loading="lazy">` : `<div class="${cls} gen g${hash(a.slug) % 6}"><span>${esc(a.category)}</span></div>`;

  // scroll reveal
  const io = 'IntersectionObserver' in window ? new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); } }), { threshold: 0.05 }) : null;
  const reveal = root => $$('.reveal:not(.in)', root || document).forEach(el => (io && !reduced()) ? io.observe(el) : el.classList.add('in'));

  // ---------- routing ----------
  const VIEWS = ['home', 'article', 'library', 'events', 'about', 'contact', 'membership', 'pay', 'account'];
  function show(v) {
    try { if (window.speechSynthesis) speechSynthesis.cancel(); } catch { /* ignore */ }
    VIEWS.forEach(x => $('#view-' + x).classList.toggle('hidden', x !== v));
    $$('.nav-links a[data-r]').forEach(a => a.classList.toggle('active', a.dataset.r === v));
    $('#nav-links').classList.remove('open'); curView = v;
    if (v !== 'article') { $('#progress').style.width = '0'; document.title = 'Horn Polity Forum – Political Science of Ethiopia & the Horn'; }
    window.scrollTo({ top: 0 });
  }
  let curView = 'home';
  function route() {
    if (location.pathname.startsWith('/pay/')) history.replaceState(null, '', '/#/pay/' + location.pathname.split('/')[2]);
    const [r, arg] = location.hash.replace(/^#\/?/, '').split('/');
    if (r === 'a' && arg) return showArticle(arg);
    if (r === 'library') { show('library'); return loadLibrary(); }
    if (r === 'events') { show('events'); return loadEvents(); }
    if (r === 'about') { show('about'); return renderAbout(); }
    if (r === 'contact') { show('contact'); return renderContact(); }
    if (r === 'membership') { show('membership'); return loadMembership(); }
    if (r === 'pay' && arg) { show('pay'); return renderPay(arg); }
    if (r === 'account') { show('account'); return renderAccount(); }
    show('home'); if (!state.loaded) loadArticles(); renderChips();
    if (r === 'articles') $('#articles').scrollIntoView();
  }
  window.addEventListener('hashchange', route);
  const go = h => { location.hash = h; };
  function updateAcctBtn() { $('#acct-btn').textContent = me && me.active ? '👤 ' + me.name.split(' ')[0] : t('signin'); }
  async function loadMe() { try { me = (await api('/member/me')).member; } catch { me = null; } updateAcctBtn(); }
  function applySlider() { const h = Math.max(240, Math.min(800, +site.slider_height || 520)); document.documentElement.style.setProperty('--slider-h', h + 'px'); }
  async function loadSite() { try { site = await api('/site'); } catch { site = {}; } applySlider(); applyStatic(); }

  // ---------- hero slider ----------
  let slides = [], si = 0, slideTimer;
  function goLink(link, e) {
    if (!link) return; if (link.startsWith('#articles')) { if (e) e.preventDefault(); if (location.hash && location.hash !== '#/') go('#/articles'); else $('#articles').scrollIntoView({ behavior: 'smooth' }); return; }
    if (link.startsWith('#')) { if (e) e.preventDefault(); go(link); } else if (e) { e.preventDefault(); location.href = link; }
  }
  async function loadSlides() { try { slides = await api('/slides'); } catch { slides = []; } renderSlider(); }
  function renderSlider() {
    const box = $('#slider'); if (!slides.length) { box.classList.add('hidden'); return; } box.classList.remove('hidden');
    const keys = { 1: 'sl1', 2: 'sl2', 3: 'sl3' };
    box.innerHTML = slides.map((s, i) => {
      const k = keys[s.id] && s.imageUrl.startsWith('/static/img/hero') ? keys[s.id] : null;
      const title = k ? tr(s.title, k + '_t') : s.title, sub = k ? tr(s.subtitle, k + '_s') : s.subtitle, cta = k ? tr(s.cta, k + '_c') : s.cta;
      return `<div class="slide${i === si ? ' on' : ''} ${s.imageUrl ? '' : 'gen g' + (i % 6)}" role="group" aria-label="${i + 1}/${slides.length}">${s.imageUrl ? `<img src="${esc(s.imageUrl)}" alt="">` : ''}
        <div class="slide-in"><span class="eyebrow"><i></i>Horn Polity Forum</span><h2>${esc(title)}</h2>${sub ? `<p>${esc(sub)}</p>` : ''}
        ${s.link && cta ? `<a class="btn btn-primary" href="${esc(s.link)}" data-slide-link="${esc(s.link)}">${esc(cta)} →</a>` : ''}</div></div>`;
    }).join('') + (slides.length > 1 ? `<button class="sl-arrow prev" aria-label="${esc(t('prev'))}">‹</button><button class="sl-arrow next" aria-label="${esc(t('next'))}">›</button>
      <div class="sl-ctl">${slides.map((_, i) => `<button class="sl-dot${i === si ? ' on' : ''}" data-i="${i}" aria-label="${i + 1}"></button>`).join('')}</div>` : '');
    startAuto();
  }
  function showSlide(i) { si = (i + slides.length) % slides.length; $$('#slider .slide').forEach((el, k) => el.classList.toggle('on', k === si)); $$('#slider .sl-dot').forEach((el, k) => el.classList.toggle('on', k === si)); }
  function startAuto() { clearInterval(slideTimer); if (slides.length < 2 || reduced()) return; slideTimer = setInterval(() => { if (curView === 'home' && !document.hidden && !$('#slider').matches(':hover')) showSlide(si + 1); }, Math.max(3, Math.min(15, +site.slider_speed || 6)) * 1000); }
  $('#slider').addEventListener('click', e => {
    const d = e.target.closest('.sl-dot'); if (d) { showSlide(+d.dataset.i); startAuto(); return; }
    if (e.target.closest('.prev')) { showSlide(si - 1); startAuto(); return; } if (e.target.closest('.next')) { showSlide(si + 1); startAuto(); return; }
    const l = e.target.closest('[data-slide-link]'); if (l) goLink(l.dataset.slideLink, e);
  });

  // ---------- home: meta, chips, articles ----------
  function countUp(el, to) {
    if (reduced()) { el.textContent = to.toLocaleString(loc()); return; }
    const t0 = performance.now(), step = n => { const p = Math.min(1, (n - t0) / 900); el.textContent = Math.round(to * p).toLocaleString(loc()); if (p < 1) requestAnimationFrame(step); }; requestAnimationFrame(step);
  }
  async function loadMeta() {
    try {
      const m = await api('/meta');
      $('#hero-stats').innerHTML = [[m.stats.articles, 'stat_articles'], [m.stats.views, 'stat_reads'], [m.stats.categories, 'stat_categories']].map(([n, k]) => `<div><b data-n="${n}">0</b><span>${esc(t(k))}</span></div>`).join('');
      $$('#hero-stats [data-n]').forEach(el => countUp(el, +el.dataset.n));
      $('#tagcloud').innerHTML = m.tags.map(x => `<button class="tag" data-tag="${esc(x.name)}">#${esc(x.name)} · ${x.count}</button>`).join('');
      $('#trending').innerHTML = m.trending.map((a, i) => `<div class="trend" data-slug="${esc(a.slug)}"><b>${i + 1}</b><div>${esc(a.title)}<div class="meta">${esc(t('reads_n', { n: a.views }))}</div></div></div>`).join('');
      cats = m.categories; renderChips();
    } catch (e) { console.error(e); }
    try {
      const ev = await api('/events');
      $('#ev-side').innerHTML = ev.upcoming.slice(0, 3).map(e => `<div class="trend" data-go="#/events"><b>${new Date(e.startsAt).getDate()}</b><div>${esc(e.title)}<div class="meta">${esc(fmtDT(e.startsAt))}</div></div></div>`).join('');
      $('#ev-card').classList.toggle('hidden', !ev.upcoming.length);
    } catch { /* optional */ }
  }
  function renderChips() {
    const chip = (label, attr, on) => `<button class="chip${on ? ' on' : ''}" ${attr}>${label}</button>`;
    $('#chips').innerHTML = chip(esc(t('all')), 'data-cat=""', !state.category && !state.saved && !state.tag) +
      cats.map(c => chip(`${esc(c.name)} (${c.count})`, `data-cat="${esc(c.name)}"`, state.category === c.name)).join('') +
      chip(`🔖 ${esc(t('saved'))} (${bookmarks.length})`, 'data-saved="1"', state.saved) + (state.tag ? chip(`#${esc(state.tag)} ✕`, 'data-cleartag="1"', true) : '');
  }
  function cardHTML(a, big = false) {
    return `<article class="card-a reveal${big ? ' big' : ''}" data-slug="${esc(a.slug)}" tabindex="0">${cover(a)}
      <div class="meta"><span class="badge">${esc(a.category)}</span>${a.featured ? `<span class="star">★ ${esc(t('featured'))}</span>` : ''}${lockBadge(a.access)}<span class="lang-badge">${esc(a.lang)}</span>
        <span>${esc(fmtDate(a.publishedAt))}</span><span>· ${esc(t('min_read', { n: a.readingMinutes }))}</span></div>
      <h3>${esc(a.title)}</h3><p>${esc(a.excerpt)}</p>
      <div class="foot"><span>👁 ${a.views}</span><span>♥ ${a.likes}</span><span>💬 ${a.commentCount}</span><span style="margin-inline-start:auto">${bookmarks.includes(a.slug) ? '🔖 ' + esc(t('saved_btn')) : ''}</span></div></article>`;
  }
  async function loadArticles(reset = true) {
    const grid = $('#grid');
    if (reset) { state.page = 1; grid.innerHTML = '<div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div>'; }
    const p = new URLSearchParams({ page: state.page, per: 6, sort: state.sort });
    if (state.q) p.set('q', state.q); if (state.category) p.set('category', state.category); if (state.tag) p.set('tag', state.tag); if (state.alang) p.set('lang', state.alang);
    if (state.saved) p.set('slugs', bookmarks.join(',') || 'none');
    try {
      const d = await api('/articles?' + p); state.pages = d.pages;
      const html = d.items.map((a, i) => cardHTML(a, reset && i === 0 && !state.q && !state.saved && !state.alang && state.page === 1 && state.sort === 'new' && a.featured)).join('');
      if (reset) grid.innerHTML = '';
      if (!d.total) grid.innerHTML = `<div class="empty" style="grid-column:1/-1">${esc(t(state.saved ? 'no_articles_saved' : 'no_articles'))}</div>`; else { grid.insertAdjacentHTML('beforeend', html); reveal(grid); }
      $('#result-note').textContent = t('n_articles', { n: d.total }) + (state.q ? ' ' + t('for_q', { q: state.q }) : '');
      $('#more').classList.toggle('hidden', state.page >= state.pages); state.loaded = true;
    } catch (e) { grid.innerHTML = `<div class="empty" style="grid-column:1/-1">${esc(t('load_err'))}<br><small>${esc(e.message)}</small></div>`; }
  }
  let debounce;
  $('#search').addEventListener('input', e => { clearTimeout(debounce); debounce = setTimeout(() => { state.q = e.target.value.trim(); loadArticles(); }, 300); });
  $('#sort').addEventListener('change', e => { state.sort = e.target.value; loadArticles(); });
  $('#more').addEventListener('click', () => { state.page++; loadArticles(false); });
  document.addEventListener('keydown', e => {
    if (e.key === '/' && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) { e.preventDefault(); if (location.hash && location.hash !== '#/') go('#/'); setTimeout(() => $('#search').focus(), 50); }
    if (e.key === 'Enter' && e.target.matches('.card-a')) go('#/a/' + e.target.dataset.slug);
  });
  const sug = $('#suggest'); let sugTimer;
  $('#search').addEventListener('input', e => {
    clearTimeout(sugTimer); const v = e.target.value.trim(); if (v.length < 2) { sug.classList.add('hidden'); return; }
    sugTimer = setTimeout(async () => {
      try {
        const list = await api('/suggest?q=' + encodeURIComponent(v));
        sug.innerHTML = list.map(x => x.type === 'article' ? `<button data-sg-slug="${esc(x.slug)}">📄 ${esc(x.label)}</button>` : `<button data-sg-tag="${esc(x.label)}"># ${esc(x.label)}</button>`).join('');
        sug.classList.toggle('hidden', !list.length);
      } catch { sug.classList.add('hidden'); }
    }, 200);
  });
  sug.addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return; sug.classList.add('hidden');
    if (b.dataset.sgSlug) go('#/a/' + b.dataset.sgSlug); else { state.tag = b.dataset.sgTag; state.q = ''; $('#search').value = ''; renderChips(); loadArticles(); }
  });
  document.addEventListener('click', e => { if (!e.target.closest('.search')) sug.classList.add('hidden'); });
  $('#search').addEventListener('keydown', e => { if (e.key === 'Escape') { sug.classList.add('hidden'); e.target.blur(); } });

  function recordRead(a) { history_ = [{ slug: a.slug, tags: a.tags, category: a.category }, ...history_.filter(h => h.slug !== a.slug)].slice(0, 20); store.set('hpf_history', history_); loadReco(); }
  async function loadReco() {
    const card = $('#reco-card'); if (!history_.length) { card.classList.add('hidden'); return; }
    const p = new URLSearchParams({ tags: [...new Set(history_.flatMap(h => h.tags))].slice(0, 20).join(','), cats: [...new Set(history_.map(h => h.category))].join(','), exclude: history_.map(h => h.slug).join(',') });
    try {
      const list = (await api('/recommend?' + p)).slice(0, 3);
      $('#reco').innerHTML = list.map((a, i) => `<div class="trend" data-slug="${esc(a.slug)}"><b>${i + 1}</b><div>${esc(a.title)}<div class="meta">${esc(a.category)} · ${esc(t('min_read', { n: a.readingMinutes }))}</div></div></div>`).join('');
      card.classList.toggle('hidden', !list.length);
    } catch { card.classList.add('hidden'); }
  }
  $('#news-form').addEventListener('submit', async e => {
    e.preventDefault();
    try { const d = await api('/newsletter', { method: 'POST', body: { email: $('#news-email').value } }); setMsg($('#news-msg'), t(d.newSubscription ? 'subscribed' : 'already_sub'), true); $('#news-email').value = ''; }
    catch (err) { setMsg($('#news-msg'), err.message, false); }
  });

  // ---------- article ----------
  function docRow(d) {
    const icon = d.isLink ? '🔗' : ({ pdf: '📕', doc: '📘', docx: '📘', xls: '📗', xlsx: '📗', ppt: '📙', pptx: '📙', csv: '📊', txt: '📄', zip: '🗜️', png: '🖼️', jpg: '🖼️', jpeg: '🖼️' }[d.ext] || '📄');
    const inl = ['pdf', 'png', 'jpg', 'jpeg'].includes(d.ext);
    const openHref = d.isLink ? `/go/${d.id}` : `/files/${d.id}${inl ? '?inline=1' : ''}`;
    const act = d.locked ? `<a class="btn btn-ghost" href="#/${me ? 'membership' : 'account'}">🔒 ${esc(t('only_for', { who: who(d.access) }))}</a>`
      : `<a class="btn btn-primary" href="${openHref}" target="_blank" rel="noopener noreferrer" title="${esc(t('open_new'))}">${esc(d.isLink ? t('open_src') : t('open_doc'))} ↗</a>${d.isLink ? '' : `<a class="btn btn-ghost" href="/files/${d.id}" download>⬇ ${esc(t('download'))}</a>`}`;
    const title = d.locked ? esc(d.title) : `<a class="doc-title" href="${openHref}" target="_blank" rel="noopener noreferrer">${esc(d.title)} ↗</a>`;
    return `<div class="doc"><div class="doc-ic">${icon}</div><div class="doc-main"><b>${title}</b>${d.description ? `<p>${esc(d.description)}</p>` : ''}
      <div class="meta"><span class="badge">${esc(d.category)}</span><span>${d.isLink ? esc(t('src_link')) : esc(d.ext.toUpperCase()) + ' · ' + fmtSize(d.size)}</span><span>👁 ${d.downloads}</span>${lockBadge(d.access)}${d.articleTitle ? `<span>· ${esc(d.articleTitle)}</span>` : ''}</div></div><div class="doc-act">${act}</div></div>`;
  }
  async function showArticle(slug) {
    show('article'); const box = $('#article-box'); box.innerHTML = '<div class="skeleton" style="height:300px"></div>';
    try {
      const a = await api('/articles/' + encodeURIComponent(slug));
      document.title = a.title + ' – Horn Polity Forum';
      const liked = likes.includes(a.slug), saved = bookmarks.includes(a.slug), r = renderBody(a.body);
      const tocHTML = !a.locked && r.toc.length > 1 ? `<div class="toc"><b>${esc(t('toc'))}</b>${r.toc.map(x => `<button data-scroll="${x.id}">${esc(x.text)}</button>`).join('')}</div>` : '';
      const md = document.querySelector('meta[name=description]'); if (md) md.content = a.excerpt;
      const lock = a.locked ? `<div class="lockbox"><h3>🔒 ${esc(t(a.access === 'premium' ? 'lock_premium_h' : 'lock_members_h'))}</h3><p>${esc(t(a.access === 'premium' ? 'lock_premium_p' : 'lock_members_p'))}</p>
        <a class="btn btn-primary" href="#/membership">${esc(t('join'))}</a> <a class="btn btn-ghost" href="#/account">${esc(t('signin'))}</a></div>` : '';
      box.innerHTML = `
        <div class="meta"><span class="badge">${esc(a.category)}</span>${lockBadge(a.access)}<span class="lang-badge">${esc(a.lang)}</span><span>${esc(fmtDate(a.publishedAt))}</span><span>· ${esc(t('min_read', { n: a.readingMinutes }))}</span><span>· ${esc(a.author)}</span><span>· 👁 ${a.views}</span></div>
        <h1>${esc(a.title)}</h1><p class="lead">${esc(a.excerpt)}</p>${cover(a, 'article-cover')}
        <div class="actions"><button class="btn btn-ghost${liked ? ' on' : ''}" id="like-btn">♥ <span id="like-count">${a.likes}</span></button>
          <button class="btn btn-ghost${saved ? ' on' : ''}" id="save-btn">🔖 ${esc(t(saved ? 'saved_btn' : 'save'))}</button>
          <button class="btn btn-ghost" id="share-btn">↗ ${esc(t('share'))}</button><button class="btn btn-ghost" id="listen-btn">🔊 ${esc(t('listen'))}</button>
          <button class="btn btn-ghost" id="print-btn">⎙ ${esc(t('print'))}</button><button class="btn btn-ghost" id="font-dn" aria-label="A-">A−</button><button class="btn btn-ghost" id="font-up" aria-label="A+">A+</button></div>
        ${tocHTML}<div class="prose">${r.html}</div>${lock}
        ${a.documents.length ? `<h3 style="margin-top:34px">📎 ${esc(t('attached'))}</h3>${a.documents.map(docRow).join('')}` : ''}
        <div class="tags" style="margin-top:22px">${a.tags.map(x => `<button class="tag" data-tag="${esc(x)}">#${esc(x)}</button>`).join('')}</div>
        ${a.related.length ? `<h3 style="margin-top:36px">${esc(t('related'))}</h3><div class="related">${a.related.map(x => cardHTML(x)).join('')}</div>` : ''}
        <h3 style="margin-top:36px">${esc(t('comments'))} <span id="c-count" class="meta" style="display:inline"></span></h3>
        <form id="comment-form" class="stack"><div class="form-grid"><input class="input" id="c-name" placeholder="${esc(t('your_name'))}" maxlength="80" required value="${esc(me ? me.name : '')}">
          <input class="input" id="c-email" type="email" placeholder="${esc(t('email_never'))}" required value="${esc(me ? me.email : '')}"></div>
          <textarea class="input" id="c-body" placeholder="${esc(t('comment_ph'))}" maxlength="3000" required></textarea>
          <button class="btn btn-primary" type="submit" style="align-self:flex-start">${esc(t('post_comment'))}</button></form><div id="comments"></div>`;
      reveal(box); wireArticle(a); loadComments(slug); recordRead(a);
    } catch (e) { box.innerHTML = `<div class="empty">${esc(t('not_found'))}<br><a class="btn btn-ghost" href="#/" style="margin-top:12px">${esc(t('back_articles'))}</a></div>`; }
  }
  function wireArticle(a) {
    $('#like-btn').addEventListener('click', async e => {
      const btn = e.currentTarget, on = likes.includes(a.slug);
      try { const r = await api(`/articles/${a.slug}/like`, { method: 'POST', body: { delta: on ? -1 : 1 } }); likes = on ? likes.filter(s => s !== a.slug) : [...likes, a.slug]; store.set('hpf_likes', likes); btn.classList.toggle('on', !on); $('#like-count').textContent = r.likes; }
      catch (err) { toast(err.message, 'err'); }
    });
    $('#save-btn').addEventListener('click', e => {
      const on = bookmarks.includes(a.slug); bookmarks = on ? bookmarks.filter(s => s !== a.slug) : [...bookmarks, a.slug]; store.set('hpf_bookmarks', bookmarks);
      e.currentTarget.classList.toggle('on', !on); e.currentTarget.textContent = '🔖 ' + t(on ? 'save' : 'saved_btn'); toast(t(on ? 'removed_saved' : 'saved_later')); renderChips();
    });
    $('#share-btn').addEventListener('click', async () => {
      const url = location.origin + '/#/a/' + a.slug;
      try { if (navigator.share) await navigator.share({ title: a.title, url }); else { await navigator.clipboard.writeText(url); toast(t('link_copied')); } } catch { /* cancelled */ }
    });
    $('#print-btn').addEventListener('click', () => window.print());
    $('#listen-btn').addEventListener('click', e => {
      const btn = e.currentTarget; if (!('speechSynthesis' in window)) { toast(t('no_speech'), 'err'); return; }
      if (speechSynthesis.speaking) { speechSynthesis.cancel(); btn.textContent = '🔊 ' + t('listen'); return; }
      const u = new SpeechSynthesisUtterance(a.title + '. ' + $('.prose').innerText); u.lang = a.lang === 'om' ? 'om' : a.lang; u.onend = u.onerror = () => { btn.textContent = '🔊 ' + t('listen'); };
      speechSynthesis.speak(u); btn.textContent = '⏹ ' + t('stop');
    });
    const size = n => { document.documentElement.style.setProperty('--prose', n + 'px'); store.set('hpf_font', n); };
    $('#font-up').addEventListener('click', () => size(Math.min(24, store.get('hpf_font', 17) + 1)));
    $('#font-dn').addEventListener('click', () => size(Math.max(14, store.get('hpf_font', 17) - 1)));
    $$('[data-scroll]').forEach(b => b.addEventListener('click', () => { const x = document.getElementById(b.dataset.scroll); if (x) x.scrollIntoView({ behavior: 'smooth' }); }));
    $('#comment-form').addEventListener('submit', async e => {
      e.preventDefault(); const btn = e.submitter; btn.disabled = true;
      try { await api(`/articles/${a.slug}/comments`, { method: 'POST', body: { name: $('#c-name').value, email: $('#c-email').value, body: $('#c-body').value } }); $('#c-body').value = ''; toast(t('comment_posted')); loadComments(a.slug); }
      catch (err) { toast(err.message, 'err'); } finally { btn.disabled = false; }
    });
  }
  async function loadComments(slug) {
    try {
      const list = await api(`/articles/${slug}/comments`); $('#c-count').textContent = `(${list.length})`;
      $('#comments').innerHTML = list.length ? list.map(c => `<div class="comment"><div class="who">${esc(c.name)}<span>${esc(fmtDate(c.createdAt))}</span></div><p>${esc(c.body)}</p></div>`).join('') : `<div class="empty" style="margin-top:10px">${esc(t('no_comments'))}</div>`;
    } catch { $('#comments').textContent = '…'; }
  }
  window.addEventListener('scroll', () => {
    $('#to-top').classList.toggle('hidden', window.scrollY < 700);
    if (curView !== 'article') return; const h = document.documentElement;
    $('#progress').style.width = Math.min(100, (h.scrollTop / Math.max(1, h.scrollHeight - h.clientHeight)) * 100) + '%';
  }, { passive: true });
  $('#to-top').addEventListener('click', () => window.scrollTo({ top: 0, behavior: reduced() ? 'auto' : 'smooth' }));
  $('#back-btn').addEventListener('click', () => go('#/'));

  // ---------- library / events ----------
  const lib = { q: '', category: '' };
  async function loadLibrary() {
    $('#lib-body').innerHTML = spinner; const p = new URLSearchParams(); if (lib.q) p.set('q', lib.q); if (lib.category) p.set('category', lib.category);
    try {
      const d = await api('/documents?' + p);
      $('#lib-chips').innerHTML = `<button class="chip${!lib.category ? ' on' : ''}" data-libcat="">${esc(t('all'))}</button>` + d.categories.map(c => `<button class="chip${lib.category === c ? ' on' : ''}" data-libcat="${esc(c)}">${esc(c)}</button>`).join('');
      $('#lib-body').innerHTML = d.items.length ? d.items.map(docRow).join('') : `<div class="empty">${esc(t('no_docs'))}</div>`;
    } catch (e) { $('#lib-body').innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
  }
  let libT; $('#lib-search').addEventListener('input', e => { clearTimeout(libT); libT = setTimeout(() => { lib.q = e.target.value.trim(); loadLibrary(); }, 300); });
  function eventHTML(e, past) {
    const d = new Date(e.startsAt), link = /^https?:\/\//i.test(e.onlineUrl) ? `<a href="${esc(e.onlineUrl)}" target="_blank" rel="noopener" style="color:var(--accent)">🔗 ${esc(t('join_link'))}</a>` : '';
    let mon = ''; try { mon = d.toLocaleString(loc(), { month: 'short' }); } catch { mon = d.toDateString().slice(4, 7); }
    return `<div class="event${past ? ' past' : ''}"><div class="date-box"><b>${d.getDate()}</b><span>${esc(mon)}</span></div>
      <div style="flex:1"><h3>${esc(e.title)}</h3><div class="meta"><span>🕒 ${esc(fmtDT(e.startsAt))}</span>${e.location ? `<span>📍 ${esc(e.location)}</span>` : ''}${link}</div>
      ${e.description ? `<p>${esc(e.description)}</p>` : ''}
      ${past ? '' : `<button class="btn btn-ghost" data-rsvp="${e.id}">✋ ${esc(t('attend'))}${e.rsvps ? ` (${e.rsvps})` : ''}</button>
      <form class="rsvp-form hidden" data-rsvp-form="${e.id}"><input class="input" placeholder="${esc(t('your_name'))}" required value="${esc(me ? me.name : '')}"><input class="input" type="email" placeholder="${esc(t('email_addr'))}" required value="${esc(me ? me.email : '')}"><button class="btn btn-primary" type="submit">${esc(t('confirm'))}</button></form>`}</div></div>`;
  }
  async function loadEvents() {
    $('#ev-body').innerHTML = spinner;
    try {
      const d = await api('/events');
      $('#ev-body').innerHTML = `<h3>${esc(t('upcoming'))}</h3>${d.upcoming.map(e => eventHTML(e, false)).join('') || `<div class="empty">${esc(t('no_upcoming'))}</div>`}${d.past.length ? `<h3 style="margin-top:28px">${esc(t('past'))}</h3>${d.past.map(e => eventHTML(e, true)).join('')}` : ''}`;
    } catch (e) { $('#ev-body').innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
  }

  // ---------- about / contact ----------
  function contactLines() {
    const l = []; if (site.contact_email) l.push(`✉ <a href="mailto:${esc(site.contact_email)}">${esc(site.contact_email)}</a>`);
    if (site.contact_phone) l.push('📞 ' + esc(site.contact_phone)); if (site.contact_address) l.push('📍 ' + esc(site.contact_address));
    if (/^https?:\/\//i.test(site.telegram || '')) l.push(`💬 <a href="${esc(site.telegram)}" target="_blank" rel="noopener">Telegram</a>`); return l;
  }
  function renderAbout() { $('#about-body').innerHTML = renderBody(siteText('about')).html; const l = contactLines(); $('#about-contact').innerHTML = `<h4>${esc(t('get_touch'))}</h4>${l.length ? l.map(x => `<p>${x}</p>`).join('') : `<p><a href="#/contact" style="color:var(--accent)">${esc(t('use_form'))}</a></p>`}`; }
  let contactPrefill = '';
  function renderContact() {
    const l = contactLines(); $('#contact-info').innerHTML = `<h4>${esc(t('ct_details'))}</h4>${l.length ? l.map(x => `<p>${x}</p>`).join('') : `<p>${esc(t('ct_note'))}</p>`}`;
    if (me) { $('#ct-name').value ||= me.name; $('#ct-email').value ||= me.email; } if (contactPrefill) { $('#ct-subject').value = contactPrefill; contactPrefill = ''; }
  }
  $('#contact-form').addEventListener('submit', async e => {
    e.preventDefault();
    try { await api('/contact', { method: 'POST', body: { name: $('#ct-name').value, email: $('#ct-email').value, subject: $('#ct-subject').value, body: $('#ct-body').value } }); setMsg($('#ct-msg'), t('sent_ok'), true); $('#ct-body').value = ''; $('#ct-subject').value = ''; }
    catch (err) { setMsg($('#ct-msg'), err.message, false); }
  });

  // ---------- membership & checkout (multi-currency) ----------
  const mem = { plans: [], methods: [], currencies: ['ETB', 'USD', 'EUR'], plan: 'supporter', method: null };
  const guessCur = () => { try { if (/Addis_Ababa/.test(Intl.DateTimeFormat().resolvedOptions().timeZone) || /-ET$/.test(navigator.language || '') || ['am', 'om'].includes(lang)) return 'ETB'; } catch { /* ignore */ } return 'USD'; };
  let cur = store.get('hpf_cur', null) || guessCur();
  const methodIcon = k => ({ telebirr: '📱', chapa: '💳', stripe: '💳', card: '💳', alipay: '🔷', alipay_qr: '🔷', payoneer: '🅿', paypal: '🅿️', bank: '🏦', wire: '🌍', cbebirr: '📱', mpesa: '📱' }[k] || '💰');
  const BRANDS = { card: [['visa', 'VISA'], ['mc', 'Mastercard']], stripe: [['visa', 'VISA'], ['mc', 'Mastercard']], paypal: [['pp', 'PayPal']], alipay: [['ali', 'Alipay']], alipay_qr: [['ali', 'Alipay']], payoneer: [['po', 'Payoneer']] };
  const badges = k => (BRANDS[k] || []).map(([c, n]) => `<span class="pbrand ${c}">${n}</span>`).join('');
  const priceOf = (p, c) => ({ ETB: p.priceEtb, USD: p.priceUsd, EUR: p.priceEur })[c] || 0;
  const pName = p => tr(p.name, 'pn_' + p.key), pBen = p => tr(p.benefits, 'plan_' + p.key + '_b'), mLabel = m => tr(m.label, 'mt_' + m.kind);
  async function loadMembership() {
    $('#mem-body').innerHTML = spinner;
    try { const d = await api('/plans'); mem.plans = d.plans; mem.methods = d.methods; mem.currencies = d.currencies; if (!mem.plans.find(p => p.key === mem.plan)) mem.plan = mem.plans[0]?.key; renderMembership(); }
    catch (e) { $('#mem-body').innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
  }
  function planPrice(p) { if (p.custom) return t('custom'); if (p.priceEtb === 0) return t('free'); const v = priceOf(p, cur); return v > 0 ? money(v * 100, cur) : '—'; }
  function renderMembership() {
    const sel = mem.plans.find(p => p.key === mem.plan) || {}; const paid = sel.priceEtb > 0 && !sel.custom, price = priceOf(sel, cur);
    const avail = mem.methods.filter(m => m.currencies.includes(cur)); if (!avail.find(m => m.id === mem.method)) mem.method = avail.length === 1 ? avail[0].id : null;
    const curBar = `<div class="cur-sel"><b>${esc(t('currency'))}:</b>${mem.currencies.map(c => `<button class="chip${c === cur ? ' on' : ''}" data-cur="${c}">${c}</button>`).join('')}</div>`;
    const planCards = mem.plans.map(p => { const ok = p.custom || p.priceEtb === 0 || priceOf(p, cur) > 0; return `<div class="plan${p.key === mem.plan ? ' sel' : ''}" data-plan="${esc(p.key)}"><h3>${esc(pName(p))}</h3>
      <div class="price">${esc(planPrice(p))}${p.priceEtb > 0 && !p.custom && ok ? `<small> ${esc(p.periodDays === 30 ? t('per_month') : t('per_days', { n: p.periodDays }))}</small>` : ''}</div>
      <p>${esc(pBen(p))}</p>${ok ? '' : `<span class="price-note">${esc(t('not_in_cur'))}</span>`}<button class="btn ${p.key === mem.plan ? 'btn-primary' : 'btn-ghost'}" type="button" data-plan-btn="${esc(p.key)}" ${ok ? '' : 'disabled'}>${esc(p.custom ? t('contact_us') : p.key === mem.plan ? '✓ ' + t('selected') : t('choose'))}</button></div>`; }).join('');
    const methods = paid ? (avail.length ? `<h4 style="margin:14px 0 4px">${esc(t('pay_method'))}</h4><div class="methods">${avail.map(m => `<label class="method${mem.method === m.id ? ' sel' : ''}"><input type="radio" name="pm" value="${m.id}" ${mem.method === m.id ? 'checked' : ''}><span class="mi">${methodIcon(m.kind)}</span><span>${esc(mLabel(m))} ${badges(m.kind)}<small>${esc(t(m.online ? 'm_online' : 'm_manual'))}</small></span></label>`).join('')}</div>`
      : `<div class="note">${esc(t('methods_setup'))}</div>`) : '';
    const canBuy = !paid || (avail.length && price > 0);
    $('#mem-body').innerHTML = curBar + `<div class="plans">${planCards}</div>
      <form id="checkout-form" class="side-card stack"><h4>${esc(paid && price > 0 ? t('join_plan_price', { plan: pName(sel), price: money(price * 100, cur) }) : t('join_plan', { plan: pName(sel) || '' }))}</h4>
        <div class="form-grid"><input class="input" id="co-name" placeholder="${esc(t('full_name'))}" required value="${esc(me ? me.name : '')}"><input class="input" id="co-email" type="email" placeholder="${esc(t('email_addr'))}" required value="${esc(me ? me.email : '')}"></div>
        <input class="input" id="co-aff" placeholder="${esc(t('affil'))}">${methods}
        <button class="btn btn-primary" type="submit" style="align-self:flex-start" ${canBuy ? '' : 'disabled'}>${esc(paid ? t('cont_pay') : t('join_free'))}</button><div class="msg" id="co-msg"></div></form>`;
  }
  $('#mem-body').addEventListener('click', e => {
    const c = e.target.closest('[data-cur]'); if (c) { cur = c.dataset.cur; store.set('hpf_cur', cur); renderMembership(); return; }
    const pc = e.target.closest('[data-plan]'); if (!pc || e.target.closest('button[disabled]')) return; const p = mem.plans.find(x => x.key === pc.dataset.plan);
    if (p.custom) { contactPrefill = pName(p); go('#/contact'); return; } mem.plan = p.key; renderMembership();
  });
  $('#mem-body').addEventListener('change', e => { if (e.target.name === 'pm') { mem.method = +e.target.value; $$('.method').forEach(m => m.classList.toggle('sel', m.contains(e.target))); } });
  $('#mem-body').addEventListener('submit', async e => {
    e.preventDefault(); const btn = e.submitter, msg = $('#co-msg'), sel = mem.plans.find(p => p.key === mem.plan), paid = sel.priceEtb > 0;
    if (paid && !mem.method) { setMsg(msg, t('pick_method'), false); return; }
    btn.disabled = true; const email = $('#co-email').value.trim().toLowerCase();
    try {
      const r = await api('/checkout', { method: 'POST', body: { name: $('#co-name').value, email, affiliation: $('#co-aff').value, plan: mem.plan, currency: cur, methodId: paid ? mem.method : null } });
      if (r.accessCode) { store.set('hpf_creds', { email, code: r.accessCode }); try { await api('/member/login', { method: 'POST', body: { email, code: r.accessCode } }); await loadMe(); } catch { /* ignore */ } }
      if (r.free) { go('#/account'); toast(t(r.existing ? 'reg_signin' : 'welcome_code')); return; }
      if (r.checkoutUrl) { toast(t('redirecting')); location.href = r.checkoutUrl; return; }
      go('#/pay/' + r.ref);
    } catch (err) { setMsg(msg, err.message, false); btn.disabled = false; }
  });

  // ---------- payment status ----------
  const copyRow = (label, val) => val ? `<div class="copyrow"><span>${esc(label)}</span><b>${esc(val)}</b><button type="button" data-copy="${esc(val)}">⧉</button></div>` : '';
  const online = o => ['chapa', 'stripe', 'paypal'].includes(o.provider);
  async function renderPay(ref, verify = true) {
    const box = $('#pay-body'); box.innerHTML = spinner;
    try {
      let o = await api('/orders/' + encodeURIComponent(ref));
      if (verify && online(o) && ['pending', 'failed'].includes(o.status)) { try { o = await api(`/orders/${encodeURIComponent(ref)}/verify`, { method: 'POST' }); } catch { /* keep o */ } }
      await loadMe(); const creds = store.get('hpf_creds', null), amt = money(o.amountMinor, o.currency);
      const head = `<div class="side-card"><div class="row"><b style="font-size:18px">${esc(t('order'))} ${esc(o.ref)}</b><span class="status ${esc(o.status)}" style="margin-inline-start:auto">${esc(t('s_' + o.status))}</span></div>
        <p style="margin:6px 0 0">${esc(t('plan_m', { plan: tr(o.planName, 'pn_' + o.plan) }))} · <b>${esc(amt)}</b></p></div>`;
      let body = '';
      if (o.status === 'paid') body = `<div class="side-card"><h4>🎉 ${esc(t('pay_ok_h'))}</h4><p>${esc(t('pay_ok_p'))}</p>${creds ? `<p>${esc(t('code_keep'))}</p><div class="codebox">${esc(creds.code)}</div>` : ''}<a class="btn btn-primary" href="#/account">${esc(t('go_acct'))}</a> <a class="btn btn-ghost" href="#/library">${esc(t('open_lib'))}</a></div>`;
      else if (online(o) && o.status === 'submitted') body = `<div class="side-card"><h4>⏳ ${esc(t('online_h'))}</h4><div class="note">${esc(t('online_wait'))}</div><button class="btn btn-ghost" id="recheck">${esc(t('i_paid'))}</button></div>`;
      else if (online(o)) body = `<div class="side-card"><h4>${methodIcon(o.provider)} ${esc(t('online_h'))}</h4>${o.status === 'failed' ? `<div class="note">${esc(t('online_failed'))}${o.note ? ' (' + esc(o.note) + ')' : ''}</div>` : `<p>${esc(t('online_p'))}</p>`}
        <div class="row">${o.checkoutUrl ? `<a class="btn btn-primary" href="${esc(o.checkoutUrl)}">${esc(t('continue_to_pay'))}</a>` : `<a class="btn btn-primary" href="#/membership">${esc(t('start_new'))}</a>`}<button class="btn btn-ghost" id="recheck">${esc(t('i_paid'))}</button></div></div>`;
      else {
        const m = o.method || {};
        body = `<div class="side-card"><h4>${methodIcon(m.kind)} ${esc(t('pay_with', { label: tr(m.label || '', 'mt_' + m.kind) }))}</h4><ol class="steps">
          <li>${esc(t('st1', { amount: amt }))}</li><li>${esc(t('st2'))} <b>${esc(o.ref)}</b></li><li>${esc(t('st3'))}</li></ol>
          ${copyRow(t('acct_name'), m.accountName)}${copyRow(t('acct_num'), m.accountNumber)}${copyRow(t('amount'), (o.amountMinor / 100) + ' ' + o.currency)}${copyRow(t('reference'), o.ref)}
          ${/^https?:\/\//i.test(m.payLink || '') ? `<p><a class="btn btn-primary" href="${esc(m.payLink)}" target="_blank" rel="noopener noreferrer">${esc(t('pay_open'))} ↗</a></p>` : ''}
          ${m.qrUrl ? `<div class="qrbox"><img class="qr" src="${esc(m.qrUrl)}" alt="QR"><div>${esc(t('scan_qr'))}</div></div>` : ''}
          ${m.instructions ? `<p style="margin-top:10px">${esc(m.instructions)}</p>` : ''}</div>
          <form id="proof-form" class="side-card stack"><h4>${esc(t(o.status === 'submitted' ? 'awaiting' : 'confirm_pay'))}</h4>
          ${o.status === 'rejected' ? `<div class="note">${esc(t('not_verified'))}${o.note ? ': ' + esc(o.note) : ''}</div>` : ''}${o.status === 'submitted' ? `<p>${esc(t('awaiting_p'))}</p>` : ''}
          <input class="input" id="pf-tx" placeholder="${esc(t('tx_ph'))}" value="${esc(o.txRef)}" maxlength="80">
          <label style="font-size:13px;color:var(--muted)">${esc(t('receipt_lbl'))}<input class="input" id="pf-file" type="file" accept=".jpg,.jpeg,.png,.webp,.pdf"></label>
          <button class="btn btn-primary" type="submit" style="align-self:flex-start">${esc(t(o.status === 'submitted' ? 'update_details' : 'submit_details'))}</button><div class="msg" id="pf-msg"></div></form>`;
      }
      const codeNote = creds && o.status !== 'paid' ? `<div class="side-card"><h4>${esc(t('your_code'))}</h4><p>${esc(t('your_code_p'))}</p><div class="codebox">${esc(creds.code)}</div></div>` : '';
      box.innerHTML = head + body + codeNote;
      const rc = $('#recheck'); if (rc) rc.addEventListener('click', async () => { rc.disabled = true; await renderPay(ref, true); toast(t('refreshed')); });
      const pf = $('#proof-form'); if (pf) pf.addEventListener('submit', async e => {
        e.preventDefault(); const fd = new FormData(); fd.append('tx_ref', $('#pf-tx').value); const f = $('#pf-file').files[0]; if (f) fd.append('file', f); e.submitter.disabled = true;
        try { await api(`/orders/${encodeURIComponent(ref)}/proof`, { method: 'POST', body: fd }); toast(t('details_sent')); renderPay(ref, false); }
        catch (err) { setMsg($('#pf-msg'), err.message, false); e.submitter.disabled = false; }
      });
    } catch (e) { box.innerHTML = `<div class="empty">${esc(e.message)}<br><a class="btn btn-ghost" href="#/membership" style="margin-top:12px">${esc(t('back_mem'))}</a></div>`; }
  }

  // ---------- account ----------
  async function renderAccount() {
    await loadMe(); const box = $('#acct-body'), creds = store.get('hpf_creds', {});
    if (me) {
      const exp = me.expiresAt ? esc(t('active_until', { date: fmtDate(me.expiresAt) })) : esc(t('no_expiry'));
      box.innerHTML = `<div class="side-card"><div class="row"><h4 style="margin:0">${esc(me.name)}</h4><span class="status ${me.active ? 'active' : 'inactive'}" style="margin-inline-start:auto">${esc(t(me.active ? 's_active' : 's_inactive'))}</span></div>
        <p>${esc(me.email)} · <b>${esc(tr(me.planName, 'pn_' + me.plan))}</b> ${esc(t('plan_word'))} · ${exp}</p>
        ${creds.email === me.email && creds.code ? `<p>${esc(t('your_code'))}:</p><div class="codebox">${esc(creds.code)}</div>` : ''}
        <div class="row"><a class="btn btn-primary" href="#/library">${esc(t('open_lib'))}</a><a class="btn btn-ghost" href="#/membership">${esc(t('upgrade'))}</a><button class="btn btn-ghost" id="logout-btn">${esc(t('sign_out'))}</button></div></div>`;
      $('#logout-btn').addEventListener('click', async () => { await api('/member/logout', { method: 'POST' }); me = null; updateAcctBtn(); toast(t('signed_out')); renderAccount(); });
    } else {
      box.innerHTML = `<form id="login-form" class="side-card stack" style="max-width:440px"><h4>${esc(t('signin'))}</h4><p>${esc(t('signin_p'))}</p>
        <input class="input" id="lg-email" type="email" placeholder="${esc(t('email_addr'))}" required value="${esc(creds.email || '')}"><input class="input" id="lg-code" placeholder="${esc(t('code_ph'))}" required value="${esc(creds.code || '')}" autocomplete="off">
        <button class="btn btn-primary" type="submit">${esc(t('signin'))}</button><div class="msg" id="lg-msg"></div><p style="margin:0;font-size:13px">${esc(t('new_here'))} <a href="#/membership" style="color:var(--accent)">${esc(t('join_forum'))}</a></p></form>`;
      $('#login-form').addEventListener('submit', async e => {
        e.preventDefault();
        try { await api('/member/login', { method: 'POST', body: { email: $('#lg-email').value, code: $('#lg-code').value } }); await loadMe(); toast(t('signed_in')); renderAccount(); }
        catch (err) { setMsg($('#lg-msg'), err.message, false); }
      });
    }
  }

  // ---------- global handlers ----------
  document.addEventListener('click', e => {
    const copy = e.target.closest('[data-copy]'); if (copy) { navigator.clipboard.writeText(copy.dataset.copy).then(() => toast('✓')).catch(() => toast('✗', 'err')); return; }
    const g = e.target.closest('[data-go]'); if (g) { go(g.dataset.go); return; }
    const rs = e.target.closest('[data-rsvp]'); if (rs) { $(`[data-rsvp-form="${rs.dataset.rsvp}"]`).classList.toggle('hidden'); return; }
    const lc = e.target.closest('[data-libcat]'); if (lc) { lib.category = lc.dataset.libcat; loadLibrary(); return; }
    const chip = e.target.closest('#chips .chip');
    if (chip) {
      if ('saved' in chip.dataset) { state.saved = !state.saved; state.category = ''; } else if ('cleartag' in chip.dataset) state.tag = ''; else { state.category = chip.dataset.cat; state.saved = false; state.tag = ''; }
      renderChips(); loadArticles(); return;
    }
    const tag = e.target.closest('[data-tag]');
    if (tag) { state.tag = tag.dataset.tag; state.category = ''; state.saved = false; renderChips(); loadArticles(); if (location.hash !== '#/' && location.hash !== '') go('#/'); return; }
    const card = e.target.closest('[data-slug]'); if (card && !e.target.closest('button,a')) go('#/a/' + card.dataset.slug);
  });
  document.addEventListener('submit', async e => {
    const f = e.target.closest('[data-rsvp-form]'); if (!f) return; e.preventDefault(); const [n, em] = $$('input', f);
    try { const r = await api(`/events/${f.dataset.rsvpForm}/rsvp`, { method: 'POST', body: { name: n.value, email: em.value } }); toast(t(r.new ? 'on_list' : 'already_reg')); f.classList.add('hidden'); loadEvents(); }
    catch (err) { toast(err.message, 'err'); }
  });

  // ---------- init ----------
  $('#year').textContent = new Date().getFullYear();
  document.documentElement.style.setProperty('--prose', store.get('hpf_font', 17) + 'px');
  applyComfort(); applyStatic(); renderChips();
  if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => { /* optional */ });
  Promise.all([loadMe(), loadSite(), loadSlides()]).finally(() => { startAuto(); route(); });
  loadMeta(); loadReco();
})();
