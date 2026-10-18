(() => {
  'use strict';
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const money = (m, c = 'ETB') => { try { return new Intl.NumberFormat('en-US', { style: 'currency', currency: c, minimumFractionDigits: 0, maximumFractionDigits: 2 }).format(m / 100); } catch { return c + ' ' + m / 100; } };
  const fmt = d => d ? new Date(d).toLocaleString() : '';
  const size = n => n > 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB';

  async function api(path, { method = 'GET', body } = {}) {
    const opts = { method, headers: { 'X-Requested-With': 'fetch' }, credentials: 'same-origin' };
    if (body instanceof FormData) opts.body = body;
    else if (body !== undefined) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
    const r = await fetch('/api' + path, opts); let d = null; try { d = await r.json(); } catch { /* ignore */ }
    if (!r.ok) { const e = new Error((d && d.error) || 'Request failed'); e.status = r.status; throw e; }
    return d;
  }
  function toast(msg, err) { const t = document.createElement('div'); t.className = 'toast' + (err ? ' err' : ''); t.textContent = msg; $('#toasts').appendChild(t); setTimeout(() => t.remove(), 3800); }
  const act = async (fn, ok) => { try { await fn(); if (ok) toast(ok); render(); } catch (e) { toast(e.message, true); } };

  const inline = t => esc(t).replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1 ↗</a>').replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/\*(.+?)\*/g, '<em>$1</em>');
  function renderBody(body) {
    return body.split(/\n{2,}/).map(b => { b = b.trim(); if (!b) return '';
      if (b.startsWith('## ')) return `<h3>${inline(b.slice(3))}</h3>`; if (b.startsWith('> ')) return `<blockquote>${inline(b.slice(2))}</blockquote>`;
      const l = b.split('\n'); if (l.every(x => x.startsWith('- '))) return '<ul>' + l.map(x => `<li>${inline(x.slice(2))}</li>`).join('') + '</ul>';
      return `<p>${inline(b).replace(/\n/g, '<br>')}</p>`; }).join('');
  }

  let tab = 'overview', sub = 'orders', editing = null, articles = [];

  async function boot() {
    const me = await api('/admin/me').catch(() => ({ admin: false }));
    $('#login').classList.toggle('hidden', me.admin); $('#panel').classList.toggle('hidden', !me.admin); if (me.admin) render();
  }
  $('#login-form').addEventListener('submit', async e => { e.preventDefault(); try { await api('/admin/login', { method: 'POST', body: { password: $('#pw').value } }); $('#pw').value = ''; boot(); } catch (err) { $('#login-msg').textContent = err.message; } });
  $('#logout').addEventListener('click', async () => { await api('/admin/logout', { method: 'POST' }); boot(); });
  $('#tabs').addEventListener('click', e => {
    const b = e.target.closest('[data-tab]'); if (!b) return; tab = b.dataset.tab; editing = null;
    $$('#tabs .chip').forEach(c => c.classList.toggle('on', c === b)); render();
  });

  async function render() {
    const body = $('#tab-body');
    try {
      await ({ overview, articles: articlesTab, slides: slidesTab, documents: documentsTab, events: eventsTab, payments: paymentsTab, people: peopleTab, messages: messagesTab, comments: commentsTab, site: siteTab, settings: settingsTab }[tab])(body);
    } catch (err) { if (err.status === 401) boot(); else toast(err.message, true); }
  }
  const table = (head, rows, empty = 'Nothing here yet') => `<div class="scroll-x"><table><tr>${head.map(h => `<th>${h}</th>`).join('')}</tr>${rows.join('') || `<tr><td colspan="${head.length}">${empty}</td></tr>`}</table></div>`;
  const accessSel = (id, v) => `<select class="input" id="${id}"><option value="public"${v === 'public' ? ' selected' : ''}>Public</option><option value="members"${v === 'members' ? ' selected' : ''}>Members (any signed-in member)</option><option value="premium"${v === 'premium' ? ' selected' : ''}>Premium (paid supporters)</option></select>`;

  // ---------- overview ----------
  async function overview(body) {
    const [s, ms] = await Promise.all([api('/admin/stats'), api('/admin/payment-methods')]);
    const k = (n, l) => `<div class="kpi"><b>${n}</b><span>${l}</span></div>`;
    const setup = ms.some(m => m.available) ? '' : `<div class="note">⚠ No payment method is available to visitors yet. Open <b>Payments → Methods</b>, enter your Telebirr number / bank account and tick “Enabled”. For online checkout add CHAPA_SECRET_KEY to the .env file.</div>`;
    body.innerHTML = `${setup}${s.pendingOrders ? `<div class="note">💳 <b>${s.pendingOrders}</b> payment(s) waiting for your confirmation → <b>Payments → Orders</b></div>` : ''}
      <div class="kpis">${k(s.articles, 'Published')}${k(s.drafts, 'Drafts')}${k(s.views, 'Total reads')}${k(s.likes, 'Likes')}${k(s.comments, 'Comments')}${k(s.subscribers, 'Subscribers')}${k(s.members, 'Members')}
      ${k(Object.entries(s.revenueByCurrency).map(([c, m]) => money(m, c)).join(' + ') || money(0), 'Confirmed revenue')}${k(s.pendingOrders, 'Payments to confirm')}${k(s.unreadMessages, 'Unread messages')}${k(s.documents, 'Documents')}${k(s.events, 'Events')}</div>
      <h3>Top articles by reads</h3><div class="bars side-card">${s.top.map(t => `<div class="bar"><span title="${esc(t.title)}">${esc(t.title)}</span><div class="fill" style="width:${Math.max(3, Math.round(t.views / (s.top[0].views || 1) * 55))}%"></div><b>${t.views}</b></div>`).join('')}</div>
      <h3>Recent comments</h3>${table(['Who', 'Comment', 'On'], s.recentComments.map(c => `<tr><td>${esc(c.name)}</td><td>${esc(c.body)}</td><td>${esc(c.title)}</td></tr>`), 'None yet')}
      <h3>Members by plan</h3><p>${Object.entries(s.tiers).map(([t, n]) => `${esc(t)}: <b>${n}</b>`).join(' · ') || 'No members yet'}</p>`;
  }

  // ---------- articles ----------
  async function articlesTab(body) {
    articles = await api('/admin/articles'); if (editing !== null) return articleEditor(body);
    body.innerHTML = `<button class="btn btn-primary" id="new-art">+ New article</button>` + table(['Title', 'Category', 'Access', 'Status', 'Reads', ''], articles.map(a => `<tr><td>${esc(a.title)}${a.featured ? ' <span class="star">★</span>' : ''}</td><td>${esc(a.category)}</td><td>${esc(a.access)}</td><td>${a.published ? 'Published' : 'Draft'}</td><td>${a.views}</td>
      <td><button class="btn btn-ghost" data-toggle="${a.id}">${a.published ? 'Unpublish' : 'Publish'}</button> <button class="btn btn-ghost" data-edit="${a.id}">Edit</button> <button class="btn btn-ghost danger" data-del="${a.id}">Delete</button></td></tr>`));
    $('#new-art').onclick = () => { editing = 0; articleEditor(body); };
    $$('[data-edit]', body).forEach(b => b.onclick = () => { editing = +b.dataset.edit; articleEditor(body); });
    $$('[data-toggle]', body).forEach(b => b.onclick = () => { const a = articles.find(x => x.id === +b.dataset.toggle); act(() => api('/admin/articles/' + a.id, { method: 'PUT', body: { ...a, published: !a.published } }), a.published ? 'Unpublished' : 'Published'); });
    $$('[data-del]', body).forEach(b => b.onclick = () => { if (confirm('Delete this article and its comments?')) act(() => api('/admin/articles/' + b.dataset.del, { method: 'DELETE' }), 'Deleted'); });
  }
  function articleEditor(body) {
    const a = articles.find(x => x.id === editing) || { title: '', category: 'Essay', tags: [], excerpt: '', body: '', author: 'Editorial Board', featured: false, published: true, access: 'public' };
    body.innerHTML = `<h3>${editing ? 'Edit' : 'New'} article</h3><form id="art-form" class="stack">
      <input class="input" id="f-title" placeholder="Title" value="${esc(a.title)}" required maxlength="200">
      <div class="form-grid"><input class="input" id="f-cat" placeholder="Category" value="${esc(a.category)}"><input class="input" id="f-author" placeholder="Author" value="${esc(a.author)}"></div>
      <input class="input" id="f-tags" placeholder="Tags, comma separated" value="${esc(a.tags.join(', '))}"><input class="input" id="f-excerpt" placeholder="Short excerpt" value="${esc(a.excerpt)}" maxlength="400">
      <div class="form-grid"><label style="font-size:13px;color:var(--muted)">Who can read the full text?${accessSel('f-access', a.access)}</label>
        <label style="font-size:13px;color:var(--muted)">Article language<select class="input" id="f-lang">${[['en', 'English'], ['am', 'አማርኛ'], ['om', 'Afaan Oromoo'], ['ar', 'العربية']].map(([v, n]) => `<option value="${v}"${(a.lang || 'en') === v ? ' selected' : ''}>${n}</option>`).join('')}</select></label></div>
      <label style="font-size:13px;color:var(--muted)">Cover image (JPG/PNG/WebP, max 6 MB) – optional, a pattern is generated if empty${a.cover ? `<br><img src="${esc(a.cover)}" alt="" style="max-height:90px;border-radius:8px;margin:6px 0"> <button class="btn btn-ghost danger" type="button" id="cover-del">Remove cover</button>` : ''}
        <input class="input" type="file" id="f-cover" accept=".jpg,.jpeg,.png,.webp,.gif"></label>
      <textarea class="input" id="f-body" style="min-height:300px" placeholder="Blank line = new paragraph. '## ' heading, '> ' quote, '- ' list, **bold**, *italic*, [source name](https://link) opens in a new tab." required>${esc(a.body)}</textarea>
      <b style="font-size:12px;color:var(--muted)">LIVE PREVIEW</b><div class="preview prose" id="preview"></div>
      <div class="row"><label><input type="checkbox" id="f-feat" ${a.featured ? 'checked' : ''}> Featured</label><label><input type="checkbox" id="f-pub" ${a.published ? 'checked' : ''}> Published</label></div>
      <div class="row"><button class="btn btn-primary" type="submit">Save</button><button class="btn btn-ghost" type="button" id="cancel">Cancel</button></div></form>`;
    const key = 'hpf_draft_' + editing, preview = () => { $('#preview').innerHTML = renderBody($('#f-body').value) || '<p style="color:var(--muted)">Nothing to preview yet.</p>'; };
    if (!editing) { try { const d = JSON.parse(localStorage.getItem(key) || 'null'); if (d && (d.title || d.body)) { $('#f-title').value = d.title; $('#f-body').value = d.body; toast('Restored your unsaved draft'); } } catch { /* ignore */ } }
    $('#art-form').addEventListener('input', () => { preview(); if (!editing) { try { localStorage.setItem(key, JSON.stringify({ title: $('#f-title').value, body: $('#f-body').value })); } catch { /* ignore */ } } });
    preview(); $('#cancel').onclick = () => { editing = null; render(); };
    const cd = $('#cover-del'); if (cd) cd.onclick = () => act(() => api(`/admin/articles/${editing}/cover`, { method: 'DELETE' }), 'Cover removed');
    $('#art-form').onsubmit = async e => { e.preventDefault();
      const payload = { title: $('#f-title').value, category: $('#f-cat').value, author: $('#f-author').value, tags: $('#f-tags').value, excerpt: $('#f-excerpt').value, body: $('#f-body').value, access: $('#f-access').value, lang: $('#f-lang').value, featured: $('#f-feat').checked, published: $('#f-pub').checked };
      try { const saved = await api(editing ? '/admin/articles/' + editing : '/admin/articles', { method: editing ? 'PUT' : 'POST', body: payload });
        const cf = $('#f-cover').files[0]; if (cf) { const fd = new FormData(); fd.append('file', cf); await api(`/admin/articles/${saved.id}/cover`, { method: 'POST', body: fd }); }
        try { localStorage.removeItem(key); } catch { /* ignore */ } toast('Saved'); editing = null; render(); } catch (err) { toast(err.message, true); } };
  }

  // ---------- documents ----------
  async function documentsTab(body) {
    const [docs, arts] = await Promise.all([api('/admin/documents'), api('/admin/articles')]);
    const d = docs.find(x => x.id === editing) || { title: '', description: '', category: 'General', access: 'public', articleId: null, isLink: false, url: '' };
    body.innerHTML = `<h3>${editing ? (d.isLink ? 'Edit web source' : 'Edit document') : 'Add a document or web source'}</h3>
      <form id="doc-form" class="side-card stack">${editing ? (d.isLink ? `<input class="input" id="d-url" type="url" placeholder="https://…" required value="${esc(d.url || '')}">` : '') : `<div class="row"><label><input type="radio" name="dmode" value="file" checked> 📄 Upload a file</label><label><input type="radio" name="dmode" value="link"> 🔗 Web link (opens in a new tab)</label></div>
        <input class="input" type="file" id="d-file" accept=".pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.csv,.txt,.rtf,.odt,.zip,.png,.jpg,.jpeg"><input class="input hidden" id="d-url" type="url" placeholder="https://example.org/report">`}
        <div class="form-grid"><input class="input" id="d-title" placeholder="Title (optional – file name is used)" value="${esc(d.title)}" maxlength="200"><input class="input" id="d-cat" placeholder="Category (e.g. Working papers)" value="${esc(d.category)}"></div>
        <input class="input" id="d-desc" placeholder="Short description" value="${esc(d.description)}" maxlength="600">
        <div class="form-grid"><label style="font-size:13px;color:var(--muted)">Access${accessSel('d-access', d.access)}</label>
          <label style="font-size:13px;color:var(--muted)">Attach to article (optional)<select class="input" id="d-art"><option value="">— none —</option>${arts.map(a => `<option value="${a.id}"${a.id === d.articleId ? ' selected' : ''}>${esc(a.title)}</option>`).join('')}</select></label></div>
        <div class="row"><button class="btn btn-primary" type="submit">${editing ? 'Save changes' : '⬆ Upload'}</button>${editing ? '<button class="btn btn-ghost" type="button" id="cancel">Cancel</button>' : ''}</div></form>
      <h3>Library (${docs.length})</h3>` + table(['Document', 'Category', 'Access', 'Attached to', 'Downloads', ''], docs.map(x => `<tr><td>${x.isLink ? '🔗 ' : ''}${esc(x.title)}<br><small>${x.isLink ? esc(x.url) : esc(x.ext.toUpperCase()) + ' · ' + size(x.size)}</small></td><td>${esc(x.category)}</td><td>${esc(x.access)}</td><td>${esc(x.articleTitle || '—')}</td><td>${x.downloads}</td>
        <td><a class="btn btn-ghost" href="${x.isLink ? '/go/' : '/files/'}${x.id}" target="_blank" rel="noopener noreferrer">Open ↗</a> <button class="btn btn-ghost" data-edit="${x.id}">Edit</button> <button class="btn btn-ghost danger" data-del="${x.id}">Delete</button></td></tr>`));
    $$('[data-edit]', body).forEach(b => b.onclick = () => { editing = +b.dataset.edit; render(); });
    $$('[data-del]', body).forEach(b => b.onclick = () => { if (confirm('Delete this document?')) act(() => api('/admin/documents/' + b.dataset.del, { method: 'DELETE' }), 'Deleted'); });
    const c = $('#cancel'); if (c) c.onclick = () => { editing = null; render(); };
    $$('[name=dmode]', body).forEach(r => r.onchange = () => { const link = r.value === 'link' && r.checked; $('#d-file').classList.toggle('hidden', link); $('#d-url').classList.toggle('hidden', !link); $('#d-url').required = link; });
    $('#doc-form').onsubmit = async e => { e.preventDefault(); const btn = e.submitter; btn.disabled = true;
      try {
        const linkMode = !editing && $('[name=dmode]:checked', body).value === 'link';
        if (editing) await api('/admin/documents/' + editing, { method: 'PUT', body: { url: $('#d-url') ? $('#d-url').value : undefined, title: $('#d-title').value, description: $('#d-desc').value, category: $('#d-cat').value, access: $('#d-access').value, articleId: $('#d-art').value ? +$('#d-art').value : null } });
        else { const fd = new FormData(); if (linkMode) fd.append('url', $('#d-url').value); else { if (!$('#d-file').files[0]) throw new Error('Choose a file first'); fd.append('file', $('#d-file').files[0]); } fd.append('title', $('#d-title').value); fd.append('description', $('#d-desc').value); fd.append('category', $('#d-cat').value); fd.append('access', $('#d-access').value); fd.append('article_id', $('#d-art').value); await api('/admin/documents', { method: 'POST', body: fd }); }
        toast(editing ? 'Saved' : 'Uploaded'); editing = null; render();
      } catch (err) { toast(err.message, true); btn.disabled = false; } };
  }

  // ---------- events ----------
  async function eventsTab(body) {
    const list = await api('/admin/events'); const ev = list.find(x => x.id === editing) || { title: '', startsAt: '', endsAt: '', location: '', onlineUrl: '', description: '', published: true };
    body.innerHTML = `<h3>${editing ? 'Edit event' : 'New event'}</h3><form id="ev-form" class="side-card stack"><input class="input" id="e-title" placeholder="Event title" required value="${esc(ev.title)}" maxlength="200">
      <div class="form-grid"><label style="font-size:13px;color:var(--muted)">Starts<input class="input" type="datetime-local" id="e-start" required value="${esc(ev.startsAt)}"></label><label style="font-size:13px;color:var(--muted)">Ends (optional)<input class="input" type="datetime-local" id="e-end" value="${esc(ev.endsAt)}"></label></div>
      <div class="form-grid"><input class="input" id="e-loc" placeholder="Location (or Online)" value="${esc(ev.location)}"><input class="input" id="e-url" placeholder="Online link (https://…)" value="${esc(ev.onlineUrl)}"></div>
      <textarea class="input" id="e-desc" placeholder="Description" maxlength="2000">${esc(ev.description)}</textarea><label><input type="checkbox" id="e-pub" ${ev.published ? 'checked' : ''}> Published</label>
      <div class="row"><button class="btn btn-primary" type="submit">${editing ? 'Save' : 'Create event'}</button>${editing ? '<button class="btn btn-ghost" type="button" id="cancel">Cancel</button>' : ''}</div></form>
      <h3>All events</h3>` + table(['Event', 'When', 'RSVPs', 'Status', ''], list.map(x => `<tr><td>${esc(x.title)}</td><td>${esc(x.startsAt.replace('T', ' '))}</td><td>${x.rsvps}</td><td>${x.published ? 'Published' : 'Hidden'}</td>
        <td><button class="btn btn-ghost" data-rsvps="${x.id}">RSVPs</button> <button class="btn btn-ghost" data-edit="${x.id}">Edit</button> <button class="btn btn-ghost danger" data-del="${x.id}">Delete</button></td></tr>`)) + '<div id="rsvp-box"></div>';
    $$('[data-edit]', body).forEach(b => b.onclick = () => { editing = +b.dataset.edit; render(); });
    $$('[data-del]', body).forEach(b => b.onclick = () => { if (confirm('Delete this event?')) act(() => api('/admin/events/' + b.dataset.del, { method: 'DELETE' }), 'Deleted'); });
    $$('[data-rsvps]', body).forEach(b => b.onclick = async () => { const r = await api(`/admin/events/${b.dataset.rsvps}/rsvps`); $('#rsvp-box').innerHTML = '<h3>RSVPs</h3>' + table(['Name', 'Email', 'When'], r.map(x => `<tr><td>${esc(x.name)}</td><td>${esc(x.email)}</td><td>${fmt(x.created_at)}</td></tr>`), 'No RSVPs yet'); });
    const c = $('#cancel'); if (c) c.onclick = () => { editing = null; render(); };
    $('#ev-form').onsubmit = async e => { e.preventDefault();
      const payload = { title: $('#e-title').value, startsAt: $('#e-start').value, endsAt: $('#e-end').value, location: $('#e-loc').value, onlineUrl: $('#e-url').value, description: $('#e-desc').value, published: $('#e-pub').checked };
      act(() => { const was = editing; editing = null; return api(was ? '/admin/events/' + was : '/admin/events', { method: was ? 'PUT' : 'POST', body: payload }); }, 'Saved'); };
  }

  // ---------- payments ----------
  async function paymentsTab(body) {
    const cfg = await api('/admin/payments/config');
    const subs = ['orders', 'methods', 'plans'].map(s => `<button class="chip${sub === s ? ' on' : ''}" data-sub="${s}">${{ orders: 'Orders', methods: 'Payment methods', plans: 'Plans & prices' }[s]}</button>`).join('');
    const st = (ok, name, env) => `<div>${ok ? '✅' : '❌'} <b>${name}</b>${ok ? '' : ` – add <code>${env}</code> to the .env file and restart`}</div>`;
    body.innerHTML = `<div class="note">${st(cfg.chapaConfigured, 'Chapa (Ethiopia: Telebirr, CBE Birr, banks, cards)', 'CHAPA_SECRET_KEY')}${st(cfg.stripeConfigured, 'Stripe (international cards)', 'STRIPE_SECRET_KEY')}${st(cfg.paypalConfigured, 'PayPal (' + cfg.paypalMode + ' mode)', 'PAYPAL_CLIENT_ID + PAYPAL_CLIENT_SECRET')}</div>
      <label class="side-card row" style="gap:12px;cursor:pointer"><input type="checkbox" id="req-appr" ${cfg.onlineRequiresApproval ? 'checked' : ''}> <span><b>Admin permission for online payments</b><br><small style="color:var(--muted)">When ticked, a payment confirmed by Stripe / PayPal / Chapa does NOT activate the membership until you press Approve in Orders. When off, verified online payments activate automatically.</small></span></label>
      <div class="tabs">${subs}</div><div id="sub-body"></div>`;
    $('#req-appr').onchange = e => act(() => api('/admin/payments/settings', { method: 'PUT', body: { onlineRequiresApproval: e.target.checked } }), e.target.checked ? 'Online payments now need your approval' : 'Online payments activate automatically');
    $$('[data-sub]', body).forEach(b => b.onclick = () => { sub = b.dataset.sub; editing = null; paymentsTab(body); });
    const sb = $('#sub-body'); await ({ orders: ordersSub, methods: methodsSub, plans: plansSub }[sub])(sb);
  }
  async function ordersSub(sb) {
    const list = await api('/admin/orders');
    sb.innerHTML = table(['Order', 'Member', 'Plan / method', 'Amount', 'Transaction ID', 'Status', ''], list.map(o => `<tr><td><b>${esc(o.ref)}</b><br><small>${fmt(o.createdAt)}</small></td><td>${esc(o.member)}<br><small>${esc(o.email)}</small></td><td>${esc(o.plan)}<br><small>${esc(o.method)}</small></td><td>${money(o.amountMinor, o.currency)}</td>
      <td>${esc(o.txRef) || '—'}${o.duplicateTx ? '<br><span class="status failed">duplicate ID!</span>' : ''}${o.hasProof ? `<br><a href="/api/admin/orders/${o.id}/proof" target="_blank" rel="noopener" style="color:var(--accent)">📎 proof</a>` : ''}</td>
      <td><span class="status ${esc(o.status)}">${esc(o.status)}</span>${o.note ? `<br><small>${esc(o.note)}</small>` : ''}</td>
      <td>${o.status !== 'paid' ? `<button class="btn btn-primary" data-ok="${o.id}">Approve</button> <button class="btn btn-ghost danger" data-no="${o.id}">Reject</button>` : '✔'}</td></tr>`), 'No orders yet');
    $$('[data-ok]', sb).forEach(b => b.onclick = () => { if (confirm('Confirm you received this payment? The member will be activated.')) act(() => api(`/admin/orders/${b.dataset.ok}/approve`, { method: 'POST' }), 'Approved – member activated'); });
    $$('[data-no]', sb).forEach(b => b.onclick = () => { const note = prompt('Reason shown to the member (optional):', 'Payment could not be verified'); if (note !== null) act(() => api(`/admin/orders/${b.dataset.no}/reject`, { method: 'POST', body: { note } }), 'Rejected'); });
  }
  async function methodsSub(sb) {
    const list = await api('/admin/payment-methods'); const m = list.find(x => x.id === editing) || { kind: 'telebirr', label: '', accountName: '', accountNumber: '', instructions: '', enabled: true };
    const kinds = ['telebirr', 'bank', 'cbebirr', 'mpesa', 'wire', 'payoneer', 'alipay_qr', 'other', 'card', 'alipay', 'paypal', 'chapa', 'stripe'], onlineK = ['chapa', 'stripe', 'paypal', 'card', 'alipay'];
    sb.innerHTML = `<form id="m-form" class="side-card stack"><h4>${editing ? 'Edit' : 'Add'} payment method</h4>
      <div class="form-grid"><label style="font-size:13px;color:var(--muted)">Type<select class="input" id="m-kind">${kinds.map(k => `<option value="${k}"${m.kind === k ? ' selected' : ''}>${({ card: 'card – Visa / Mastercard (online, Stripe)', alipay: 'alipay (online, Stripe)', paypal: 'paypal (online)', chapa: 'chapa (online, Ethiopia)', stripe: 'stripe (all methods you enabled in Stripe)', wire: 'wire (international bank transfer)', payoneer: 'payoneer (account / payment link)', alipay_qr: 'alipay QR code (manual)' })[k] || k}</option>`).join('')}</select></label>
        <label style="font-size:13px;color:var(--muted)">Label shown to visitors<input class="input" id="m-label" required value="${esc(m.label)}" placeholder="e.g. Telebirr (send to our number)"></label></div>
      <div class="form-grid"><input class="input" id="m-name" placeholder="Account holder name" value="${esc(m.accountName)}"><input class="input" id="m-num" placeholder="Telebirr number / bank account number" value="${esc(m.accountNumber)}"></div>
      <textarea class="input" id="m-ins" placeholder="Instructions shown to the payer" maxlength="500">${esc(m.instructions)}</textarea>
      <div class="side-card stack" style="margin:0"><b>Optional for manual methods (Payoneer, Alipay, PayPal.me, Telebirr …)</b>
        <input class="input" id="m-link" type="url" placeholder="Payment link, e.g. your Payoneer / PayPal.me page (opens in a new tab)" value="${esc(m.payLink || '')}">
        <label style="font-size:13px;color:var(--muted)">QR code image (the payer scans it)${m.qrUrl ? `<br><img src="${esc(m.qrUrl)}" alt="" style="width:90px;background:#fff;border-radius:8px;padding:4px;margin:6px 0"> <button class="btn btn-ghost danger" type="button" id="qr-del">Remove QR</button>` : ''}<input class="input" type="file" id="m-qr" accept=".jpg,.jpeg,.png,.webp,.gif"></label></div>
      <div class="row"><b>Accepted currencies:</b>${['ETB', 'USD', 'EUR'].map(c => `<label><input type="checkbox" class="m-cur" value="${c}" ${(m.currencies || ['ETB']).includes(c) ? 'checked' : ''}> ${c}</label>`).join('')}</div>
      <label><input type="checkbox" id="m-en" ${m.enabled ? 'checked' : ''}> Enabled – you decide which methods visitors can use (manual methods also need an account number; Stripe/PayPal/Chapa need their keys)</label>
      <div class="row"><button class="btn btn-primary" type="submit">Save</button>${editing ? '<button class="btn btn-ghost" type="button" id="cancel">Cancel</button>' : ''}</div></form>` +
      table(['Method', 'Currencies', 'Details', 'Enabled', 'Visible to visitors', ''], list.map(x => `<tr><td>${esc(x.label)}<br><small>${esc(x.kind)}</small></td><td>${esc((x.currencies || []).join(', '))}</td><td>${x.online ? 'Online checkout' : esc(x.accountName) + '<br>' + esc(x.accountNumber)}</td><td>${x.enabled ? 'Yes' : 'No'}</td><td>${x.available ? '✅' : '—'}</td>
        <td><button class="btn btn-ghost" data-edit="${x.id}">Edit</button> <button class="btn btn-ghost danger" data-del="${x.id}">Delete</button></td></tr>`));
    $$('[data-edit]', sb).forEach(b => b.onclick = () => { editing = +b.dataset.edit; render(); });
    $$('[data-del]', sb).forEach(b => b.onclick = () => { if (confirm('Delete this payment method?')) act(() => api('/admin/payment-methods/' + b.dataset.del, { method: 'DELETE' }), 'Deleted'); });
    const c = $('#cancel', sb); if (c) c.onclick = () => { editing = null; render(); };
    const qd = $('#qr-del'); if (qd) qd.onclick = () => act(() => api(`/admin/payment-methods/${editing}/qr`, { method: 'DELETE' }), 'QR removed');
    $('#m-form').onsubmit = e => { e.preventDefault(); const was = editing; editing = null; const qf = $('#m-qr').files[0];
      act(async () => { const r = await api(was ? '/admin/payment-methods/' + was : '/admin/payment-methods', { method: was ? 'PUT' : 'POST', body: { kind: $('#m-kind').value, label: $('#m-label').value, accountName: $('#m-name').value, accountNumber: $('#m-num').value, instructions: $('#m-ins').value, enabled: $('#m-en').checked, payLink: $('#m-link').value, currencies: $$('.m-cur:checked').map(x => x.value) } });
        if (qf) { const fd = new FormData(); fd.append('file', qf); await api(`/admin/payment-methods/${was || r.id}/qr`, { method: 'POST', body: fd }); } }, 'Saved'); };
  }
  async function plansSub(sb) {
    const list = await api('/admin/plans');
    sb.innerHTML = '<p style="color:var(--muted)">Set a price for each currency (0 = not offered in that currency). “Custom” plans are not sold online – visitors are sent to the Contact page.</p>' + list.map(p => `<form class="side-card stack plan-form" data-key="${esc(p.key)}">
      <div class="form-grid"><input class="input" name="name" value="${esc(p.name)}" required><input class="input" name="periodDays" type="number" min="0" value="${p.periodDays}" placeholder="Days of access per payment"></div>
      <div class="form-grid"><label style="font-size:12px;color:var(--muted)">ETB<input class="input" name="priceEtb" type="number" min="0" value="${p.priceEtb}" ${p.key === 'reader' ? 'readonly' : ''}></label><label style="font-size:12px;color:var(--muted)">USD (0 = not offered)<input class="input" name="priceUsd" type="number" min="0" value="${p.priceUsd}" ${p.key === 'reader' ? 'readonly' : ''}></label></div>
      <div class="form-grid"><label style="font-size:12px;color:var(--muted)">EUR (0 = not offered)<input class="input" name="priceEur" type="number" min="0" value="${p.priceEur}" ${p.key === 'reader' ? 'readonly' : ''}></label><label style="font-size:12px;color:var(--muted)">Benefits<input class="input" name="benefits" value="${esc(p.benefits)}"></label></div>
      <div class="row"><label><input type="checkbox" name="custom" ${p.custom ? 'checked' : ''}> Custom (contact us)</label><label><input type="checkbox" name="active" ${p.active ? 'checked' : ''}> Active</label><button class="btn btn-primary" type="submit" style="margin-left:auto">Save <b>${esc(p.key)}</b></button></div></form>`).join('') +
      `<form id="np-form" class="side-card stack"><h4>Add a plan</h4><div class="form-grid"><input class="input" id="np-key" placeholder="key (e.g. student)" required><input class="input" id="np-name" placeholder="Name" required></div>
      <div class="form-grid"><input class="input" id="np-price" type="number" min="0" placeholder="Price ETB" required><input class="input" id="np-usd" type="number" min="0" placeholder="Price USD"></div><div class="form-grid"><input class="input" id="np-eur" type="number" min="0" placeholder="Price EUR"><input class="input" id="np-days" type="number" min="0" value="30"></div><input class="input" id="np-ben" placeholder="Benefits"><button class="btn btn-primary" type="submit" style="align-self:flex-start">Add plan</button></form>`;
    $$('.plan-form', sb).forEach(f => f.onsubmit = e => { e.preventDefault(); const g = n => f.elements[n];
      act(() => api('/admin/plans/' + f.dataset.key, { method: 'PUT', body: { name: g('name').value, priceEtb: +g('priceEtb').value, priceUsd: +g('priceUsd').value, priceEur: +g('priceEur').value, periodDays: +g('periodDays').value, benefits: g('benefits').value, custom: g('custom').checked, active: g('active').checked } }), 'Plan saved'); });
    $('#np-form').onsubmit = e => { e.preventDefault(); act(() => api('/admin/plans', { method: 'POST', body: { key: $('#np-key').value, name: $('#np-name').value, priceEtb: +$('#np-price').value, priceUsd: +($('#np-usd').value || 0), priceEur: +($('#np-eur').value || 0), periodDays: +$('#np-days').value, benefits: $('#np-ben').value } }), 'Plan added'); };
  }

  // ---------- people ----------
  async function peopleTab(body) {
    const [subs, mem] = await Promise.all([api('/admin/subscribers'), api('/admin/members')]);
    body.innerHTML = `<div class="row"><h3 style="margin:0">Members (${mem.length})</h3><a class="btn btn-ghost" href="/api/admin/members?format=csv">Export CSV</a></div><div style="margin:10px 0 26px">` +
      table(['Name', 'Email / affiliation', 'Plan', 'Status', 'Expires', 'Access code', ''], mem.map(m => `<tr><td>${esc(m.name)}</td><td>${esc(m.email)}<br><small>${esc(m.affiliation)}</small></td><td>${esc(m.plan)}</td><td><span class="status ${esc(m.status)}">${esc(m.status)}</span></td><td>${m.expires_at ? fmt(m.expires_at) : '—'}</td><td><code>${esc(m.access_code)}</code></td>
        <td><button class="btn btn-ghost" data-ext="${m.id}">+30 days</button> <button class="btn btn-ghost" data-st="${m.id}" data-v="${m.status === 'active' ? 'inactive' : 'active'}">${m.status === 'active' ? 'Deactivate' : 'Activate'}</button> <button class="btn btn-ghost" data-code="${m.id}">New code</button></td></tr>`)) + `</div>
      <div class="row"><h3 style="margin:0">Subscribers (${subs.length})</h3><a class="btn btn-ghost" href="/api/admin/subscribers?format=csv">Export CSV</a></div><div style="margin-top:10px">` + table(['Email', 'Joined'], subs.map(s => `<tr><td>${esc(s.email)}</td><td>${fmt(s.created_at)}</td></tr>`)) + '</div>';
    $$('[data-ext]', body).forEach(b => b.onclick = () => act(() => api('/admin/members/' + b.dataset.ext, { method: 'PUT', body: { extendDays: 30 } }), 'Extended by 30 days'));
    $$('[data-st]', body).forEach(b => b.onclick = () => act(() => api('/admin/members/' + b.dataset.st, { method: 'PUT', body: { status: b.dataset.v } }), 'Updated'));
    $$('[data-code]', body).forEach(b => b.onclick = () => { if (confirm('Generate a new access code? The old one stops working.')) act(() => api('/admin/members/' + b.dataset.code, { method: 'PUT', body: { newCode: true } }), 'New code generated'); });
  }

  // ---------- messages / comments ----------
  async function messagesTab(body) {
    const list = await api('/admin/messages');
    body.innerHTML = table(['From', 'Message', 'Date', ''], list.map(m => `<tr style="${m.read ? 'opacity:.7' : ''}"><td>${m.read ? '' : '● '}<b>${esc(m.name)}</b><br><a href="mailto:${esc(m.email)}" style="color:var(--accent)">${esc(m.email)}</a></td><td><b>${esc(m.subject)}</b><br>${esc(m.body)}</td><td>${fmt(m.createdAt)}</td>
      <td>${m.read ? '' : `<button class="btn btn-ghost" data-read="${m.id}">Mark read</button> `}<button class="btn btn-ghost danger" data-del="${m.id}">Delete</button></td></tr>`), 'No messages');
    $$('[data-read]', body).forEach(b => b.onclick = () => act(() => api('/admin/messages/' + b.dataset.read, { method: 'PUT', body: {} })));
    $$('[data-del]', body).forEach(b => b.onclick = () => { if (confirm('Delete this message?')) act(() => api('/admin/messages/' + b.dataset.del, { method: 'DELETE' }), 'Deleted'); });
  }
  async function commentsTab(body) {
    const list = await api('/admin/comments');
    body.innerHTML = table(['Who', 'Comment', 'Article', 'Date', ''], list.map(c => `<tr><td>${esc(c.name)}<br><small>${esc(c.email)}</small></td><td>${esc(c.body)}</td><td>${esc(c.article)}</td><td>${fmt(c.createdAt)}</td><td><button class="btn btn-ghost danger" data-c="${c.id}">Delete</button></td></tr>`), 'No comments');
    $$('[data-c]', body).forEach(b => b.onclick = () => { if (confirm('Delete this comment?')) act(() => api('/admin/comments/' + b.dataset.c, { method: 'DELETE' }), 'Deleted'); });
  }

  // ---------- site pages & settings ----------
  async function siteTab(body) {
    const s = await api('/site'); const L = [['', 'English'], ['_am', 'አማርኛ'], ['_om', 'Afaan Oromoo'], ['_ar', 'العربية']];
    body.innerHTML = `<form id="site-form" class="stack"><h3 style="margin:0">Top banner &amp; About page (one version per language)</h3><p style="color:var(--muted);margin:0">If a language is left empty, visitors see the English text.</p>
      ${L.map(([sfx, name]) => `<div class="side-card stack"><b>${name}</b><input class="input" data-k="announcement${sfx}" placeholder="Announcement banner (empty = hidden)" value="${esc(s['announcement' + sfx] || '')}" maxlength="300">
        <textarea class="input" data-k="about${sfx}" style="min-height:170px" placeholder="About text (blank line = paragraph, ## heading, > quote, - list)">${esc(s['about' + sfx] || '')}</textarea></div>`).join('')}
      <h3 style="margin:10px 0 0">Contact details</h3><div class="form-grid"><input class="input" data-k="contact_email" placeholder="Public email" value="${esc(s.contact_email)}"><input class="input" data-k="contact_phone" placeholder="Phone" value="${esc(s.contact_phone)}"></div>
      <div class="form-grid"><input class="input" data-k="contact_address" placeholder="Address" value="${esc(s.contact_address)}"><input class="input" data-k="telegram" placeholder="Telegram link (https://t.me/…)" value="${esc(s.telegram)}"></div>
      <button class="btn btn-primary" type="submit" style="align-self:flex-start">Save site pages</button></form>`;
    $('#site-form').onsubmit = e => { e.preventDefault(); const o = {}; $$('[data-k]', e.target).forEach(x => { o[x.dataset.k] = x.value; }); act(() => api('/admin/site', { method: 'PUT', body: o }), 'Saved'); };
  }

  // ---------- home slider ----------
  async function slidesTab(body) {
    const [list, site] = await Promise.all([api('/admin/slides'), api('/site')]); const sl = list.find(x => x.id === editing) || { title: '', subtitle: '', link: '#/membership', cta: '', imageUrl: '', active: true, sort: list.length + 1 };
    let H = +site.slider_height || 520;
    body.innerHTML = `<div class="side-card stack"><h4 style="margin:0">Slider size &amp; speed</h4><p style="color:var(--muted);margin:0">Make the home slider bigger or smaller (240–800 px; on small phones it shrinks automatically).</p>
      <div class="row"><button class="btn btn-ghost" type="button" id="sz-dn">− Smaller</button><input type="range" id="sz-range" min="240" max="800" step="10" value="${H}" style="flex:1;min-width:140px"><button class="btn btn-ghost" type="button" id="sz-up">+ Larger</button><b id="sz-val" style="min-width:64px">${H} px</b></div>
      <div class="row">${[['Compact', 320], ['Standard', 480], ['Tall', 640], ['Large', 760]].map(([n, v]) => `<button class="chip" type="button" data-sz="${v}">${n} (${v})</button>`).join('')}
        <label style="margin-inline-start:auto">Change slide every <select class="input" id="sz-speed" style="width:auto;display:inline-block">${[3, 4, 5, 6, 8, 10, 12, 15].map(v => `<option value="${v}"${(+site.slider_speed || 6) === v ? ' selected' : ''}>${v} s</option>`).join('')}</select></label></div>
      <div id="sz-prev" style="border-radius:12px;background:linear-gradient(135deg,#7c2d12,#f97316);display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700"></div>
      <button class="btn btn-primary" type="button" id="sz-save" style="align-self:flex-start">Save slider size</button></div>
      <p style="color:var(--muted)">These slides rotate at the top of the home page. Upload a wide photo (about 1600×900). Without an image a coloured pattern is used.</p>
      <form id="sl-form" class="side-card stack"><h4 style="margin:0">${editing ? 'Edit slide' : 'Add a slide'}</h4>
        <input class="input" id="sl-title" placeholder="Headline" required maxlength="140" value="${esc(sl.title)}"><input class="input" id="sl-sub" placeholder="Sub-headline" maxlength="260" value="${esc(sl.subtitle)}">
        <div class="form-grid"><input class="input" id="sl-cta" placeholder="Button text (e.g. See plans)" maxlength="40" value="${esc(sl.cta)}"><input class="input" id="sl-link" placeholder="Button link: #/membership, #/library, #/events, https://…" value="${esc(sl.link)}"></div>
        <label style="font-size:13px;color:var(--muted)">Image (JPG/PNG/WebP, max 6 MB)${sl.imageUrl ? `<br><img src="${esc(sl.imageUrl)}" alt="" style="max-height:80px;border-radius:8px;margin:6px 0">` : ''}<input class="input" type="file" id="sl-file" accept=".jpg,.jpeg,.png,.webp,.gif"></label>
        <div class="row"><label>Order <input class="input" id="sl-sort" type="number" style="width:80px" value="${sl.sort}"></label><label><input type="checkbox" id="sl-act" ${sl.active ? 'checked' : ''}> Active</label>${editing && sl.imageUrl ? '<label><input type="checkbox" id="sl-rm"> Remove image</label>' : ''}</div>
        <div class="row"><button class="btn btn-primary" type="submit">${editing ? 'Save' : 'Add slide'}</button>${editing ? '<button class="btn btn-ghost" type="button" id="cancel">Cancel</button>' : ''}</div></form>` +
      table(['Preview', 'Slide', 'Link', 'Active', ''], list.map(x => `<tr><td>${x.imageUrl ? `<img src="${esc(x.imageUrl)}" alt="" style="width:100px;height:56px;object-fit:cover;border-radius:8px">` : '—'}</td><td><b>${esc(x.title)}</b><br><small>${esc(x.subtitle)}</small></td><td>${esc(x.link)}</td><td>${x.active ? 'Yes' : 'No'}</td>
        <td><button class="btn btn-ghost" data-edit="${x.id}">Edit</button> <button class="btn btn-ghost danger" data-del="${x.id}">Delete</button></td></tr>`));
    const setH = v => { H = Math.max(240, Math.min(800, v)); $('#sz-range').value = H; $('#sz-val').textContent = H + ' px'; $('#sz-prev').style.height = Math.round(H * 0.32) + 'px'; $('#sz-prev').textContent = 'Home slider · ' + H + ' px'; };
    setH(H); $('#sz-range').oninput = e => setH(+e.target.value); $('#sz-dn').onclick = () => setH(H - 40); $('#sz-up').onclick = () => setH(H + 40);
    $$('[data-sz]', body).forEach(b => b.onclick = () => setH(+b.dataset.sz));
    $('#sz-save').onclick = () => act(() => api('/admin/site', { method: 'PUT', body: { slider_height: H, slider_speed: +$('#sz-speed').value } }), 'Slider size saved');
    $$('[data-edit]', body).forEach(b => b.onclick = () => { editing = +b.dataset.edit; render(); });
    $$('[data-del]', body).forEach(b => b.onclick = () => { if (confirm('Delete this slide?')) act(() => api('/admin/slides/' + b.dataset.del, { method: 'DELETE' }), 'Deleted'); });
    const c = $('#cancel', body); if (c) c.onclick = () => { editing = null; render(); };
    $('#sl-form').onsubmit = async e => { e.preventDefault(); const fd = new FormData();
      fd.append('title', $('#sl-title').value); fd.append('subtitle', $('#sl-sub').value); fd.append('cta', $('#sl-cta').value); fd.append('link', $('#sl-link').value);
      fd.append('sort', $('#sl-sort').value); fd.append('active', $('#sl-act').checked ? '1' : '0'); const f = $('#sl-file').files[0]; if (f) fd.append('file', f); const rm = $('#sl-rm'); if (rm && rm.checked) fd.append('remove_image', '1');
      const was = editing; editing = null; act(() => api(was ? '/admin/slides/' + was : '/admin/slides', { method: was ? 'PUT' : 'POST', body: fd }), 'Saved'); };
  }
  function settingsTab(body) {
    body.innerHTML = `<h3>Change admin password</h3><form id="pw-form" class="stack" style="max-width:380px"><input class="input" type="password" id="old" placeholder="Current password" required autocomplete="current-password">
      <input class="input" type="password" id="new" placeholder="New password (min 8 characters)" minlength="8" required autocomplete="new-password"><button class="btn btn-primary" type="submit" style="align-self:flex-start">Update password</button></form>
      <h3 style="margin-top:30px">Backup &amp; restore articles</h3><div class="row"><a class="btn btn-ghost" href="/api/admin/backup">⬇ Download backup (JSON)</a>
      <label class="btn btn-ghost">⬆ Import backup<input type="file" id="imp" accept=".json,application/json" class="hidden"></label></div>`;
    $('#pw-form').onsubmit = async e => { e.preventDefault(); try { await api('/admin/password', { method: 'POST', body: { old: $('#old').value, new: $('#new').value } }); toast('Password updated'); e.target.reset(); } catch (err) { toast(err.message, true); } };
    $('#imp').onchange = async e => { const f = e.target.files[0]; if (!f) return; try { const d = await api('/admin/import', { method: 'POST', body: JSON.parse(await f.text()) }); toast(`Imported ${d.added} new article(s)`); } catch (err) { toast(err.message || 'Invalid file', true); } };
  }

  boot();
})();
