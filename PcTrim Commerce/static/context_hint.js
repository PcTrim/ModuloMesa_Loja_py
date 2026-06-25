(function () {
  'use strict';

  var bar = null;
  var textEl = null;
  var hideTimer = null;

  var TONE_CLASSES = ['is-error', 'is-success'];

  function getBar() {
    if (bar) return bar;
    bar = document.getElementById('context-hint-bar');
    textEl = document.getElementById('context-hint-text');
    return bar;
  }

  function isHintField(el) {
    if (!el || el.disabled) return false;
    var tag = el.tagName;
    if (tag !== 'INPUT' && tag !== 'SELECT' && tag !== 'TEXTAREA') return false;
    if (tag === 'INPUT' && String(el.type || '').toLowerCase() === 'hidden') return false;
    var hint = el.getAttribute('data-hint');
    return hint && String(hint).trim().length > 0;
  }

  function setTone(tone) {
    var node = getBar();
    if (!node) return;
    TONE_CLASSES.forEach(function (cls) { node.classList.remove(cls); });
    if (tone === 'error') node.classList.add('is-error');
    else if (tone === 'success') node.classList.add('is-success');
  }

  function show(text, options) {
    var node = getBar();
    if (!node || !textEl || !text) return;
    options = options || {};
    if (hideTimer) {
      clearTimeout(hideTimer);
      hideTimer = null;
    }
    setTone(options.tone || 'info');
    textEl.textContent = String(text).trim();
    node.removeAttribute('hidden');
    node.setAttribute('aria-hidden', 'false');
    requestAnimationFrame(function () {
      node.classList.add('is-visible');
    });
  }

  function hide() {
    var node = getBar();
    if (!node) return;
    node.classList.remove('is-visible');
    node.setAttribute('aria-hidden', 'true');
    hideTimer = setTimeout(function () {
      if (!node.classList.contains('is-visible')) {
        node.setAttribute('hidden', '');
        textEl.textContent = '';
        setTone('info');
      }
      hideTimer = null;
    }, 200);
  }

  function showFromField(el) {
    if (!isHintField(el)) return;
    show(el.getAttribute('data-hint'), { tone: 'info' });
  }

  document.addEventListener('focusin', function (e) {
    var field = e.target && e.target.closest ? e.target.closest('[data-hint]') : null;
    if (field && isHintField(field)) showFromField(field);
  });

  document.addEventListener('focusout', function () {
    requestAnimationFrame(function () {
      var active = document.activeElement;
      if (active && isHintField(active)) {
        showFromField(active);
        return;
      }
      hide();
    });
  });

  window.LojaContextHint = {
    show: show,
    hide: hide
  };
})();
