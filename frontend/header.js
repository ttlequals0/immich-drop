// Shared header utilities: theme + ping + ephemeral banner
(function(){
  const doc = document;
  const root = doc.documentElement;
  const banner = doc.getElementById('topBanner');

  function updateThemeIcon(){
    const isDark = root.classList.contains('dark');
    const light = doc.getElementById('iconLight');
    const dark = doc.getElementById('iconDark');
    if (light && light.classList) light.classList.toggle('hidden', !isDark);
    if (dark && dark.classList) dark.classList.toggle('hidden', isDark);
  }

  function initDarkMode(){
    try{
      const stored = localStorage.getItem('theme');
      if (stored === 'dark' || (!stored && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
        root.classList.add('dark');
      } else {
        root.classList.remove('dark');
      }
    }catch{}
    updateThemeIcon();
  }

  function toggleDarkMode(){
    const isDark = root.classList.toggle('dark');
    try{ localStorage.setItem('theme', isDark ? 'dark' : 'light'); }catch{}
    updateThemeIcon();
  }

  function showBanner(text, kind='ok'){
    if(!banner) return;
    banner.textContent = text;
    banner.className = 'rounded-2xl p-3 text-center transition-colors ' + (
      kind==='ok' ? 'border border-green-200 bg-green-50 text-green-700 dark:bg-green-900 dark:border-green-700 dark:text-green-300'
      : kind==='warn' ? 'border border-amber-200 bg-amber-50 text-amber-700 dark:bg-amber-900 dark:border-amber-700 dark:text-amber-300'
      : 'border border-red-200 bg-red-50 text-red-700 dark:bg-red-900 dark:border-red-700 dark:text-red-300'
    );
    banner.classList.remove('hidden');
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
