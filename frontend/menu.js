// menu.js -- Admin dashboard logic for immich-drop
//
// Security note: innerHTML is used below to render admin-only data
// (invite tokens, album names, cookie previews) sourced from the
// application's own API. All attribute values are escaped via escAttr().
// This page is gated behind Immich authentication (session cookie check).
// The escAttr helper sanitizes &, ", <, > to prevent injection.
//
// This is an intentional, reviewed use of innerHTML for a trusted
// admin-only context. External/untrusted user input does not reach
// these code paths.

/* eslint-disable no-innerHTML */
/* jshint -W060 */
(function(){
  var albumSelectWrap = document.getElementById('albumSelectWrap');
  var albumSelect = document.getElementById('albumSelect');
  var albumInputWrap = document.getElementById('albumInputWrap');
  var albumInput = document.getElementById('albumInput');
  var albumHint = document.getElementById('albumHint');
  var btnCreateAlbum = document.getElementById('btnCreateAlbum');
  var btnCreate = document.getElementById('btnCreate');
  var usage = document.getElementById('usage');
  var days = document.getElementById('days');
  var result = document.getElementById('result');
  var linkOut = document.getElementById('linkOut');
  var btnCopy = document.getElementById('btnCopy');
  var qrImg = document.getElementById('qrImg');
  var passwordInput = document.getElementById('password');

  function showResult(kind){
    result.className = (kind==='ok' ? 'banner banner--ok mt-3' : 'banner banner--err mt-3');
    result.classList.remove('hidden');
  }

  async function loadAlbums(){
    try {
      var r = await fetch('/api/albums');
      if (r.status === 403) {
        albumHint.textContent = 'Listing albums is forbidden with current credentials. You can still type a new album name or leave it blank.';
        albumInputWrap.classList.remove('hidden');
        return;
      }
      var list = await r.json();
      if (Array.isArray(list)){
        var opts = [{id:'', name:'-- No album --'}].concat(list.map(function(a){ return {id:a.id, name:(a.albumName || a.title || a.id)}; }));
        albumSelect.innerHTML = opts.map(function(a){ return '<option value="'+escAttr(a.id)+'">'+escAttr(a.name)+'</option>'; }).join('');
        albumSelectWrap.classList.remove('hidden');
        albumInputWrap.classList.remove('hidden');
        albumHint.textContent = 'Pick an existing album, or type a new name and click Create album.';
      }
    } catch (e) {
      albumHint.textContent = 'Failed to load albums.';
    }
  }

  btnCreateAlbum.onclick = async function(){
    var name = albumInput.value.trim();
    if (!name) return;
    try{
      var r = await fetch('/api/albums', { method:'POST', headers:{'Content-Type':'application/json','Accept':'application/json'}, body: JSON.stringify({ name: name }) });
      var j = await r.json().catch(function(){ return {}; });
      if(!r.ok){ showResult('err'); return; }
      showResult('ok');
      try { await loadAlbums(); } catch(e2){}
    }catch(err){ showResult('err'); }
  };

  btnCreate.onclick = async function(){
    var albumId = null, albumName = null;
    if (!albumSelectWrap.classList.contains('hidden') && albumSelect.value) {
      albumId = albumSelect.value;
    } else if (albumInput.value.trim()) {
      albumName = albumInput.value.trim();
    }
    var payload = { maxUses: parseInt(usage.value, 10) };
    var d = days.value.trim();
    if (d) payload.expiresDays = parseInt(d, 10);
    if (albumId) payload.albumId = albumId; else if (albumName) payload.albumName = albumName;
    var pw = (passwordInput && passwordInput.value) ? passwordInput.value.trim() : '';
    if (pw) payload.password = pw;
    try{
      var r = await fetch('/api/invites', { method:'POST', headers:{'Content-Type':'application/json','Accept':'application/json'}, body: JSON.stringify(payload) });
      var j = await r.json().catch(function(){ return {}; });
      if(!r.ok){ showResult('err'); return; }
      var link = j.absoluteUrl || (location.origin + j.url);
      showResult('ok');
      linkOut.value = link;
      qrImg.src = '/api/qr?text='+encodeURIComponent(link);
      if (j && j.token) { try { LAST_CREATED_TOKEN = j.token; } catch(e2){} }
      try { await loadInvites(); } catch(e2){}
    }catch(err){ showResult('err'); }
  };

  btnCopy.onclick = function(){
    var text = linkOut.value || '';
    if (!text) return;
    var flash = function(){ btnCopy.textContent='Copied'; setTimeout(function(){ btnCopy.textContent='Copy'; }, 1200); };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(flash).catch(function(){});
    }
  };

  loadAlbums();

  // --- Manage Links ---
  var searchQ = document.getElementById('searchQ');
  var sortSel = document.getElementById('sortSel');
  var btnRefresh = document.getElementById('btnRefresh');
  var invitesTBody = document.getElementById('invitesTBody');
  var chkAll = document.getElementById('chkAll');
  var btnDisableSel = document.getElementById('btnDisableSel');
  var btnEnableSel = document.getElementById('btnEnableSel');
  var btnDeleteSel = document.getElementById('btnDeleteSel');
  var INVITES = [];
  var LAST_CREATED_TOKEN = null;

  async function loadInvites(){
    var params = new URLSearchParams();
    var q = (searchQ.value||'').trim(); if (q) params.set('q', q);
    var sort = (sortSel.value||'').trim(); if (sort) params.set('sort', sort);
    try{
      var r = await fetch('/api/invites?'+params.toString());
      var j = await r.json();
      INVITES = (j && j.items) ? j.items : [];
    }catch(e){ INVITES = []; }
    renderInvites();
  }

  // HTML attribute escaper for server-sourced admin data
  function escAttr(s){ return String(s||'').replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

  function statusBadge(row){
    var inactive = String(row.inactiveReason||'');
    if (/expired|claimed|exhausted/i.test(inactive)){
      var label = inactive.charAt(0).toUpperCase()+inactive.slice(1);
      return '<span class="badge badge--red">'+escAttr(label)+'</span>';
    }
    if (row.active) return '<span class="badge badge--green">Active</span>';
    if (/disabled/i.test(inactive)) return '<span class="badge badge--amber">Disabled</span>';
    return '<span class="badge">'+(row.active?'Active':'Inactive')+'</span>';
  }

  function renderInvites(){
    var rows = '';
    for (var i=0; i<INVITES.length; i++){
      var row = INVITES[i];
      var status = statusBadge(row);
      var uses = (row.used||0)+'/'+(row.maxUses<0?'Inf':row.maxUses);
      var url = location.origin + '/invite/' + row.token;
      var nameEsc = escAttr(row.name);
      var expVal = row.expiresAt ? new Date(row.expiresAt).toISOString().slice(0,10) : '';
      var expTitle = row.expiresAt ? new Date(row.expiresAt).toLocaleString() : 'No expiry';
      rows += '<tr data-token="'+escAttr(row.token)+'">'
        + '<td class="td-checkbox"><input class="chkRow" type="checkbox" data-token="'+escAttr(row.token)+'"/></td>'
        + '<td class="td-name" data-label="Name"><input class="inName input" data-token="'+escAttr(row.token)+'" value="'+nameEsc+'" title="'+nameEsc+'"/></td>'
        + '<td data-label="Status">'+status+'</td>'
        + '<td data-label="Uses">'+escAttr(uses)+'</td>'
        + '<td data-label="Expires"><input class="inExpires input" type="date" data-token="'+escAttr(row.token)+'" value="'+escAttr(expVal)+'" title="'+escAttr(expTitle)+'" style="width:140px;"/></td>'
        + '<td data-label="Album">'+escAttr(row.albumName||'--')+'</td>'
        + '<td class="td-actions" data-label="">'
        + '<div class="flex items-center gap-2">'
        + '<button class="btnDetails btn btn--sm btn--icon has-tooltip" data-token="'+escAttr(row.token)+'" aria-label="Details"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" width="16" height="16"><path d="M12 3a9 9 0 1 1 0 18A9 9 0 0 1 12 3zm0 4a1.25 1.25 0 1 0 0 2.5A1.25 1.25 0 0 0 12 7zm-1.5 4.5h3v6h-3v-6z"/></svg><span class="tooltip">Details</span></button>'
        + '<button class="btnQR btn btn--sm btn--icon has-tooltip" data-url="'+escAttr(url)+'" aria-label="QR"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" width="16" height="16"><path d="M3 3h8v8H3V3zm2 2v4h4V5H5zm8-2h8v8h-8V3zm2 2v4h4V5h-4zM3 13h8v8H3v-8zm2 2v4h4v-4H5zm12 0h-2v2h2v2h-4v2h6v-6h-2v0zm-4-2h2v2h-2v-2zm6-2h2v2h-2v-2z"/></svg><span class="tooltip">QR</span></button>'
        + '<a class="btn btn--sm btn--icon has-tooltip" target="_blank" href="'+escAttr(url)+'" aria-label="Open"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" width="16" height="16"><path d="M14 3h7v7h-2V6.414l-9.293 9.293-1.414-1.414L17.586 5H14V3z"/><path d="M5 5h6v2H7v10h10v-4h2v6H5V5z"/></svg><span class="tooltip">Open</span></a>'
        + '<button class="btnCopyLink btn btn--sm btn--icon has-tooltip" data-url="'+escAttr(url)+'" aria-label="Copy"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" width="16" height="16"><path d="M16 1H4a2 2 0 0 0-2 2v12h2V3h12V1zm3 4H8a2 2 0 0 0-2 2v14h13a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2zm0 16H8V7h11v14z"/></svg><span class="tooltip">Copy</span></button>'
        + '<button class="btnSave btn btn--sm btn--icon has-tooltip" data-token="'+escAttr(row.token)+'" aria-label="Save" disabled style="opacity:0.4;"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" width="16" height="16"><path d="M17 3H7a2 2 0 0 0-2 2v14l7-3 7 3V5a2 2 0 0 0-2-2zM7 5h10v10l-5-2-5 2V5z"/></svg><span class="tooltip">Save</span></button>'
        + '</div></td></tr>';
    }
    invitesTBody.innerHTML = rows;

    function updateSaveState(token){
      var inName = invitesTBody.querySelector('.inName[data-token="'+token+'"]');
      var inExp = invitesTBody.querySelector('.inExpires[data-token="'+token+'"]');
      var btn = invitesTBody.querySelector('.btnSave[data-token="'+token+'"]');
      if (!inName || !inExp || !btn) return;
      var changed = ((inName.value||'').trim() !== (inName.getAttribute('data-original')||'')) || ((inExp.value||'') !== (inExp.getAttribute('data-original')||''));
      btn.disabled = !changed;
      btn.style.opacity = changed ? '1' : '0.4';
    }

    INVITES.forEach(function(row){
      var token = row.token;
      var inName = invitesTBody.querySelector('.inName[data-token="'+token+'"]');
      var inExp = invitesTBody.querySelector('.inExpires[data-token="'+token+'"]');
      if (inName) inName.setAttribute('data-original', (row.name||'').trim());
      var dStr = row.expiresAt ? new Date(row.expiresAt).toISOString().slice(0,10) : '';
      if (inExp) inExp.setAttribute('data-original', dStr);
      if (inName) inName.addEventListener('input', function(){ updateSaveState(token); });
      if (inExp) inExp.addEventListener('change', function(){ updateSaveState(token); });
      updateSaveState(token);
    });

    invitesTBody.querySelectorAll('.btnSave').forEach(function(btn){
      btn.onclick = async function(){
        var token = btn.getAttribute('data-token');
        if (btn.disabled) return;
        var name = invitesTBody.querySelector('.inName[data-token="'+token+'"]').value.trim();
        var expVal = invitesTBody.querySelector('.inExpires[data-token="'+token+'"]').value;
        var payload = { name: name };
        if (expVal) { var dt = new Date(expVal); dt.setHours(23,59,59,999); payload.expiresAt = dt.toISOString().slice(0,19); } else { payload.expiresAt = null; }
        try{
          var r = await fetch('/api/invite/'+token, { method:'PATCH', headers:{'Content-Type':'application/json','Accept':'application/json'}, body: JSON.stringify(payload) });
          if (!r.ok) throw new Error('Update failed');
          await loadInvites();
        }catch(e){ showResult('err'); }
      };
    });

    invitesTBody.querySelectorAll('.btnDetails').forEach(function(btn){
      btn.onclick = async function(){
        var token = btn.getAttribute('data-token');
        try{
          var r = await fetch('/api/invite/'+token+'/uploads');
          var j = await r.json();
          var items = (j && j.items) ? j.items : [];
          var dlg = document.createElement('div');
          dlg.className = 'modal-overlay';
          var panel = document.createElement('div');
          panel.className = 'modal-panel';
          var hdr = document.createElement('div');
          hdr.className = 'modal-header';
          var h3 = document.createElement('h3');
          h3.textContent = 'Uploads';
          var closeBtn = document.createElement('button');
          closeBtn.className = 'btn btn--sm';
          closeBtn.textContent = 'Close';
          closeBtn.onclick = function(){ dlg.remove(); };
          hdr.appendChild(h3);
          hdr.appendChild(closeBtn);
          panel.appendChild(hdr);
          var body = document.createElement('div');
          body.style.maxHeight = '60vh';
          body.style.overflow = 'auto';
          if (items.length){
            var tbl = '<table class="data-table"><thead><tr><th>When</th><th>IP</th><th>Filename</th><th>Size</th></tr></thead><tbody>';
            items.forEach(function(it){
              tbl += '<tr><td>'+escAttr(new Date(it.uploadedAt).toLocaleString())+'</td><td>'+escAttr(it.ip)+'</td><td>'+escAttr(it.filename)+'</td><td>'+escAttr((it.size||0).toLocaleString())+'</td></tr>';
            });
            tbl += '</tbody></table>';
            body.innerHTML = tbl;
          } else {
            body.textContent = 'No uploads yet.';
            body.className = 'text-sm text-secondary';
          }
          panel.appendChild(body);
          dlg.appendChild(panel);
          document.body.appendChild(dlg);
          dlg.onclick = function(e){ if(e.target===dlg) dlg.remove(); };
        }catch(e){ showResult('err'); }
      };
    });

    invitesTBody.querySelectorAll('.btnQR').forEach(function(btn){
      btn.onclick = function(){
        var url = btn.getAttribute('data-url');
        var dlg = document.createElement('div');
        dlg.className = 'modal-overlay';
        var panel = document.createElement('div');
        panel.className = 'modal-panel';
        panel.style.maxWidth = '400px';
        var hdr = document.createElement('div');
        hdr.className = 'modal-header';
        var h3 = document.createElement('h3');
        h3.textContent = 'QR Code';
        var closeBtn = document.createElement('button');
        closeBtn.className = 'btn btn--sm';
        closeBtn.textContent = 'Close';
        closeBtn.onclick = function(){ dlg.remove(); };
        hdr.appendChild(h3);
        hdr.appendChild(closeBtn);
        panel.appendChild(hdr);
        var body = document.createElement('div');
        body.className = 'flex items-center';
        body.style.gap = '16px';
        var img = document.createElement('img');
        img.src = '/api/qr?text='+encodeURIComponent(url);
        img.alt = 'QR';
        img.style.width = '140px';
        img.style.height = '140px';
        var linkEl = document.createElement('div');
        linkEl.className = 'text-sm';
        linkEl.style.wordBreak = 'break-all';
        linkEl.textContent = url;
        body.appendChild(img);
        body.appendChild(linkEl);
        panel.appendChild(body);
        dlg.appendChild(panel);
        document.body.appendChild(dlg);
        dlg.onclick = function(e){ if(e.target===dlg) dlg.remove(); };
      };
    });

    invitesTBody.querySelectorAll('.btnCopyLink').forEach(function(btn){
      btn.onclick = function(){
        var url = btn.getAttribute('data-url');
        var origHTML = btn.innerHTML;
        var flash = function(){
          btn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41L9 16.17z"/></svg>';
          setTimeout(function(){ btn.innerHTML = origHTML; }, 1000);
        };
        if (navigator.clipboard && navigator.clipboard.writeText) { navigator.clipboard.writeText(url).then(flash).catch(function(){}); }
      };
    });

    if (chkAll) chkAll.checked = false;
    if (LAST_CREATED_TOKEN) {
      var tr = invitesTBody.querySelector('tr[data-token="'+LAST_CREATED_TOKEN+'"]');
      if (tr) {
        tr.style.background = 'var(--green-bg)';
        try { tr.scrollIntoView({ behavior:'smooth', block:'center' }); } catch(e2){}
        setTimeout(function(){ try{ tr.style.background = ''; }catch(e2){} }, 1600);
      }
      LAST_CREATED_TOKEN = null;
    }
  }

  btnRefresh.onclick = loadInvites;
  searchQ.oninput = function(){ clearTimeout(searchQ._t); searchQ._t = setTimeout(loadInvites, 300); };
  sortSel.onchange = loadInvites;
  chkAll.onchange = function(){ invitesTBody.querySelectorAll('.chkRow').forEach(function(c){ c.checked = chkAll.checked; }); };

  btnDisableSel.onclick = async function(){
    var toks = Array.from(invitesTBody.querySelectorAll('.chkRow:checked')).map(function(x){ return x.getAttribute('data-token'); });
    if (!toks.length) return;
    try{
      var r = await fetch('/api/invites/bulk', { method:'POST', headers:{'Content-Type':'application/json','Accept':'application/json'}, body: JSON.stringify({ tokens: toks, action:'disable' }) });
      if (!r.ok) throw new Error('Bulk disable failed');
      await loadInvites();
    }catch(e){ showResult('err'); }
  };
  btnEnableSel.onclick = async function(){
    var toks = Array.from(invitesTBody.querySelectorAll('.chkRow:checked')).map(function(x){ return x.getAttribute('data-token'); });
    if (!toks.length) return;
    try{
      var r = await fetch('/api/invites/bulk', { method:'POST', headers:{'Content-Type':'application/json','Accept':'application/json'}, body: JSON.stringify({ tokens: toks, action:'enable' }) });
      if (!r.ok) throw new Error('Bulk enable failed');
      await loadInvites();
    }catch(e){ showResult('err'); }
  };
  btnDeleteSel.onclick = async function(){
    var toks = Array.from(invitesTBody.querySelectorAll('.chkRow:checked')).map(function(x){ return x.getAttribute('data-token'); });
    if (!toks.length) return;
    if (!confirm('Are you sure? This cannot be undone.')) return;
    try{
      var r = await fetch('/api/invites/delete', { method:'POST', headers:{'Content-Type':'application/json','Accept':'application/json'}, body: JSON.stringify({ tokens: toks }) });
      if (!r.ok) throw new Error('Delete failed');
      await loadInvites();
    }catch(e){ showResult('err'); }
  };

  loadInvites();

  // --- Platform Cookies ---
  var cookiePlatform = document.getElementById('cookiePlatform');
  var cookieString = document.getElementById('cookieString');
  var btnSaveCookie = document.getElementById('btnSaveCookie');
  var btnRefreshCookies = document.getElementById('btnRefreshCookies');
  var cookiesTBody = document.getElementById('cookiesTBody');
  var cookieResult = document.getElementById('cookieResult');
  var COOKIES = [];
  var PLATFORMS = [];

  function showCookieResult(kind, text) {
    cookieResult.className = 'banner mt-3 ' + (kind === 'ok' ? 'banner--ok' : 'banner--err');
    cookieResult.textContent = text;
    cookieResult.classList.remove('hidden');
    setTimeout(function(){ cookieResult.classList.add('hidden'); }, 3000);
  }

  async function loadCookies() {
    try {
      var r = await fetch('/api/cookies');
      var j = await r.json();
      COOKIES = (j && j.items) ? j.items : [];
      PLATFORMS = (j && j.platforms) ? j.platforms : [];
      cookiePlatform.innerHTML = '<option value="">Select...</option>' +
        PLATFORMS.map(function(p){ return '<option value="'+escAttr(p)+'">'+escAttr(p.charAt(0).toUpperCase()+p.slice(1))+'</option>'; }).join('');
    } catch(e) {
      COOKIES = [];
      PLATFORMS = [];
    }
    renderCookies();
  }

  function fmtDate(iso) {
    try { var d = new Date(iso); return d.toLocaleDateString(undefined, { day: '2-digit', month: 'short', year: '2-digit' }); }
    catch(e) { return '-'; }
  }

  function renderCookies() {
    if (COOKIES.length === 0) {
      cookiesTBody.innerHTML = '<tr><td colspan="4" class="text-sm text-secondary" style="padding:16px;text-align:center;">No cookies configured.</td></tr>';
      return;
    }
    var rows = '';
    for (var i=0; i<COOKIES.length; i++){
      var c = COOKIES[i];
      var preview = c.cookie_preview || (c.cookie_string ? c.cookie_string.slice(0, 40) + '...' : '');
      rows += '<tr data-platform="'+escAttr(c.platform)+'">'
        + '<td data-label="Platform" style="font-weight:500;">'+escAttr(c.platform.charAt(0).toUpperCase()+c.platform.slice(1))+'</td>'
        + '<td data-label="Preview" class="text-mono text-xs text-secondary">'+escAttr(preview)+'</td>'
        + '<td data-label="Updated">'+escAttr(fmtDate(c.updated_at))+'</td>'
        + '<td class="td-actions" data-label="">'
        + '<div class="flex items-center gap-2">'
        + '<button class="btnEditCookie btn btn--sm btn--icon has-tooltip" data-platform="'+escAttr(c.platform)+'" data-cookie="'+escAttr(c.cookie_string)+'" aria-label="Edit"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" width="16" height="16"><path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04c.39-.39.39-1.02 0-1.41l-2.34-2.34c-.39-.39-1.02-.39-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/></svg><span class="tooltip">Edit</span></button>'
        + '<button class="btnDeleteCookie btn btn--sm btn--icon btn--danger has-tooltip" data-platform="'+escAttr(c.platform)+'" aria-label="Delete"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" width="16" height="16"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg><span class="tooltip">Delete</span></button>'
        + '</div></td></tr>';
    }
    cookiesTBody.innerHTML = rows;

    cookiesTBody.querySelectorAll('.btnEditCookie').forEach(function(btn){
      btn.onclick = function(){
        cookiePlatform.value = btn.getAttribute('data-platform');
        cookieString.value = btn.getAttribute('data-cookie');
        cookieString.focus();
      };
    });
    cookiesTBody.querySelectorAll('.btnDeleteCookie').forEach(function(btn){
      btn.onclick = async function(){
        var platform = btn.getAttribute('data-platform');
        if (!confirm('Delete cookies for '+platform+'?')) return;
        try {
          var r = await fetch('/api/cookies/'+platform, { method: 'DELETE' });
          if (!r.ok) throw new Error('Delete failed');
          showCookieResult('ok', 'Deleted cookies for '+platform);
          await loadCookies();
        } catch (e) { showCookieResult('err', String(e.message || e)); }
      };
    });
  }

  btnSaveCookie.onclick = async function(){
    var platform = cookiePlatform.value.trim();
    var cookie = cookieString.value.trim();
    if (!platform) { showCookieResult('err', 'Please select a platform'); return; }
    if (!cookie) { showCookieResult('err', 'Please enter a cookie string'); return; }
    try {
      var r = await fetch('/api/cookies', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
        body: JSON.stringify({ platform: platform, cookie_string: cookie })
      });
      var j = await r.json().catch(function(){ return {}; });
      if (!r.ok) { showCookieResult('err', j.error || 'Save failed'); return; }
      showCookieResult('ok', 'Saved cookies for '+platform);
      cookiePlatform.value = '';
      cookieString.value = '';
      await loadCookies();
    } catch (e) { showCookieResult('err', String(e.message || e)); }
  };

  btnRefreshCookies.onclick = loadCookies;
  loadCookies();

  fetch('/api/config')
    .then(function(r){ return r.json(); })
    .then(function(data){
      var versionEl = document.getElementById('version-link');
      if (versionEl && data.version) versionEl.textContent = 'immich-drop v' + data.version;
    })
    .catch(function(){});
})();
