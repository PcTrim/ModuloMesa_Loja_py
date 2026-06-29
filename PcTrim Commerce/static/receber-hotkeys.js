(function (global) {
  var handlers = [];
  var bound = false;

  function isEndKey(ev) {
    return ev && (ev.key === "End" || ev.code === "End");
  }

  function safeCall(fn) {
    try {
      return fn();
    } catch (_e) {
      return false;
    }
  }

  function register(cfg) {
    if (!cfg || !cfg.id) return;
    handlers = handlers.filter(function (h) {
      return h.id !== cfg.id;
    });
    handlers.push(cfg);
    ensureBound();
  }

  function ensureBound() {
    if (bound) return;
    bound = true;
    document.addEventListener(
      "keydown",
      function (ev) {
        if (!isEndKey(ev)) return;
        var target = ev.target;
        for (var i = 0; i < handlers.length; i++) {
          var h = handlers[i];
          if (!safeCall(function () {
            return h.enabled !== false && (!h.enabled || h.enabled());
          })) {
            continue;
          }
          if (!safeCall(function () {
            return h.isActive && h.isActive();
          })) {
            continue;
          }
          if (!safeCall(function () {
            return h.isValueInput && h.isValueInput(target);
          })) {
            continue;
          }
          if (!safeCall(function () {
            return h.canConfirm && h.canConfirm();
          })) {
            return;
          }
          ev.preventDefault();
          ev.stopPropagation();
          if (h.syncBeforeConfirm) safeCall(h.syncBeforeConfirm);
          if (h.onConfirm) safeCall(h.onConfirm);
          return;
        }
      },
      true
    );
  }

  global.lojaReceberHotkeys = {
    register: register,
  };
})(window);
