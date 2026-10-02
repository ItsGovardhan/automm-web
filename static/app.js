// Copy buttons
document.addEventListener('click', function (e) {
  var btn = e.target.closest('[data-copy]');
  if (!btn) return;
  var text = btn.getAttribute('data-copy');
  function done() {
    btn.classList.add('copied');
    var label = btn.querySelector('.copy-label');
    var old = label ? label.textContent : null;
    if (label) label.textContent = 'Copied';
    setTimeout(function () {
      btn.classList.remove('copied');
      if (label) label.textContent = old;
    }, 1500);
  }
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text).then(done);
  } else {
    var ta = document.createElement('textarea');
    ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta); ta.select();
    try { document.execCommand('copy'); done(); } catch (err) {}
    document.body.removeChild(ta);
  }
});

// Deal page: payment aate hi page khud refresh ho jaye
(function () {
  var box = document.querySelector('[data-watch]');
  if (!box) return;
  var url = box.getAttribute('data-watch');
  var last = box.getAttribute('data-state');
  setInterval(function () {
    if (document.hidden) return;
    var a = document.activeElement;
    if (a && (a.tagName === 'INPUT' || a.tagName === 'TEXTAREA')) return;
    fetch(url, { headers: { 'Accept': 'application/json' }, credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) {
        if (!j) return;
        var now = j.status + '|' + j.pay_state + '|' + j.received;
        if (now !== last) location.reload();
      })
      .catch(function () {});
  }, 8000);
})();
