// Installable app support: registers the service worker and works out how this phone installs apps.
window.PWA = (() => {
  if ('serviceWorker' in navigator) addEventListener('load', () => navigator.serviceWorker.register('/sw.js').catch(() => {}));
  const ua = navigator.userAgent;
  const isIOS = /iphone|ipad|ipod/i.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  const standalone = () => matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
  // iOS apps like WeChat/WhatsApp open links in their own browser, which can't add to the home screen
  const iosInApp = isIOS && !/safari/i.test(ua) && !/crios|fxios|edgios/i.test(ua) || /micromessenger|whatsapp|fban|fbav|instagram|line\//i.test(ua);
  let prompt = null;
  addEventListener('beforeinstallprompt', e => { e.preventDefault(); prompt = e; dispatchEvent(new Event('pwa-change')); });
  addEventListener('appinstalled', () => { prompt = null; dispatchEvent(new Event('pwa-installed')); dispatchEvent(new Event('pwa-change')); });
  return {
    isIOS, iosInApp, standalone,
    // 'prompt' = Android/desktop Chrome can install directly; 'ios' = show the Share → Add to Home Screen guide
    mode: () => standalone() ? null : prompt ? 'prompt' : isIOS ? 'ios' : null,
    async install() { if (!prompt) return false; prompt.prompt(); const r = await prompt.userChoice; prompt = null; dispatchEvent(new Event('pwa-change')); return r.outcome === 'accepted'; },
  };
})();
