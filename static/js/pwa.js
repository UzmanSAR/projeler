/* Ana ekrana eklenebilen uygulama (PWA). Classic deferred script, last in <body>.
   It registers the service worker (offline page only, nothing is cached) and offers "Ana ekrana ekle"
   once the browser allows it. Without it every page works as before. */
(function () {
  'use strict';
  var w = window, d = document, n = navigator, root = d.documentElement;
  if ('serviceWorker' in n) w.addEventListener('load', function () { n.serviceWorker.register('/sw.js').catch(function () {}); });

  /* Where the offer is made: the barber's first screen, and the customer's shop page and ticket.
     Not in the middle of a booking, not on forms. Each app (the panel, each shop) remembers its own answer. */
  var screen = root.getAttribute('data-screen') || '', link = d.querySelector('link[rel="manifest"]');
  var href = link ? link.getAttribute('href') : '', shop = !!href && href !== '/uygulama.webmanifest';
  var where = !shop && screen === 'today' ? 'panel' : shop && (screen === 'shop' || screen === 'ticket') ? 'shop' : '';
  var standalone = n.standalone === true || !!(w.matchMedia && w.matchMedia('(display-mode: standalone)').matches);
  var KEY = 'pwa:later:' + (shop ? href : 'panel'), until = 0, bar = null, deferred = null, pad = '';
  try { until = +w.localStorage.getItem(KEY) || 0; } catch (e) {}
  var offer = !!where && !standalone && Date.now() >= until;

  function later(days) { try { w.localStorage.setItem(KEY, String(Date.now() + days * 864e5)); } catch (e) {} }
  function hide(days) {
    if (bar) { bar.remove(); bar = null; d.body.style.paddingBottom = pad; }
    if (days) { later(days); offer = false; }
  }
  /* above the fixed bottom bar of the page, if it has one (panel tabs on a phone, the booking button);
     measured again when the screen turns or the window changes */
  function place() {
    if (!bar) return;
    bar.style.bottom = '';
    var fixed = d.querySelector('.sticky, .tabs');
    if (fixed) { var r = fixed.getBoundingClientRect(); if (w.getComputedStyle(fixed).position === 'fixed' && r.bottom >= w.innerHeight - 2) bar.style.bottom = (r.height + 12) + 'px'; }
    /* room at the end of the page: the last buttons and links can be scrolled clear of the bar */
    d.body.style.paddingBottom = pad;
    d.body.style.paddingBottom = (parseFloat(w.getComputedStyle(d.body).paddingBottom) + bar.offsetHeight + 12) + 'px';
  }

  function show(ios) {
    if (bar || !offer) return;
    var name = (d.querySelector('meta[name="apple-mobile-web-app-title"]') || {}).content || '';
    var icon = (d.querySelector('link[rel="apple-touch-icon"]') || {}).href || '';
    bar = d.createElement('div'); bar.className = 'install'; bar.setAttribute('role', 'region'); bar.setAttribute('aria-label', 'Ana ekrana ekle');
    var img = d.createElement('img'); img.src = icon; img.alt = ''; img.width = 44; img.height = 44;
    var text = d.createElement('p'), title = d.createElement('b'), sub = d.createElement('span');
    title.textContent = ios ? 'Paylaş düğmesine, sonra “Ana Ekrana Ekle”ye dokun' : where === 'panel' ? 'Paneli ana ekranına ekle' : name + ' ana ekranında dursun';
    sub.textContent = ios ? (where === 'panel' ? 'Panel uygulama gibi açılır.' : name + ' ana ekranında durur.')
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
    pad = d.body.style.paddingBottom;
    d.body.appendChild(bar); place();
  }

  /* The browser's own banner is always held back: the offer appears only where this script shows it,
     never in the middle of a booking and not again after "Şimdi değil". */
  w.addEventListener('beforeinstallprompt', function (e) { e.preventDefault(); if (offer) { deferred = e; show(false); } });
  w.addEventListener('appinstalled', function () { hide(3650); });
  w.addEventListener('resize', place);
  /* iOS has no install prompt: say where the button is, but only where it exists. In-app browsers
     (Instagram, Facebook…) cannot add to the home screen; other iOS browsers can since 16.4. */
  var ua = n.userAgent || '', ios = /iPad|iPhone|iPod/.test(ua) || (n.platform === 'MacIntel' && n.maxTouchPoints > 1);
  var inApp = !/Safari\//.test(ua) || /Instagram|FBAN|FBAV|FB_IAB|Line\/|TikTok|musical_ly|Snapchat|GSA\//.test(ua);
  var v = /OS (\d+)_(\d+)/.exec(ua), old = /CriOS|FxiOS|EdgiOS|OPiOS/.test(ua) && !!v && (+v[1] < 16 || (+v[1] === 16 && +v[2] < 4));
  if (ios && !inApp && !old) show(true);
})();
