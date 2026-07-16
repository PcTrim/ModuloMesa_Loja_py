(function (global) {
  function toStr(v) {
    return String(v == null ? "" : v);
  }

  function clampWidth(w) {
    var n = Number(w);
    if (!isFinite(n) || n <= 0) return 48;
    n = Math.floor(n);
    if (n < 32) return 32;
    if (n > 64) return 64;
    return n;
  }

  function rpad(s, n) {
    s = toStr(s);
    if (s.length >= n) return s;
    return s + " ".repeat(n - s.length);
  }

  function lpad(s, n) {
    s = toStr(s);
    if (s.length >= n) return s;
    return " ".repeat(n - s.length) + s;
  }

  function hr(ch, width) {
    var w = clampWidth(width);
    var c = toStr(ch || "-").slice(0, 1) || "-";
    return c.repeat(w);
  }

  function center(s, width) {
    var w = clampWidth(width);
    s = toStr(s).trim();
    if (!s) return "";
    if (s.length >= w) return s.slice(0, w);
    var pad = w - s.length;
    var left = Math.floor(pad / 2);
    var right = pad - left;
    return " ".repeat(left) + s + " ".repeat(right);
  }

  function wrap(s, width, indent) {
    var w = clampWidth(width);
    var ind = Math.max(0, Math.min(12, Number(indent) || 0));
    var prefix = ind ? " ".repeat(ind) : "";
    var text = toStr(s).replace(/\s+/g, " ").trim();
    if (!text) return [];
    var max = Math.max(10, w - prefix.length);
    var words = text.split(" ");
    var out = [];
    var line = "";
    for (var i = 0; i < words.length; i++) {
      var word = words[i];
      if (!word) continue;
      if (!line) {
        line = word;
        continue;
      }
      if ((line + " " + word).length <= max) {
        line = line + " " + word;
      } else {
        out.push(prefix + line);
        line = word;
      }
    }
    if (line) out.push(prefix + line);
    return out;
  }

  function cols(left, right, width, minGap) {
    var w = clampWidth(width);
    var gap = Number(minGap);
    if (!isFinite(gap) || gap < 1) gap = 1;
    if (gap > 6) gap = 6;
    var L = toStr(left);
    var R = toStr(right);
    if (!R) return L.length <= w ? L : L.slice(0, w);
    if (R.length >= w) return R.slice(0, w);
    var maxLeft = w - R.length - gap;
    if (maxLeft < 0) maxLeft = 0;
    if (L.length > maxLeft) {
      if (maxLeft <= 1) L = "";
      else L = L.slice(0, Math.max(0, maxLeft - 1)) + "…";
    }
    return rpad(L, w - R.length) + R;
  }

  function moneyClean(s) {
    var t = toStr(s).trim();
    if (!t) return "";
    return t.replace(/\s+/g, " ");
  }

  function kv(label, value, width) {
    var w = clampWidth(width);
    var L = toStr(label || "").trim();
    var V = moneyClean(value);
    return cols(L, V, w, 1);
  }

  function blockTitle(title, width) {
    var w = clampWidth(width);
    var t = toStr(title).trim();
    if (!t) return [];
    return [hr("-", w), center(t, w), hr("-", w)];
  }

  function normFormato(v) {
    return toStr(v).trim().toLowerCase() === "simples" ? "simples" : "completa";
  }

  function isSimples(formato) {
    return normFormato(formato) === "simples";
  }

  /** ESC ! 0 + GS ! 0 — fecha bloco de tamanho em impressoras ESC/POS. */
  function sizeReset() {
    return "\x1b!\x00\x1d!\x00";
  }

  /** Título grande: completa = ESC ! 0x30; simples = só padding central. */
  function bigTitle(s, formato, width) {
    var t = toStr(s);
    if (isSimples(formato)) return center(t, width);
    return "\x1b!\x30" + t + sizeReset();
  }

  /** Ênfase média (altura dupla 0x10): completa = ESC; simples = texto. */
  function midTitle(s, formato, width) {
    var t = toStr(s);
    if (isSimples(formato)) return width != null ? center(t, width) : t;
    return "\x1b!\x10" + t + sizeReset();
  }

  function boldText(s, formato) {
    var t = toStr(s);
    if (isSimples(formato)) return t;
    return "\x1bE\x01" + t + "\x1bE\x00";
  }

  /** ESC a 1/0 — só no perfil completa. */
  function alignCenterCmd(on, formato) {
    if (isSimples(formato)) return "";
    return on ? "\x1ba\x01" : "\x1ba\x00";
  }

  global.lojaPrintFmt = {
    width: clampWidth,
    hr: hr,
    center: center,
    wrap: wrap,
    cols: cols,
    kv: kv,
    blockTitle: blockTitle,
    normFormato: normFormato,
    isSimples: isSimples,
    sizeReset: sizeReset,
    bigTitle: bigTitle,
    midTitle: midTitle,
    boldText: boldText,
    alignCenterCmd: alignCenterCmd,
  };
})(window);

