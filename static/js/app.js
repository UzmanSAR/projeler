/* Motion layer, core. Classic blocking script in <head>: never defer, async or type=module.
   Without it every page is complete; it never adds a class that hides anything. */
(function () {
  'use strict';
  var w = window, d = document, root = d.documentElement, ss = null;
  try { ss = w.sessionStorage; ss.setItem('m:t', '1'); ss.removeItem('m:t'); } catch (e) { ss = null; }
  var store = {
    get: function (k) { try { return ss ? JSON.parse(ss.getItem('m:' + k)) : null; } catch (e) { return null; } },
    set: function (k, v) { try { if (ss) ss.setItem('m:' + k, JSON.stringify(v)); } catch (e) {} },
    take: function (k) { var v = store.get(k); try { if (ss) ss.removeItem('m:' + k); } catch (e) {} return v; }
  };

  /* ---- level: off | lite | full; the server's value is only ever lowered here */
  var level = root.getAttribute('data-motion'), pref = null, con = navigator.connection;
  if (level !== 'lite' && level !== 'off') level = 'full';
  try { pref = w.localStorage.getItem('motion'); } catch (e) {}
  if (pref === 'off' || (pref === 'lite' && level === 'full')) level = pref;
  if (level === 'full' && ((con && (con.saveData || /(^|-)2g$/.test(con.effectiveType || ''))) || navigator.deviceMemory <= 1)) level = 'lite';
  root.setAttribute('data-motion', level);
  var reduced = level === 'off' || !!(w.matchMedia && w.matchMedia('(prefers-reduced-motion: reduce)').matches);
  var M = w.Motion = { store: store, reduced: reduced, lite: level === 'lite', full: !reduced && level === 'full', nav: 'rise', from: null, screen: 'other', entering: false };
  M.flag = function (name) { return (' ' + (root.getAttribute('data-flags') || '') + ' ').indexOf(' ' + name + ' ') > -1; };

  /* ---- screens and ranks, first match wins; core/test_motion.py keeps them in step with urls.py */
  var SCREENS = [
    [/^\/$/, 'landing', 0], [/^\/panel\/(giris|kayit)\/$/, 'auth', 5],
    [/^\/panel\/$/, 'today', 100], [/^\/panel\/takvim\//, 'calendar', 110],
    [/^\/panel\/musteriler\/$/, 'customers', 120], [/^\/panel\/musteriler\/\d+\/$/, 'customer', 125],
    [/^\/panel\/raporlar\//, 'report', 130],
    [/^\/panel\/ayarlar\/$/, 'settings', 140], [/^\/panel\/ayarlar\/./, 'settings-sub', 145],
    [/^\/panel\//, 'other', 100],
    [/^\/[^/]+\/$/, 'shop', 10], [/^\/[^/]+\/hesabim\/$/, 'account', 15],
    [/^\/[^/]+\/randevu\/$/, 'select', 20], [/^\/[^/]+\/randevu\/saat\/$/, 'time', 30],
    [/^\/[^/]+\/randevu\/bilgi\/$/, 'details', 40], [/^\/[^/]+\/randevu\/kod\/$/, 'verify', 50],
    [/^\/[^/]+\/r\/[^/]+\/$/, 'ticket', 60], [/^/, 'other', 10]
  ];
  function screenOf(p) { for (var i = 0; ; i++) if (SCREENS[i][0].test(p)) return SCREENS[i].slice(1); }
  function param(search, key) { var m = new RegExp('[?&]' + key + '=([^&]*)').exec(search); return m ? m[1] : ''; }
  var navType = 'push', restored = false;
  function direction() {
    var act = null, from = null, trav = 0, nav = 'rise', fromS = null, cur = screenOf(location.pathname);
    navType = 'push';
    try {
      var pe = performance.getEntriesByType('navigation')[0];
      if (pe) navType = pe.type === 'back_forward' ? 'traverse' : pe.type === 'reload' ? 'reload' : 'push';
      act = w.navigation && w.navigation.activation;
      if (act) {
        if (act.navigationType) navType = act.navigationType === 'replace' ? 'push' : act.navigationType;
        if (act.from && act.from.url) from = act.from.url;
        if (navType === 'traverse' && act.from && act.entry) trav = act.entry.index < act.from.index ? -1 : 1;
      }
    } catch (e) {}
    if (restored && navType !== 'traverse') { navType = 'traverse'; trav = 0; }   /* bfcache, no Navigation API */
    if (!from && navType === 'push' && d.referrer) from = d.referrer;
    if (navType === 'traverse') nav = trav > 0 ? 'fwd' : 'back';
    else if (navType === 'push' && from) {
      try {
        var u = new URL(from), prev = screenOf(u.pathname);
        if (u.origin === location.origin) {
          fromS = prev[0];
          if (u.pathname === location.pathname) {
            /* only the calendar day and the report month have an order: a booking day change is "same" */
            var k = cur[0] === 'calendar' ? 'g' : cur[0] === 'report' ? 'ay' : '', x = k && (param(u.search, k) || (store.get('scroll') || {}).g), y = k && param(location.search, k);
            nav = x && y && x !== y ? (y > x ? 'fwd' : 'back') : 'same';
          } else if ((prev[0] === 'shop' && cur[0] === 'select') || (prev[0] === 'auth' && cur[1] >= 100)) nav = 'wipe';
          else if (prev[1] >= 100 && cur[1] >= 100 && Math.floor(prev[1] / 10) !== Math.floor(cur[1] / 10)) nav = 'tab';
          else if (prev[0] === 'ticket' && /^(select|time)$/.test(cur[0])) nav = 'fwd';   /* "Yeni randevu al" */
          else if (cur[1] !== prev[1]) nav = cur[1] > prev[1] ? 'fwd' : 'back';
        }
      } catch (e) {}
    }
    /* the razor exists only while a transition runs: pagereveal confirms it */
    if (nav === 'wipe' && (!M.full || !('onpagereveal' in w))) nav = 'fwd';
    M.nav = nav; M.from = fromS; M.screen = cur[0];
    root.setAttribute('data-screen', cur[0]);
    root.setAttribute('data-nav', nav);
    if (fromS) root.setAttribute('data-from', fromS); else root.removeAttribute('data-from');
    return cur;
  }
  var cur = direction();
  /* a slow zone script must not hold the first paint for good */
  setTimeout(function () { var l = d.querySelector('link[rel="expect"]'); if (l && !d.getElementById('eof')) l.remove(); }, 2500);
  /* the gate. Fails closed: no storage => quiet panel, no sign reveal. Back and Forward are always quiet */
  var enterOff = M.nav === 'same' || level !== 'full' || navType === 'traverse';
  if (cur[1] >= 100) {
    var key = location.pathname + location.search, seen = store.get('seen') || [];
    if (!ss || seen.indexOf(key) > -1) enterOff = true;
    else { seen.push(key); if (seen.length > 40) seen.shift(); store.set('seen', seen); }
  } else {
    if (ss && !M.from && M.nav === 'rise' && navType === 'push' && level === 'full' && !store.get('first')) {
      store.set('first', 1); if (store.get('first')) root.setAttribute('data-first', '');
    }
    store.set('first', 1);
  }
  if (enterOff) root.setAttribute('data-enter', 'off');
  M.entering = !enterOff && !reduced;

  /* ---- reveal: transition state, M.ready, tap policy */
  var shownAt = performance.now(), liveVT = null, revealed = !('onpagereveal' in w), domReady = d.readyState !== 'loading', queue = [];
  function flush() {
    if (!revealed || !domReady) return;
    var q = queue; queue = [];
    q.forEach(function (fn) { try { fn(M); } catch (e) { setTimeout(function () { throw e; }); } });
  }
  M.ready = function (fn) { queue.push(fn); flush(); };
  w.addEventListener('pagereveal', function (e) {
    var vt = e.viewTransition;
    shownAt = performance.now();
    if (restored) direction();
    if (vt && vt.ready) vt.ready.catch(function () {});   /* a skipped transition is not an error */
    if (vt && level === 'off') { vt.skipTransition(); vt = null; }
    if (vt) {
      liveVT = vt;
      root.setAttribute('data-vt', M.nav);
      if (M.nav === 'wipe') { root.setAttribute('data-enter', 'off'); M.entering = false; }   /* behind the blade the page stands still */
      var done = function () { if (liveVT === vt) { liveVT = null; root.removeAttribute('data-vt'); root.removeAttribute('data-away'); } };
      vt.finished.then(done, done);
    } else if (M.nav === 'wipe') { M.nav = 'fwd'; root.setAttribute('data-nav', 'fwd'); }
    restore();
    away(vt && (moved || navType !== 'push' || location.hash));   /* a fresh page stands at the top: no layout is forced to learn that */
    revealed = true; flush();
  });
  /* a scrolled page: its top bars are out of view. Unnamed (app.css), they fade in place instead of flying in */
  function away(may) { root.toggleAttribute('data-away', !!may && w.scrollY > 16); }
  w.addEventListener('pageswap', function (e) { away(e.viewTransition); });
  d.addEventListener('DOMContentLoaded', function () { domReady = true; if (revealed) shownAt = performance.now(); restore(); keptY = 0; flush(); });
  /* an impatient tap ends the transition; never forwarded */
  d.addEventListener('pointerdown', function () { if (liveVT) try { liveVT.skipTransition(); } catch (e) {} }, true);
  /* ghost-tap guard: bars sit at the same spot on consecutive pages. Stateless */
  d.addEventListener('click', function (e) {
    if (performance.now() - shownAt < 300 && e.target.closest && e.target.closest('.sticky, .btn, button')) { e.preventDefault(); e.stopImmediatePropagation(); }
  }, true);
  d.addEventListener('touchstart', function () {}, { passive: true });   /* iOS: paints :active at once */

  /* ---- status words: chip + polite live region. Both stand empty in base.html: a screen reader speaks only
     a change to a region that was already there (and nothing is inserted while the page arrives) */
  var chip = null, live = null, chipTimer = 0, sayTimer = 0;
  function words() {
    if (chip || !d.body) return;
    if (!d.getElementById('nav-live')) d.body.insertAdjacentHTML('beforeend', '<div id="nav-status" aria-hidden="true"></div><div id="nav-live" class="sr-only" role="status"></div>');
    chip = d.getElementById('nav-status'); live = d.getElementById('nav-live');
  }
  M.announce = function (text) { words(); if (live) live.textContent = text || ''; };
  M.status = function (text, ms, mute) {   /* mute: the chip only */
    words(); clearTimeout(chipTimer); if (!chip) return;
    chip.textContent = text || ''; if (!mute) M.announce(text);
    if (text && ms) chipTimer = setTimeout(function () { chip.textContent = ''; if (!mute) live.textContent = ''; }, ms);
  };

  /* ---- waiting: busy at once, pole at 300ms, words at 4s and 12s; one timer set */
  var timers = [];
  function later(fn, ms) { timers.push(setTimeout(fn, ms)); }
  function each(sel, fn) { [].forEach.call(d.querySelectorAll(sel), fn); }
  function busy(el) { el.classList.add('is-busy'); el.setAttribute('aria-busy', 'true'); }   /* never disabled: name=value must be posted */
  function idle(el) { el.classList.remove('is-busy', 'is-picked'); el.removeAttribute('aria-busy'); }
  function waiting(post) {
    reset(1);
    later(function () { root.classList.add('is-waiting'); }, 300);
    later(function () { M.status('Bağlanıyor…'); }, 4000);
    later(function () { M.status('Sunucu uyanıyor, birkaç saniye daha…'); }, 12000);
    if (!post) later(release, 15000);   /* a link can be tapped again; pole and words stay while the browser still loads */
    later(function () { reset(); M.status('Bağlantı kurulamadı. Tekrar deneyebilirsin.', 6000); }, 90000);
  }
  function release() {
    each('.is-busy, .is-picked, [aria-busy]', idle);
    each('form[data-busy]', function (f) { f.removeAttribute('data-busy'); });
  }
  function reset(keep) {   /* keep: a new wait, the marks stay */
    timers.forEach(clearTimeout); timers = [];
    root.classList.remove('is-waiting');
    clearTimeout(sayTimer);
    if (chip) { clearTimeout(chipTimer); chip.textContent = live.textContent = ''; }
    if (!keep) release();
  }
  /* a navigation the browser gave up (Stop): release now. An abort in its first second, or one that a newer
     navigation or the unload follows, is not that */
  var navSeq = 0;
  if (w.navigation) w.navigation.addEventListener('navigate', function (e) {
    var n = ++navSeq, t0 = Date.now();
    if (e.signal) e.signal.addEventListener('abort', function () {
      if (Date.now() - t0 > 1000) setTimeout(function () { if (n === navSeq && timers.length) { reset(); M.status('Yükleme durdu. Tekrar deneyebilirsin.', 6000); } }, 300);
    });
  });
  w.addEventListener('pageshow', function (e) {
    /* the first pageshow resets nothing: a tap made before load is still on its way */
    if (e.persisted) { reset(); restored = true; shownAt = performance.now(); root.setAttribute('data-enter', 'off'); root.removeAttribute('data-first'); M.entering = false; direction(); }
    d.dispatchEvent(new CustomEvent('motion:reset', { detail: { persisted: !!e.persisted } }));
  });
  function emit(name, target, detail) { target.dispatchEvent(new CustomEvent(name, { bubbles: true, detail: detail })); }
  /* g: the day or month shown here; the default URL carries none */
  function keepScroll() { store.set('scroll', { p: location.pathname, y: w.scrollY, t: Date.now(), g: (d.querySelector('input[name=g], [name=ay] [selected]') || root).getAttribute('value') }); }
  function formsOf(action) { return [].filter.call(d.forms, function (f) { return f.getAttribute('action') === action; }); }

  /* ---- links (bubble phase: whoever cancels the click has done so) */
  var lastSubmit = null, newTab = false, SUBMITS = 'button, input[type="submit"]';
  d.addEventListener('click', function (e) {
    var t = e.target; if (!t.closest) return;
    var sb = t.closest(SUBMITS); if (sb) { lastSubmit = sb; newTab = e.ctrlKey || e.metaKey || e.shiftKey; }
    if (e.defaultPrevented || e.button || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    var a = t.closest('a[href]');
    if (!a || (a.target && a.target !== '_self') || a.hasAttribute('download') || a.origin !== location.origin || /\.ics$/.test(a.pathname)) return;
    if (a.pathname === location.pathname && a.search === location.search && a.hash) return;
    each('a.is-busy', idle);
    if (a.classList.contains('btn')) busy(a);
    if (a.pathname === location.pathname) keepScroll();
    waiting(false);
    emit('motion:go', a, { link: a });
  });
  /* ---- forms (bubble phase: an inline confirm() has already answered) */
  d.addEventListener('submit', function (e) {
    var f = e.target, tg = f.getAttribute('target');
    if (e.defaultPrevented || (tg && tg !== '_self')) return;
    if (newTab && lastSubmit.form === f) { newTab = false; return; }   /* modifier click: the answer opens elsewhere */
    if (f.hasAttribute('data-busy')) { e.preventDefault(); return; }
    f.setAttribute('data-busy', '1');
    var post = (f.getAttribute('method') || '').toLowerCase() === 'post';
    var b = e.submitter || (lastSubmit && lastSubmit.form === f ? lastSubmit : null) || f.querySelector('button:not([type="button"]), input[type="submit"]');
    if (b) busy(b);
    if (post) {
      keepScroll();
      var a = f.getAttribute('action');   /* found again by action + order */
      if (b) store.set('btn', { p: location.pathname, a: a, f: formsOf(a).indexOf(f), b: [].indexOf.call(f.querySelectorAll(SUBMITS), b), x: b.textContent, t: Date.now() });
    }
    waiting(post);
    emit('motion:submit', f, { form: f, submitter: b, post: post });
  });
  /* onchange="this.form.submit()" fires no submit event */
  d.addEventListener('change', function (e) {
    var t = e.target; if (!t.getAttribute || !/submit\(\)/.test(t.getAttribute('onchange') || '')) return;
    keepScroll(); waiting(false); emit('motion:go', t, { link: null });
  });

  /* ---- same screen returns: keep the place, say the result, echo on the button */
  var kept = false, keptY = 0, moved = false, AGE = 95000;   /* just longer than the 90s POST guard */
  function restore() {
    if (!(domReady || d.getElementById('eof'))) return;
    if (kept) { if (keptY) w.scrollTo(0, keptY); return; }
    kept = true;
    var s = store.take('scroll'), b = store.take('btn'), now = Date.now(), here = location.pathname;
    var err = d.querySelector('.msgs li.error, .errorlist'), flash = d.querySelector('.msgs.flash');   /* standing warnings don't count */
    if (s && s.p === here && now - s.t < AGE && navType === 'push') {
      var er = err && !err.closest('.flash') && err.getBoundingClientRect();   /* a flash error is at the top */
      if (!err) { if (s.y > 0) { keptY = s.y; w.scrollTo(0, keptY); moved = true; } }
      else if (er && (er.top < 0 || er.bottom > w.innerHeight)) { err.scrollIntoView({ block: 'center' }); moved = true; }   /* a field error must be seen */
    }
    M.ready(function () {
      if (flash) {
        var r = flash.getBoundingClientRect(), text = [].map.call(flash.children, function (li) { return li.textContent; }).join(' ');
        if (r.bottom < 0 || r.top > w.innerHeight) M.status(text, 4000, 1);
        /* spoken a second after arrival, as a change of its own; then the copy goes */
        sayTimer = setTimeout(function () { M.announce(text); sayTimer = setTimeout(function () { if (live && live.textContent === text) live.textContent = ''; }, 6000); }, 1000);
      }
      var f = b && b.p === here && now - b.t < AGE && !err && M.full && d.querySelector('.msgs.flash li.success') && formsOf(b.a)[b.f];
      var btn = f && f.querySelectorAll(SUBMITS)[b.b];
      if (btn && btn.textContent === b.x && !btn.closest('[data-echo="off"]')) { btn.classList.add('is-done'); setTimeout(function () { btn.classList.remove('is-done'); }, 1600); }
    });
  }

  /* ---- one-shot hints for the next page */
  M.hint = function (name, data) { store.set('h:' + name, { d: data, p: location.pathname, t: Date.now() }); };
  M.takeHint = function (name, maxAge) { var h = store.take('h:' + name); return h && Date.now() - h.t < (maxAge || 20000) ? { data: h.d, path: h.p } : null; };

  /* ---- ustura bir sıra köpüğü siler: el is a positioned wrapper (.shave); nothing is left behind when it is done */
  M.shave = function (el, delay) {
    if (!M.full || !el || el.querySelector('.lather')) return;
    var l = d.createElement('i'), r = d.createElement('span');
    l.className = 'lather'; r.className = 'shave-run';
    r.innerHTML = '<svg class="shave-razor" viewBox="0 0 202 236" aria-hidden="true"><use href="#m-razor-shave"/></svg>';
    if (delay) { l.style.setProperty('--shave-delay', delay + 'ms'); r.style.setProperty('--shave-delay', delay + 'ms'); }
    el.classList.add('shave'); el.appendChild(l); el.appendChild(r);
    var gone = function () { l.remove(); r.remove(); };
    r.addEventListener('animationend', function (e) { if (e.target === r) gone(); });
    setTimeout(gone, (delay || 0) + 1600);   /* an animation that never ran still leaves nothing */
  };

  /* ---- numbers: Turkish format in ("1.600 ₺", "%42,8"), the server's exact string out */
  M.parse = function (text) {
    var m = /^(\D*?)(\d[\d.]*)(?:,(\d+))?(.*)$/.exec(String(text).trim()); if (!m) return null;
    return { pre: m[1], val: parseFloat(m[2].replace(/\./g, '') + (m[3] ? '.' + m[3] : '')), dec: m[3] ? m[3].length : 0, post: m[4] };
  };
  M.count = function (el, from, ms) {
    if (el._mEnd) el._mEnd();   /* a roll in progress: restore the server's string first */
    var final = el.textContent, n = M.parse(final); ms = ms || 600;
    if (!n || !M.full || !(from < n.val)) return false;   /* never downward, only with full motion */
    var t0 = 0, over = false;   /* tr-TR by hand: Intl's first use costs a frame */
    function fmt(v) { var p = v.toFixed(n.dec).split('.'); return p[0].replace(/\B(?=(\d{3})+$)/g, '.') + (p[1] ? ',' + p[1] : ''); }
    var end = el._mEnd = function () { if (!over) { over = true; el._mEnd = null; el.textContent = final; } };
    function step(t) {
      if (over) return; if (!t0) t0 = t;
      var k = Math.min(1, (t - t0) / ms), eased = 1 - Math.pow(1 - k, 4);
      if (k < 1) { el.textContent = n.pre + fmt(from + (n.val - from) * eased) + n.post; requestAnimationFrame(step); } else end();
    }
    el.textContent = n.pre + fmt(from) + n.post;
    requestAnimationFrame(step); setTimeout(end, ms + 400);   /* rAF may stall in a background tab */
    return true;
  };
})();
