// Shared header utilities: theme + ping + ephemeral banner
(function(){
  const doc = document;
  const root = doc.documentElement;
  const banner = doc.getElementById('topBanner');

  let themeMode = 'system';
  const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)');

  function applyTheme(mode){
    const useDark = mode === 'dark' || (mode === 'system' && prefersDark && prefersDark.matches);
    root.classList.toggle('dark', useDark);
    root.dataset.theme = mode;
  }

  function updateThemeIcon(){
    const light = doc.getElementById('iconLight');
    const dark = doc.getElementById('iconDark');
    const system = doc.getElementById('iconSystem');
    if (light) light.classList.toggle('hidden', themeMode !== 'light');
    if (dark) dark.classList.toggle('hidden', themeMode !== 'dark');
    if (system) system.classList.toggle('hidden', themeMode !== 'system');
  }

  function initDarkMode(){
    themeMode = 'system';
    applyTheme(themeMode);
    updateThemeIcon();
    if (prefersDark && prefersDark.addEventListener) {
      prefersDark.addEventListener('change', () => {
        if (themeMode === 'system') applyTheme('system');
      });
    }
  }

  function toggleDarkMode() {
    themeMode = (themeMode === 'dark') ? 'system' : (themeMode === 'system') ? 'light' : 'dark';
    applyTheme(themeMode);
    updateThemeIcon();
  }

  function showBanner(text, kind='ok'){
    if(!banner) return;
    banner.textContent = text;
    banner.className = 'banner ' + (kind==='ok' ? 'banner--ok' : kind==='warn' ? 'banner--warn' : 'banner--err');
    setTimeout(() => banner.classList.add('hidden'), 3000);
  }

  function wire(){
    const btnTheme = doc.getElementById('btnTheme');
    const btnPing = doc.getElementById('btnPing');
    const pingStatus = doc.getElementById('pingStatus');
    const linkPublic = doc.getElementById('linkPublicUploader');
    const linkHome = doc.getElementById('linkHome');
    if (btnTheme) btnTheme.onclick = toggleDarkMode;
    if (btnPing) btnPing.onclick = async () => {
      if (pingStatus) pingStatus.textContent = 'checking…';
      try{
        const r = await fetch('/api/ping', { method:'POST' });
        const j = await r.json();
        if (pingStatus) {
          pingStatus.textContent = j.ok ? 'Connected' : 'No connection';
          pingStatus.className = 'ml-2 text-sm ' + (j.ok ? 'text-green-600' : 'text-red-600');
        }
        if(j.ok){
          let text = `Connected to Immich at ${j.base_url}`;
          if (j.album_name) text += ` | Uploading to album: "${j.album_name}"`;
          showBanner(text, 'ok');
        }
      }catch{
        if (pingStatus) {
          pingStatus.textContent = 'No connection';
          pingStatus.className='ml-2 text-sm text-red-600';
        }
      }
    };

    // Hide public uploader links unless enabled
    (async ()=>{
      try{
        const r = await fetch('/api/config');
        const j = await r.json();
        const enabled = !!(j && j.public_upload_page_enabled);
        if (linkPublic) linkPublic.classList.toggle('hidden', !enabled);
        if (linkHome) linkHome.classList.toggle('hidden', !enabled);
      }catch{
        if (linkPublic) linkPublic.classList.add('hidden');
        if (linkHome) linkHome.classList.add('hidden');
      }
    })();
  }

  initDarkMode();
  wire();

  // Expose for other scripts if needed
  window.__header = { toggleDarkMode, showBanner };
})();
