/**
 * Etiqueta térmica CODE128 (ESC/POS) — retail.
 * Uso: buildBarcodeLabel({ chave, produto|nome, barcode }) → { ok, conteudo, erro }
 *
 * Layout: "chave  produto" + barras CODE128 do campo barcode (sem HRI).
 */
(function (global) {
  var WIDTH = 42;
  var MAX_BARCODE = 50;

  function toStr(v) {
    return String(v == null ? "" : v);
  }

  function center(s, width) {
    var w = width || WIDTH;
    s = toStr(s).trim();
    if (!s) return "";
    if (s.length >= w) return s.slice(0, w);
    var pad = w - s.length;
    var left = Math.floor(pad / 2);
    return " ".repeat(left) + s + " ".repeat(pad - left);
  }

  function truncateName(s, maxLen) {
    s = toStr(s).replace(/\s+/g, " ").trim();
    if (!s) return "";
    if (s.length <= maxLen) return s;
    if (maxLen <= 3) return s.slice(0, maxLen);
    return s.slice(0, maxLen - 3) + "...";
  }

  /** Linha: chave + produto (campos da tabela). */
  function titleChaveProduto(chave, produto, width) {
    var w = width || WIDTH;
    var chaveStr = toStr(chave).trim();
    var gap = "  ";
    var prefix = chaveStr ? chaveStr + gap : "";
    var maxNome = Math.max(8, w - prefix.length);
    var name = truncateName(produto, maxNome);
    var line = prefix + name;
    if (line.length > w) line = line.slice(0, w);
    return center(line, w);
  }

  /** CODE128 Set B: ASCII imprimível 32–126. */
  function validateBarcode(raw) {
    var code = toStr(raw).trim();
    if (!code) {
      return { ok: false, erro: "Informe o código de barras antes de imprimir" };
    }
    if (code.length > MAX_BARCODE) {
      return { ok: false, erro: "Código de barras deve ter no máximo " + MAX_BARCODE + " caracteres." };
    }
    for (var i = 0; i < code.length; i++) {
      var c = code.charCodeAt(i);
      if (c < 32 || c > 126) {
        return {
          ok: false,
          erro: "Código de barras com caracteres inválidos. Use apenas letras, números e símbolos ASCII.",
        };
      }
    }
    return { ok: true, barcode: code };
  }

  /**
   * GS k 73 — CODE128 Set B ({B + dados).
   * GS H 0 = sem HRI (evita segundo número / "{B" na etiqueta).
   */
  function escposCode128(barcode) {
    var data = "{B" + barcode;
    var n = data.length;
    if (n > 255) {
      return null;
    }
    return (
      "\x1d\x68\x5a" + // GS h 90
      "\x1d\x77\x02" + // GS w 2
      "\x1d\x48\x00" + // GS H 0 — sem texto sob as barras
      "\x1d\x6b\x49" + // GS k 73
      String.fromCharCode(n) +
      data
    );
  }

  function buildBarcodeLabel(product) {
    product = product || {};
    var check = validateBarcode(product.barcode);
    if (!check.ok) {
      return { ok: false, conteudo: "", erro: check.erro };
    }
    var barcode = check.barcode;
    var produtoNome = product.produto || product.nome || "";
    if (!toStr(produtoNome).trim()) {
      return { ok: false, conteudo: "", erro: "Informe o nome do produto antes de imprimir." };
    }
    var chave = product.chave;
    if (chave == null || toStr(chave).trim() === "") {
      return { ok: false, conteudo: "", erro: "Informe o código (chave) do produto antes de imprimir." };
    }

    var bars = escposCode128(barcode);
    if (!bars) {
      return { ok: false, conteudo: "", erro: "Código de barras muito longo para CODE128." };
    }

    var parts = [
      "\x1b\x61\x01", // ESC a 1 — centro
      titleChaveProduto(chave, produtoNome, WIDTH),
      "",
      bars,
      "",
      "\x1b\x64\x03", // ESC d 3 — feed
      "\x1b\x61\x00", // ESC a 0 — esquerda
    ];

    return { ok: true, conteudo: parts.join("\n"), erro: null };
  }

  global.buildBarcodeLabel = buildBarcodeLabel;
  global.lojaBarcodeLabel = {
    build: buildBarcodeLabel,
    validate: validateBarcode,
    width: WIDTH,
  };
})(window);
