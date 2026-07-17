(function (global) {
  var cacheLoja = null;
  var cacheLojaPromise = null;
  var metaCache = {};

  function apiUrl(path) {
    if (typeof global.lojaUrl === "function") return global.lojaUrl(path);
    return path;
  }

  function trimStr(v) {
    return String(v == null ? "" : v).trim();
  }

  function fmtCtx() {
    var F = global.lojaPrintFmt || {};
    var W = F.width ? F.width(48) : 48;
    var ESC = "\x1b";
    return {
      F: F,
      W: W,
      ESC: ESC,
      hr: function (ch) {
        return F.hr ? F.hr(ch, W) : String(ch || "-").slice(0, 1).repeat(W);
      },
      center: function (s) {
        return F.center ? F.center(s, W) : String(s || "");
      },
      wrap: function (s, indent) {
        return F.wrap ? F.wrap(s, W, indent || 0) : [String(s || "")];
      },
      kv: function (l, v) {
        return F.kv ? F.kv(l, v, W) : String(l || "") + ": " + String(v || "");
      },
    };
  }

  function formatPrintDateTime(isoOrDate) {
    var d = isoOrDate instanceof Date ? isoOrDate : null;
    if (!d && isoOrDate) {
      var s = String(isoOrDate);
      d = new Date(s);
      if (isNaN(d.getTime()) && s.indexOf("T") === -1) {
        d = new Date(s.replace(" ", "T"));
      }
    }
    if (!d || isNaN(d.getTime())) d = new Date();
    try {
      return d.toLocaleString("pt-BR", {
        timeZone: "America/Sao_Paulo",
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch (_e) {
      return d.toISOString().slice(0, 16).replace("T", " ");
    }
  }

  function resolveAtendente(meta, ctx) {
    var m = meta || {};
    var c = ctx || global.LOJA_PRINT_CTX || {};
    return trimStr(m.atendente) || trimStr(c.usuario) || "-";
  }

  function resolveDataHora(meta) {
    var m = meta || {};
    if (trimStr(m.data_hora)) return trimStr(m.data_hora);
    if (m.data_criacao) return formatPrintDateTime(m.data_criacao);
    return formatPrintDateTime(new Date());
  }

  function formatCnpj(raw) {
    var d = String(raw || "").replace(/\D/g, "");
    if (d.length === 14) {
      return d.replace(/^(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})$/, "$1.$2.$3/$4-$5");
    }
    return trimStr(raw);
  }

  function formatTelefoneLoja(loja) {
    var tel = trimStr(loja && loja.telefone);
    if (!tel) return "";
    var digits = tel.replace(/\D/g, "");
    var ddd = trimStr(loja && loja.ddd).replace(/\D/g, "");
    if (digits.length >= 10 && !ddd) return tel;
    if (ddd && digits) {
      if (digits.indexOf(ddd) === 0) return tel;
      return "(" + ddd + ") " + tel;
    }
    return tel;
  }

  function buildEnderecoLinha(loja) {
    if (!loja) return "";
    var parts = [];
    var end = trimStr(loja.endereco);
    if (end) parts.push(end);
    var bairro = trimStr(loja.bairro);
    var cidade = trimStr(loja.cidade);
    if (bairro) parts.push(bairro);
    if (cidade && parts.indexOf(cidade) < 0) parts.push(cidade);
    return parts.join(" - ");
  }

  function pushOptionalLines(out, ctx, label, value, indent) {
    var v = trimStr(value);
    if (!v) return;
    var line = label ? label + ": " + v : v;
    if (line.length <= ctx.W) {
      out.push(ctx.center(line));
      return;
    }
    if (label) out.push(ctx.center(label + ":"));
    ctx.wrap(v, indent || 0).forEach(function (ln) {
      if (trimStr(ln)) out.push(ln);
    });
  }

  function ensureLojaDados() {
    if (cacheLoja) return Promise.resolve(cacheLoja);
    if (cacheLojaPromise) return cacheLojaPromise;
    cacheLojaPromise = fetch(apiUrl("/api/dados-loja-info"), { credentials: "same-origin" })
      .then(function (r) {
        return r.json().catch(function () {
          return {};
        });
      })
      .then(function (d) {
        cacheLoja = (d && d.sucesso && d.dados) || {};
        return cacheLoja;
      })
      .catch(function () {
        cacheLoja = {};
        return cacheLoja;
      });
    return cacheLojaPromise;
  }

  function metaCacheKey(nropedido, origem) {
    return String(nropedido || 0) + "|" + String(origem || "").toUpperCase();
  }

  function refreshPrintMeta(nropedido, origem) {
    var nro = Number(nropedido) || 0;
    var orig = String(origem || "DELIVERY").toUpperCase();
    if (nro <= 0) {
      var fallback = {
        data_criacao: new Date().toISOString(),
        data_hora: formatPrintDateTime(new Date()),
        atendente: resolveAtendente({}, global.LOJA_PRINT_CTX),
      };
      return Promise.resolve(fallback);
    }
    var url =
      apiUrl("/api/impressao-meta") +
      "?nropedido=" +
      encodeURIComponent(String(nro)) +
      "&origem=" +
      encodeURIComponent(orig);
    return fetch(url, { credentials: "same-origin" })
      .then(function (r) {
        return r.json().catch(function () {
          return {};
        });
      })
      .then(function (d) {
        var meta = {
          data_criacao: (d && d.data_criacao) || new Date().toISOString(),
          data_hora: (d && d.data_hora) || formatPrintDateTime((d && d.data_criacao) || new Date()),
          atendente: resolveAtendente(d, global.LOJA_PRINT_CTX),
          atendente_chave: d && d.atendente_chave,
        };
        metaCache[metaCacheKey(nro, orig)] = meta;
        return meta;
      })
      .catch(function () {
        var meta = {
          data_criacao: new Date().toISOString(),
          data_hora: formatPrintDateTime(new Date()),
          atendente: resolveAtendente({}, global.LOJA_PRINT_CTX),
        };
        metaCache[metaCacheKey(nro, orig)] = meta;
        return meta;
      });
  }

  function getCachedPrintMeta(nropedido, origem) {
    return metaCache[metaCacheKey(nropedido, origem)] || null;
  }

  function setPrintMeta(nropedido, origem, meta) {
    if (!meta) return;
    metaCache[metaCacheKey(nropedido, origem)] = meta;
  }

  function buildPrintHeaderFull(opts) {
    opts = opts || {};
    var loja = opts.loja || cacheLoja || {};
    var meta = opts.meta || {};
    var ctx = fmtCtx();
    var F = ctx.F;
    var formato = F.normFormato ? F.normFormato(opts.formato) : "completa";
    var simples = F.isSimples ? F.isSimples(formato) : false;
    var out = [];
    var nome = trimStr(loja.nome) || "Minha Loja";

    if (!simples) out.push(ctx.ESC + "a" + String.fromCharCode(1));
    if (F.bigTitle) {
      out.push(F.bigTitle(nome, formato, ctx.W));
    } else {
      out.push(
        ctx.ESC +
          "!" +
          String.fromCharCode(0x30) +
          nome +
          ctx.ESC +
          "!" +
          String.fromCharCode(0x00)
      );
    }
    if (!simples) out.push(ctx.ESC + "a" + String.fromCharCode(0));

    var cnpj = formatCnpj(loja.cnpj);
    if (cnpj) pushOptionalLines(out, ctx, "CNPJ", cnpj, 0);

    var endereco = buildEnderecoLinha(loja);
    if (endereco) pushOptionalLines(out, ctx, "", endereco, 0);

    var contato = formatTelefoneLoja(loja);
    if (contato) pushOptionalLines(out, ctx, "Tel", contato, 0);

    out.push(ctx.hr("-"));

    var titulo = trimStr(opts.tituloPedido);
    if (titulo) {
      if (!simples) out.push(ctx.ESC + "a" + String.fromCharCode(1));
      if (F.bigTitle) {
        out.push(F.bigTitle(titulo, formato, ctx.W));
      } else {
        out.push(
          ctx.ESC +
            "!" +
            String.fromCharCode(0x30) +
            titulo +
            ctx.ESC +
            "!" +
            String.fromCharCode(0x00)
        );
      }
      if (!simples) out.push(ctx.ESC + "a" + String.fromCharCode(0));
    }

    var atendente = resolveAtendente(meta, global.LOJA_PRINT_CTX);
    var dataHora = resolveDataHora(meta);
    out.push("Atendente: " + atendente);
    out.push("Data/hora: " + dataHora);
    out.push(ctx.hr("-"));

    return out;
  }

  function buildPrintHeaderPreparo(opts) {
    opts = opts || {};
    var meta = opts.meta || {};
    var ctx = fmtCtx();
    var out = [];
    var atendente = resolveAtendente(meta, global.LOJA_PRINT_CTX);
    var dataHora = resolveDataHora(meta);
    var linha = dataHora + " | Atend: " + atendente;
    if (linha.length <= ctx.W) out.push(linha);
    else {
      out.push(dataHora);
      out.push("Atend: " + atendente);
    }
    out.push(ctx.hr("-"));
    return out;
  }

  global.lojaPrintHeader = {
    ensureLojaDados: ensureLojaDados,
    refreshPrintMeta: refreshPrintMeta,
    getCachedPrintMeta: getCachedPrintMeta,
    setPrintMeta: setPrintMeta,
    formatPrintDateTime: formatPrintDateTime,
    buildPrintHeaderFull: buildPrintHeaderFull,
    buildPrintHeaderPreparo: buildPrintHeaderPreparo,
  };
})(window);
