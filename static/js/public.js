/* Hareket katmanı, müşteri tarafı (PUBLIC). Classic script at the end of <body>, after app.js.
   It only decorates: without it (or window.Motion) every page works and looks complete. */
(function () {
  'use strict';
  var M = window.Motion, d = document; if (!M) return;
  function each(sel, fn) { [].forEach.call(d.querySelectorAll(sel), fn); }

  /* P5/P7: the tapped day or hour answers at once. The only setter of .is-picked on this side, and it clears
     first: the transition name "pick" can never be on two elements. app.js removes the class on every pageshow. */
  var strip = d.querySelector('.days');
  d.addEventListener('motion:go', function (e) {
    var a = e.detail.link; if (!a || !a.matches('a.day, a.slot')) return;
    each('.day.is-picked, .slot.is-picked', function (el) { el.classList.remove('is-picked'); });
    a.classList.add('is-picked');
    if (strip && a.parentNode === strip) M.hint('days', strip.scrollLeft);
    else if (M.full) {   /* makas seçilen saatin köşesini keser (the hour is already bordo: the tap never waits) */
      if (!a.querySelector('.snip')) a.insertAdjacentHTML('beforeend', '<i class="offcut"></i><svg class="snip" viewBox="-12.5 -8 25 16" aria-hidden="true">' +
        '<g class="sc-b"><path class="io" d="M-11,.15L0,0L4.5,-2"/><circle class="io" cx="7.3" cy="-3.5" r="2.8"/></g>' +
        '<g class="sc-a"><path class="io" d="M-11,-.15L0,0L4.5,2"/><circle class="io" cx="7.3" cy="3.5" r="2.8"/></g><circle class="ii" r=".9"/></svg>');
      a.classList.add('just-picked');
    }
  });
  d.addEventListener('motion:reset', function () { each('.slot.just-picked', function (el) { el.classList.remove('just-picked'); }); });
  /* levha kendini çizer, makas kesik çizgiyi keser: ekrana girince, bir kez */
  if (M.full && 'IntersectionObserver' in window) {
    var io = new IntersectionObserver(function (es) {
      es.forEach(function (e) { if (e.isIntersecting) { e.target.classList.remove('is-wait'); e.target.classList.add('is-in'); io.unobserve(e.target); } });
    }, { threshold: .5 });
    each('.draw:not(.on-load), .cut:not(.perf)', function (el) { el.classList.add('is-wait'); io.observe(el); });
  }
  /* ustura, tarak ve makas ekrandayken durmadan çalışır; "Durdur" hepsini bekletir (seçim oturum boyunca kalır).
     html[data-loops] is the only switch of these loops and is set here alone, with full motion. */
  var loops = d.querySelectorAll('.loop'), doc = d.documentElement;
  if (M.full && loops.length && 'IntersectionObserver' in window) {
    var seen = new IntersectionObserver(function (es) {
      es.forEach(function (e) { e.target.classList.toggle('is-live', e.isIntersecting); });
    }, { rootMargin: '48px 0px' });
    var setLoops = function (off) {
      doc.setAttribute('data-loops', off ? 'off' : 'on');
      each('.loop-toggle', function (b) {
        b.textContent = off ? 'Oynat' : 'Durdur';
        b.setAttribute('aria-label', off ? 'Çizimlerin hareketini oynat' : 'Çizimlerin hareketini durdur');   /* the visible word is in the name */
      });
    };
    [].forEach.call(loops, function (el) {
      seen.observe(el);
      var fig = el.closest('figure'), cap = fig && fig.querySelector('figcaption');
      if (!cap) return;
      /* the drawing and its caption stay decorative, the button does not */
      var text = d.createElement('span'); text.setAttribute('aria-hidden', 'true');
      while (cap.firstChild) text.appendChild(cap.firstChild);
      cap.appendChild(text); fig.removeAttribute('aria-hidden'); el.setAttribute('aria-hidden', 'true');
      var b = d.createElement('button'); b.type = 'button'; b.className = 'loop-toggle'; cap.appendChild(b);
      b.addEventListener('click', function () {
        var off = doc.getAttribute('data-loops') !== 'off';
        M.store.set('loops', off ? 'off' : 'on'); setLoops(off);
      });
    });
    setLoops(M.store.get('loops') === 'off');
  }
  /* gün değişince ustura yeni günün adını açar */
  M.ready(function () { if (M.nav === 'same' && M.from === 'time') M.shave(d.querySelector('[data-shave]'), 160); });
  /* P5: after a day change the strip stands where it stood; otherwise the chosen day is brought into view
     (CSS scroll-initial-target where it exists). Only scrollLeft is written: scrollIntoView could move the page. */
  var on = strip && strip.querySelector('.day.on');
  if (on) {
    var kept = M.takeHint('days'), box = function () { return on.getBoundingClientRect().left - strip.getBoundingClientRect().left; };
    if (kept && kept.path === location.pathname) strip.scrollLeft = kept.data;
    else if (!(window.CSS && CSS.supports && CSS.supports('scroll-initial-target', 'nearest'))) strip.scrollLeft += box() - (strip.clientWidth - on.offsetWidth) / 2;
    var left = box(), over = left + on.offsetWidth - strip.clientWidth;
    if (left < 0) strip.scrollLeft += left; else if (over > 0) strip.scrollLeft += over;
  }

  /* Model seçilince bağlı işlem işaretlenir (müşteri istemezse kaldırabilir). Hareketten bağımsız: her düzeyde. */
  d.addEventListener('change', function (e) {
    var r = e.target; if (!r.matches || !r.matches('input[name="m"]') || !r.checked) return;
    var id = r.getAttribute('data-service'), box = id && d.querySelector('input[name="h"][value="' + id + '"]');
    if (box && !box.checked) { box.checked = true; box.dispatchEvent(new Event('change', { bubbles: true })); }
  });

  /* P3 live total on "Devam et" (flag live-total). Like the server, it counts the first six ticked services. */
  var picks = d.querySelectorAll('.pick input[name="h"]'), cta = picks.length && picks[0].form && picks[0].form.querySelector('.sticky .btn');
  if (cta && M.flag('live-total')) {
    var label = cta.textContent;
    var total = function () {
      var dk = 0, tl = 0, n = 0;
      [].forEach.call(picks, function (i) {
        if (!i.checked || n > 5) return;
        var box = i.nextElementSibling, s = box && box.querySelector('small'), p = box && box.lastElementChild && M.parse(box.lastElementChild.textContent);
        n++; dk += parseInt(s ? s.textContent : '', 10) || 0; tl += p ? p.val : 0;
      });
      cta.textContent = n ? label + ' · ' + dk + ' dk · ' + String(tl).replace(/\B(?=(\d{3})+$)/g, '.') + ' ₺' : label;
    };
    [].forEach.call(picks, function (i) { i.addEventListener('change', total); });
    d.addEventListener('motion:reset', total); total();
  }

  /* P8 code: the underline follows the digits; the value is only ever read. Self-send (flag auto-code, off as
     shipped): once per document, from real input, never from a value that was already there. */
  var code = d.querySelector('input.code-input');
  if (code) {
    var sent = false, digits = function () { return code.value.replace(/\D/g, '').length; };
    var paint = function () { var n = Math.min(6, digits()); code.style.setProperty('--n', n); code.classList.toggle('is-full', n === 6); };
    code.addEventListener('input', function (e) {
      paint();
      if (!M.flag('auto-code') || sent || !e.isTrusted || digits() !== 6 || !code.form || !code.form.requestSubmit || d.querySelector('form[data-busy]')) return;
      sent = true;
      setTimeout(function () { if (digits() === 6 && !d.querySelector('form[data-busy]')) code.form.requestSubmit(); }, 260);
    });
    d.addEventListener('motion:reset', paint); paint();
    /* a failed "Tekrar gönder" is not a wrong code: no red field, no shake */
    d.addEventListener('motion:submit', function (e) { if (e.detail.form !== code.form) M.hint('calm', 1); });
    if (M.takeHint('calm')) code.classList.add('is-calm');
  }
})();
