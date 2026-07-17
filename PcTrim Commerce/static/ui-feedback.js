/**
 * Feedback não bloqueante para PDV (toast + confirm nativo).
 * Uso: window.uiFeedback.success|warn|error|confirm
 */
(function () {
  var MAX_TOASTS = 3;
  var DEDUPE_MS = 1800;
  var host = null;
  var lastMsg = "";
  var lastAt = 0;
  var styleReady = false;

  function ensureStyle() {
    if (styleReady) return;
    styleReady = true;
    var css =
      "#ui-feedback-host{position:fixed;z-index:99999;right:16px;bottom:16px;display:flex;flex-direction:column;gap:8px;max-width:min(420px,calc(100vw - 24px));pointer-events:none;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;}" +
      ".ui-fb-toast{pointer-events:auto;padding:12px 14px;border-radius:10px;box-shadow:0 8px 24px rgba(0,0,0,.18);color:#fff;font-size:14px;line-height:1.35;white-space:pre-wrap;word-break:break-word;opacity:0;transform:translateY(8px);transition:opacity .18s ease,transform .18s ease;}" +
      ".ui-fb-toast.show{opacity:1;transform:translateY(0);}" +
      ".ui-fb-toast.success{background:#1f7a4d;}" +
      ".ui-fb-toast.warn{background:#9a6b00;}" +
      ".ui-fb-toast.error{background:#a12622;}" +
      ".ui-fb-toast .ui-fb-close{float:right;margin:-2px 0 0 10px;border:0;background:transparent;color:inherit;opacity:.85;cursor:pointer;font-size:16px;line-height:1;}";
    var el = document.createElement("style");
    el.setAttribute("data-ui-feedback", "1");
    el.textContent = css;
    (document.head || document.documentElement).appendChild(el);
  }

  function ensureHost() {
    ensureStyle();
    if (host && host.parentNode) return host;
    host = document.getElementById("ui-feedback-host");
    if (!host) {
      host = document.createElement("div");
      host.id = "ui-feedback-host";
      host.setAttribute("aria-live", "polite");
      (document.body || document.documentElement).appendChild(host);
    }
    return host;
  }

  function prune() {
    var h = ensureHost();
    while (h.children.length > MAX_TOASTS) {
      h.removeChild(h.firstChild);
    }
  }

  function isDupe(msg) {
    var now = Date.now();
    if (msg === lastMsg && now - lastAt < DEDUPE_MS) return true;
    lastMsg = msg;
    lastAt = now;
    return false;
  }

  function showToast(kind, message, ttlMs) {
    var msg = String(message == null ? "" : message).trim();
    if (!msg) return;
    if (isDupe(kind + ":" + msg)) return;
    var h = ensureHost();
    var toast = document.createElement("div");
    toast.className = "ui-fb-toast " + kind;
    toast.setAttribute("role", kind === "error" ? "alert" : "status");
    var close = document.createElement("button");
    close.type = "button";
    close.className = "ui-fb-close";
    close.setAttribute("aria-label", "Fechar");
    close.textContent = "×";
    close.onclick = function () {
      dismiss(toast);
    };
    toast.appendChild(close);
    toast.appendChild(document.createTextNode(msg));
    h.appendChild(toast);
    prune();
    requestAnimationFrame(function () {
      toast.classList.add("show");
    });
    if (ttlMs > 0) {
      setTimeout(function () {
        dismiss(toast);
      }, ttlMs);
    }
  }

  function dismiss(toast) {
    if (!toast || !toast.parentNode) return;
    toast.classList.remove("show");
    setTimeout(function () {
      if (toast.parentNode) toast.parentNode.removeChild(toast);
    }, 200);
  }

  function success(message) {
    showToast("success", message, 2500);
  }

  function warn(message) {
    showToast("warn", message, 4000);
  }

  function error(message, opts) {
    opts = opts || {};
    var msg = String(message == null ? "" : message);
    if (opts.blocking) {
      try {
        window.alert(msg);
      } catch (_e) {}
      return;
    }
    showToast("error", msg, opts.sticky ? 0 : 8000);
  }

  function confirmFn(message) {
    try {
      return window.confirm(String(message == null ? "" : message));
    } catch (_e) {
      return false;
    }
  }

  window.uiFeedback = {
    success: success,
    warn: warn,
    error: error,
    confirm: confirmFn,
  };
})();
