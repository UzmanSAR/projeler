/* Ana ekrana eklenebilen uygulama (PWA). Classic deferred script, last in <body>.
   It registers the service worker (offline page only, nothing is cached) and offers "Ana ekrana ekle"
   once the browser allows it. Without it every page works as before. */
(function () {
  'use strict';
  var w = window, d = document, n = navigator, root = d.documentElement;
  if ('serviceWorker' in n) w.addEventListener('load', function () { n.serviceWorker.register('/sw.js').catch(function () {}); });

  /* Where the offer is made: the barber's first screen, and the customer's shop page and ticket.
     Not in the middle of a booking, not on forms. */
  var screen = root.getAttribute('data-screen') || '', link = d.querySelector('link[rel="manifest"]');
  var shop = !!link && link.getAttribute('href') !== '/uygulama.webmanifest';
  var where = !shop && screen === 'today' ? 'panel' : shop && (screen === 'shop' || screen === 'ticket') ? 'shop' : '';
  var standalone = n.standalone === true || !!(w.matchMedia && w.matchMedia('(display-mode: standalone)').matches);
  if (!where || standalone) return;

  var KEY = 'pwa:later', until = 0, bar = null, deferred = null;
  try { until = +w.localStorage.getItem(KEY) || 0; } catch (e) {}
  if (Date.now() < until) return;
  function later(days) { try { w.localStorage.setItem(KEY, String(Date.now() + days * 864e5)); } catch (e) {} }
  function hide(days) { if (bar) { bar.remove(); bar = null; } if (days) later(days); }

  function show(ios) {
    if (bar) return;
    var name = (d.querySelector('meta[name="apple-mobile-web-app-title"]') || {}).content || '';
    var icon = (d.querySelector('link[rel="apple-touch-icon"]') || {}).href || '';
    bar = d.createElement('div'); bar.className = 'install'; bar.setAttribute('role', 'region'); bar.setAttribute('aria-label', 'Ana ekrana ekle');
    var img = d.createElement('img'); img.src = icon; img.alt = ''; img.width = 44; img.height = 44;
    var text = d.createElement('p'), title = d.createElement('b'), sub = d.createElement('span');
    title.textContent = where === 'panel' ? 'Paneli ana ekranına ekle' : name + ' ana ekranında dursun';
    sub.textContent = ios ? 'Paylaş düğmesine, sonra “Ana Ekrana Ekle”ye dokun.'
      : where === 'panel' ? 'Uygulama gibi açılır, tek dokunuşla.' : 'Randevunu tek dokunuşla alırsın.';
    text.appendChild(title); text.appendChild(sub); bar.appendChild(img); bar.appendChild(text);
    if (!ios) {
      var add = d.createElement('button'); add.type = 'button'; add.className = 'btn small'; add.textContent = 'Ekle';
      add.addEventListener('click', function () {
        if (!deferred) return hide(0);
        deferred.prompt();
        deferred.userChoice.then(function (choice) { hide(choice && choice.outcome === 'accepted' ? 3650 : 14); }, function () { hide(14); });
        deferred = null;
      });
      bar.appendChild(add);
    }
    var x = d.createElement('button'); x.type = 'button'; x.className = 'install-x'; x.setAttribute('aria-label', 'Şimdi değil'); x.textContent = '×';
    x.addEventListener('click', function () { hide(14); });
    bar.appendChild(x);
    /* above the fixed bottom bar of the page, if it has one (panel tabs on a phone, the booking button) */
    var fixed = d.querySelector('.sticky, .tabs');
    if (fixed) { var r = fixed.getBoundingClientRect(); if (w.getComputedStyle(fixed).position === 'fixed' && r.bottom >= w.innerHeight - 2) bar.style.bottom = (r.height + 12) + 'px'; }
    d.body.appendChild(bar);
  }

  w.addEventListener('beforeinstallprompt', function (e) { e.preventDefault(); deferred = e; show(false); });
  w.addEventListener('appinstalled', function () { hide(3650); });
  /* iOS has no install prompt: say where the button is. (Every iOS browser has had it in the share menu since 16.4.) */
  var ua = n.userAgent || '';
  if (/iPad|iPhone|iPod/.test(ua) || (n.platform === 'MacIntel' && n.maxTouchPoints > 1)) show(true);
})();
