/* DoechBots Panel: ana ekrana eklenebilen uygulama (PWA).
   Her panel sayfasında </body>'den hemen önce yüklenir:  <script src="/pwa.js" defer></script>
   - Hizmet betiğini (/sw.js) kaydeder.
   - Tarayıcı izin verdiğinde altta "Ana ekrana ekle" çubuğu gösterir (Android/Chrome/Edge).
   - iPhone/iPad'de Paylaş > "Ana Ekrana Ekle" adımını tarif eder.
   - "Şimdi değil" denirse 14 gün, eklenirse bir daha sorulmaz.
   Çubuğu göstermek istemediğin sayfada <html data-pwa-teklif="yok"> yaz (ör. giriş, ödeme).
   Betik çalışmasa bile panel eskisi gibi çalışır. */
(function () {
  'use strict';
  var w = window, d = document, n = navigator, root = d.documentElement;
  if ('serviceWorker' in n) w.addEventListener('load', function () { n.serviceWorker.register('/sw.js').catch(function () {}); });

  var KEY = 'doechbots:pwa:sonra', until = 0, bar = null, deferred = null;
  try { until = +w.localStorage.getItem(KEY) || 0; } catch (e) {}
  var standalone = n.standalone === true || !!(w.matchMedia && w.matchMedia('(display-mode: standalone)').matches);
  var offer = !standalone && Date.now() >= until && root.getAttribute('data-pwa-teklif') !== 'yok';
  if (standalone) root.classList.add('pwa-standalone');   /* uygulama olarak açıldığında CSS'te kullanılabilir */

  function later(days) { try { w.localStorage.setItem(KEY, String(Date.now() + days * 864e5)); } catch (e) {} }
  function hide(days) {
    if (bar) { bar.remove(); bar = null; }
    if (days) { later(days); offer = false; }
  }

  function style() {
    if (d.getElementById('pwa-teklif-stil')) return;
    var s = d.createElement('style'); s.id = 'pwa-teklif-stil';
    s.textContent =
      '.pwa-teklif{position:fixed;left:12px;right:12px;bottom:calc(12px + env(safe-area-inset-bottom));z-index:9999;' +
      'max-width:30rem;margin:0 auto;display:flex;align-items:center;gap:12px;padding:12px 8px 12px 12px;border-radius:16px;' +
      'background:#1a1d24;color:#eef0f4;box-shadow:0 8px 32px rgba(0,0,0,.35);font:15px/1.35 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}' +
      '.pwa-teklif img{width:44px;height:44px;border-radius:11px;flex:none}' +
      '.pwa-teklif p{margin:0;flex:1;min-width:0}.pwa-teklif b{display:block}.pwa-teklif span{color:#9aa1ad;font-size:13px}' +
      '.pwa-teklif .pwa-ekle{font:inherit;font-weight:600;border:0;border-radius:10px;padding:0 16px;min-height:44px;background:#f5b83d;color:#14161b;cursor:pointer}' +
      '.pwa-teklif .pwa-x{font:22px/1 system-ui,sans-serif;border:0;background:none;color:#9aa1ad;width:44px;height:44px;cursor:pointer;flex:none}' +
      '@media (prefers-color-scheme:light){.pwa-teklif{background:#fff;color:#14161b}.pwa-teklif span,.pwa-teklif .pwa-x{color:#5b6270}}';
    d.head.appendChild(s);
  }

  function show(ios) {
    if (bar || !offer) return;
    style();
    bar = d.createElement('div'); bar.className = 'pwa-teklif'; bar.setAttribute('role', 'region'); bar.setAttribute('aria-label', 'Ana ekrana ekle');
    var img = d.createElement('img'); img.src = '/icons/icon-192.png'; img.alt = ''; img.width = 44; img.height = 44;
    var text = d.createElement('p'), title = d.createElement('b'), sub = d.createElement('span');
    title.textContent = ios ? 'Paylaş düğmesine, sonra “Ana Ekrana Ekle”ye dokun' : 'DoechBots’u ana ekranına ekle';
    sub.textContent = ios ? 'Panel uygulama gibi tam ekran açılır.' : 'Botlarını tek dokunuşla, uygulama gibi yönet.';
    text.appendChild(title); text.appendChild(sub); bar.appendChild(img); bar.appendChild(text);
    if (!ios) {
      var add = d.createElement('button'); add.type = 'button'; add.className = 'pwa-ekle'; add.textContent = 'Ekle';
      add.addEventListener('click', function () {
        if (!deferred) return hide(0);
        deferred.prompt();
        deferred.userChoice.then(function (c) { hide(c && c.outcome === 'accepted' ? 3650 : 14); }, function () { hide(14); });
        deferred = null;
      });
      bar.appendChild(add);
    }
    var x = d.createElement('button'); x.type = 'button'; x.className = 'pwa-x'; x.setAttribute('aria-label', 'Şimdi değil'); x.textContent = '×';
    x.addEventListener('click', function () { hide(14); });
    bar.appendChild(x);
    d.body.appendChild(bar);
  }

  /* Tarayıcının kendi kurulum afişi bastırılır; teklif yalnızca bu çubukla yapılır. */
  w.addEventListener('beforeinstallprompt', function (e) { e.preventDefault(); if (offer) { deferred = e; show(false); } });
  w.addEventListener('appinstalled', function () { hide(3650); });

  /* iOS'ta kurulum penceresi yok: düğmenin yerini tarif et. Uygulama içi tarayıcılar (Instagram, Facebook…)
     ana ekrana ekleyemez; Safari dışındaki iOS tarayıcıları 16.4'ten beri ekleyebilir. */
  var ua = n.userAgent || '', ios = /iPad|iPhone|iPod/.test(ua) || (n.platform === 'MacIntel' && n.maxTouchPoints > 1);
  var inApp = !/Safari\//.test(ua) || /Instagram|FBAN|FBAV|FB_IAB|Line\/|TikTok|musical_ly|Snapchat|GSA\//.test(ua);
  var v = /OS (\d+)_(\d+)/.exec(ua), old = /CriOS|FxiOS|EdgiOS|OPiOS/.test(ua) && !!v && (+v[1] < 16 || (+v[1] === 16 && +v[2] < 4));
  if (ios && !inApp && !old) {
    if (d.readyState === 'loading') d.addEventListener('DOMContentLoaded', function () { show(true); }); else show(true);
  }
})();
