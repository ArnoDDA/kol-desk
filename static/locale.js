// Load exactly one language bundle. Saved business information is never translated.
(() => {
  let saved;
  try { saved = localStorage.getItem('kol_language'); } catch (_) {}
  const requested = new URLSearchParams(location.search).get('lang');
  window.KOL_LANG = ['en', 'zh'].includes(requested) ? requested : (saved === 'en' ? 'en' : 'zh');
  try { localStorage.setItem('kol_language', window.KOL_LANG); } catch (_) {}
  document.documentElement.lang = window.KOL_LANG === 'en' ? 'en' : 'zh-CN';
  document.title = window.KOL_LANG === 'en' ? 'KOL Desk · Game Creator Partnerships' : 'KOL Desk · 游戏达人决策工作台';
  document.querySelector('.loading').textContent = window.KOL_LANG === 'en' ? 'Opening your workspace...' : '正在打开工作台…';
  const prefix = window.KOL_LANG === 'en' ? '/en/' : '/';
  function load(name, next) {
    const script = document.createElement('script');
    script.src = prefix + name;
    script.onload = next;
    script.onerror = () => { document.querySelector('#app').textContent = window.KOL_LANG === 'en' ? 'Could not load the workspace. Refresh to try again.' : '页面未能加载，请刷新后重试。'; };
    document.body.appendChild(script);
  }
  load('discovery.js', () => load('app.js', () => {}));
})();
