// Frontend logic (mobile-safe picker; no settings UI)
const sessionId = (crypto && crypto.randomUUID) ? crypto.randomUUID() : (Math.random().toString(36).slice(2));
let items = [];
let socket;

// --- Dark mode ---
function initDarkMode() {
  const stored = localStorage.getItem('theme');
  if (stored === 'dark' || (!stored && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
    document.documentElement.classList.add('dark');
  }
  updateThemeIcon();
}

function toggleDarkMode() {
  const isDark = document.documentElement.classList.toggle('dark');
  localStorage.setItem('theme', isDark ? 'dark' : 'light');
  updateThemeIcon();
}

function updateThemeIcon() {
  const isDark = document.documentElement.classList.contains('dark');
  document.getElementById('iconLight').classList.toggle('hidden', !isDark);
  document.getElementById('iconDark').classList.toggle('hidden', isDark);
}

initDarkMode();

// --- helpers ---
function human(bytes){
  if (!bytes) return '0 B';
  const k = 1024, sizes = ['B','KB','MB','GB','TB'];
  const i = Math.floor(Math.log(bytes)/Math.log(k));
  return (bytes/Math.pow(k,i)).toFixed(1)+' '+sizes[i];
}

function addItem(file){
  const id = (crypto && crypto.randomUUID) ? crypto.randomUUID() : (Math.random().toString(36).slice(2));
  const it = { id, file, name: file.name, size: file.size, status: 'queued', progress: 0 };
  items.unshift(it);
  render();
}

function render(){
  const itemsEl = document.getElementById('items');
  itemsEl.innerHTML = items.map(it => `
    <div class="rounded-2xl border bg-white dark:bg-gray-800 dark:border-gray-700 p-4 shadow-sm transition-colors">
      <div class="flex items-center justify-between">
        <div class="min-w-0">
          <div class="truncate font-medium">${it.name} <span class="text-xs text-gray-500 dark:text-gray-400">(${human(it.size)})</span></div>
          <div class="mt-1 text-xs text-gray-600 dark:text-gray-400">
            ${it.message ? `<span>${it.message}</span>` : ''}
          </div>
        </div>
        <div class="text-sm">${it.status}</div>
      </div>
      <div class="mt-3 h-2 w-full overflow-hidden rounded-full bg-gray-100 dark:bg-gray-700">
        <div class="h-full ${it.status==='done'?'bg-green-500':it.status==='duplicate'?'bg-amber-500':it.status==='error'?'bg-red-500':(it.status==='uploading' && it.progress >= 100)?'bg-green-500':'bg-blue-500'}" style="width:${Math.max(it.progress, (it.status==='done'||it.status==='duplicate'||it.status==='error')?100:it.progress)}%"></div>
      </div>
      <div class="mt-2 text-sm text-gray-600 dark:text-gray-400">
        ${it.status==='uploading' ? (it.progress >= 100 ? 'Processing...' : `Uploading… ${it.progress}%`) : it.status.charAt(0).toUpperCase()+it.status.slice(1)}
      </div>
    </div>
  `).join('');

  const c = {queued:0,uploading:0,done:0,dup:0,err:0};
  for(const it of items){
    if(['queued','checking'].includes(it.status)) c.queued++;
    if(it.status==='uploading') c.uploading++;
    if(it.status==='done') c.done++;
    if(it.status==='duplicate') c.dup++;
    if(it.status==='error') c.err++;
  }
  document.getElementById('countQueued').textContent=c.queued;
  document.getElementById('countUploading').textContent=c.uploading;
  document.getElementById('countDone').textContent=c.done;
  document.getElementById('countDup').textContent=c.dup;
  document.getElementById('countErr').textContent=c.err;
}

// --- WebSocket progress ---
function openSocket(){
  socket = new WebSocket((location.protocol==='https:'?'wss':'ws')+'://'+location.host+'/ws');
  socket.onopen = () => { socket.send(JSON.stringify({session_id: sessionId})); };
  socket.onmessage = (evt) => {
    const msg = JSON.parse(evt.data);
    const { item_id, status, progress, message } = msg;
    const it = items.find(x => x.id===item_id);
    if(!it) return;
    it.status = status;
    if(typeof progress==='number') it.progress = progress;
    if(message) it.message = message;
    render();
  };
  socket.onclose = () => setTimeout(openSocket, 2000);
}
openSocket();

// --- Upload queue ---
async function runQueue(){
  let inflight = 0;
  async function runNext(){
    if(inflight >= 3) return; // client-side throttle; server handles uploads regardless
    const next = items.find(i => i.status==='queued');
    if(!next) return;
    next.status='checking';
    render();
    inflight++;
    try{
      const form = new FormData();
      form.append('file', next.file);
      form.append('item_id', next.id);
      form.append('session_id', sessionId);
      form.append('last_modified', next.file.lastModified || '');
      const res = await fetch('/api/upload', { method:'POST', body: form });
      const body = await res.json().catch(()=>({}));
      if(!res.ok && next.status!=='error'){
        next.status='error';
        next.message = body.error || 'Upload failed';
        render();
      }
    }catch(err){
      next.status='error';
      next.message = String(err);
      render();
    }finally{
      inflight--;
      setTimeout(runNext, 50);
    }
  }
  for(let i=0;i<3;i++) runNext();
}

// --- DOM refs ---
const dz = document.getElementById('dropzone');
const fi = document.getElementById('fileInput');
const btnClearFinished = document.getElementById('btnClearFinished');
const btnClearAll = document.getElementById('btnClearAll');
const btnPing = document.getElementById('btnPing');
const pingStatus = document.getElementById('pingStatus');
const banner = document.getElementById('topBanner');
const btnTheme = document.getElementById('btnTheme');

// --- Connection test with ephemeral banner ---
btnPing.onclick = async () => {
  pingStatus.textContent = 'checking…';
  try{
    const r = await fetch('/api/ping', { method:'POST' });
    const j = await r.json();
    pingStatus.textContent = j.ok ? 'Connected' : 'No connection';
    pingStatus.className = 'ml-2 text-sm ' + (j.ok ? 'text-green-600' : 'text-red-600');
    if(j.ok){
      let bannerText = `Connected to Immich at ${j.base_url}`;
      if(j.album_name) {
        bannerText += ` | Uploading to album: "${j.album_name}"`;
      }
      banner.textContent = bannerText;
      banner.classList.remove('hidden');
      setTimeout(() => banner.classList.add('hidden'), 4000);
    }
  }catch{
    pingStatus.textContent = 'No connection';
    pingStatus.className='ml-2 text-sm text-red-600';
  }
};

// --- Drag & drop (no click-to-open on touch) ---
['dragenter','dragover'].forEach(ev => dz.addEventListener(ev, e=>{ e.preventDefault(); dz.classList.add('border-blue-500','bg-blue-50','dark:bg-blue-900','dark:bg-opacity-20'); }));
['dragleave','drop'].forEach(ev => dz.addEventListener(ev, e=>{ e.preventDefault(); dz.classList.remove('border-blue-500','bg-blue-50','dark:bg-blue-900','dark:bg-opacity-20'); }));
dz.addEventListener('drop', (e)=>{
  e.preventDefault();
  const files = Array.from(e.dataTransfer.files || []);
  const accepted = files.filter(f => /^(image|video)\//.test(f.type) || /\.(jpe?g|png|heic|heif|webp|gif|tiff|bmp|mp4|mov|m4v|avi|mkv)$/i.test(f.name));
  accepted.forEach(addItem);
  render();
  runQueue();
});

// --- Mobile-safe file input change handler ---
const isTouch = ('ontouchstart' in window) || (navigator.maxTouchPoints > 0);
let suppressClicksUntil = 0;

fi.addEventListener('click', (e) => {
  // prevent bubbling to parents (extra safety)
  e.stopPropagation();
});

fi.onchange = () => {
  // Suppress any stray clicks for a short window after the picker closes
  suppressClicksUntil = Date.now() + 800;

  const files = Array.from(fi.files || []);
  const accepted = files.filter(f =>
    /^(image|video)\//.test(f.type) ||
    /\.(jpe?g|png|heic|heif|webp|gif|tiff|bmp|mp4|mov|m4v|avi|mkv)$/i.test(f.name)
  );
  accepted.forEach(addItem);
  render();
  runQueue();

  // Reset a bit later so selecting the same items again still triggers 'change'
  setTimeout(() => { try { fi.value = ''; } catch {} }, 500);
};

// If you want the whole dropzone clickable on desktop only, enable this:
if (!isTouch) {
  dz.addEventListener('click', () => {
    // avoid accidental double-open if something weird happens
    if (Date.now() < suppressClicksUntil) return;
    try { fi.value = ''; } catch {}
    fi.click();
  });
}

// --- Clear buttons ---
btnClearFinished.onclick = ()=>{ items = items.filter(i => !['done','duplicate'].includes(i.status)); render(); };
btnClearAll.onclick = ()=>{ items = []; render(); };

// --- Dark mode toggle ---
btnTheme.onclick = toggleDarkMode;
