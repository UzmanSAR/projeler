/* Hareket katmanı, PANEL. Classic script at the end of <body>, after app.js. Pages are complete without it. */
(function () {
  'use strict';
  var M = window.Motion, d = document; if (!M) return;
  var all = function (sel) { return [].slice.call(d.querySelectorAll(sel)); };
  var tabs = d.querySelector('.tabs');

  /* N1: label and ink answer at tap time (the ink follows .is-picked in panel.css) */
  d.addEventListener('motion:go', function (e) {
    var a = e.detail.link; if (!a || !tabs || a.parentNode !== tabs) return;
    var at = tabs.querySelector('.is-picked') || tabs.querySelector('.on');
    if (at) at.classList.remove('is-picked');
    a.classList.add('is-picked');
    M.hint('ink', { f: [].indexOf.call(tabs.children, at), t: Date.now() });
  });

  /* N2 N3 N4: what the screen showed at the press */
  d.addEventListener('motion:submit', function (e) {
    var f = e.detail.form, b = e.detail.submitter, act = f.getAttribute('action') || '', card = f.closest('.appt');
    if (!e.detail.post) return;
    if (card && /\/kapat\/$/.test(act) && b && b.value)
      M.hint('till', { k: all('.kpi > b').map(function (x) { return x.textContent; }), id: card.getAttribute('data-appt'), s: b.value });
    if (/\/randevusuz\/$/.test(act)) M.hint('cards', all('.appt[data-appt]').map(function (x) { return x.getAttribute('data-appt'); }));
  });

  M.ready(function () {
    var here = location.pathname, failed = d.querySelector('.msgs.flash li.error');
    /* N1: the answer came before the ink arrived: it finishes its 300ms here, no jump */
    var ink = M.takeHint('ink', 2000), dt = ink ? Date.now() - ink.data.t : -1;
    if (M.full && tabs && dt >= 0 && dt < 300 && ink.data.f > -1 && getComputedStyle(tabs, '::before').content !== 'none') try {
      var an = tabs.animate({ transform: 'translateX(' + ink.data.f * 100 + '%)', offset: 0 },
        { pseudoElement: '::before', duration: 300, delay: -dt, easing: getComputedStyle(tabs).getPropertyValue('--e-soft').trim() });
      if (!an.effect || an.effect.pseudoElement !== '::before') an.cancel();   /* never the real bar */
    } catch (err) {}

    /* N2: the till rolls only after a close, only upward (M.count refuses the rest) */
    var h = M.takeHint('till');
    if (h && h.path === here && M.full && !failed) {
      all('.kpi > b').forEach(function (b, i) {
        var old = M.parse(h.data.k[i] || ''), now = M.parse(b.textContent), end = b.textContent; if (!old || !now) return;
        if (i || !(now.val > old.val)) { M.count(b, old.val, 600); return; }
        var r = b.getBoundingClientRect(), lab = b.parentNode.querySelector('small'), name = lab ? lab.textContent : '';
        M.announce(name + ' ' + end);
        if (r.bottom > 0 && r.top < innerHeight) { M.count(b, old.val, 600); b.parentNode.classList.add('is-up'); return; }
        var till = d.createElement('div'), tb = d.createElement('b');   /* tile out of view */
        till.className = 'till'; till.setAttribute('aria-hidden', 'true');
        till.appendChild(d.createElement('small')).textContent = name;
        till.appendChild(tb).textContent = end;
        d.body.appendChild(till);
        tb.style.minWidth = tb.offsetWidth + 'px'; tb.textContent = h.data.k[0];   /* old figure first */
        setTimeout(function () { tb.textContent = end; M.count(tb, old.val, 700); }, 200);
        setTimeout(function () { till.remove(); }, 2600);
      });
      var card = h.data.id && d.querySelector('.appt[data-appt="' + h.data.id + '"]');
      if (card && h.data.s === 'completed' && card.classList.contains('completed')) card.classList.add('just-done');   /* N3 */
    }
    var c = M.takeHint('cards');   /* N4 */
    if (c && c.path === here && M.full) {
      var fresh = all('.appt[data-appt]').filter(function (x) { return c.data.indexOf(x.getAttribute('data-appt')) < 0; });
      if (fresh.length < 3) fresh.forEach(function (x) { x.classList.add('just-added'); });
    }

    /* N8. A filter change is "same" for CORE (gate closed) unless the month moved: for a new URL the drawing opens here */
    if (M.screen === 'report') {
      var seen = M.store.get('pan:rep') || [], key = location.search, unseen = seen.indexOf(key) < 0, main = d.querySelector('main'), draw = M.entering;
      if (unseen) { seen.push(key); M.store.set('pan:rep', seen.slice(-40)); }
      if (!draw && unseen && M.full && M.nav === 'same' && main && M.store.get('pan:rep')) { main.classList.add('is-drawn'); draw = 1; }   /* no storage: still */
      if (draw) all('.kpi > b').forEach(function (b) { M.count(b, 0, 500); });
    }

    /* N7: a still "now" line; scale from the first two axis labels */
    var marks = all('.cal .axis span'), g = d.querySelector('input[type="date"][name="g"]'), lanes = all('.cal .lane');
    if (M.flag('now-line') && marks.length > 1 && g && lanes.length) {
      var t = new Date(), iso = new Date(t - t.getTimezoneOffset() * 6e4).toISOString().slice(0, 10);   /* local date */
      var mm = function (el) { var p = el.textContent.split(':'); return p[0] * 60 + +p[1]; }, top = function (el) { return parseFloat(el.style.top); };
      var y = top(marks[0]) + (t.getHours() * 60 + t.getMinutes() - mm(marks[0])) * (top(marks[1]) - top(marks[0])) / (mm(marks[1]) - mm(marks[0]));
      if (g.value === iso && y >= 0 && y <= lanes[0].offsetHeight) lanes.forEach(function (lane, i) {
        var line = lane.appendChild(d.createElement('i')), ms = 520 / Math.min(lanes.length, 4);   /* one stroke, lane after lane */
        line.className = 'now'; line.setAttribute('aria-hidden', 'true');
        line.style.cssText = 'top:' + y + 'px;animation-duration:' + ms + 'ms;animation-delay:' + (300 + i * ms) + 'ms';
      });
    }
  });

  /* N9: tap the booking link to copy it */
  if (M.flag('copy-link') && navigator.clipboard) all('.linkbox[data-copy]').forEach(function (box) {
    var timer = 0, copy = function () {
      navigator.clipboard.writeText(box.textContent.trim()).then(function () {
        box.classList.remove('is-copied'); void box.offsetWidth; box.classList.add('is-copied'); M.status('Kopyalandı', 1600);
        clearTimeout(timer); timer = setTimeout(function () { box.classList.remove('is-copied'); }, 1600);
      }, function () { M.status('Kopyalanamadı', 1600); });
    };
    box.setAttribute('role', 'button'); box.setAttribute('tabindex', '0');
    box.setAttribute('aria-label', 'Randevu linkini kopyala: ' + box.textContent.trim());
    box.addEventListener('click', copy);
    box.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); copy(); } });
  });
})();
