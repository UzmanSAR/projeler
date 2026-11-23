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
  });
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
