/**
 * Impressão: bridge local (PC Windows) + confirmação no servidor (Hostinger/Linux).
 */
(function () {
  var BRIDGE_BASE = window.LOJA_PRINT_BRIDGE || "http://127.0.0.1:9123";
  var cachedTerminalId = null;
  var lastPrinterResolveError = null;

  async function getBridgeTerminalId(forceRefresh) {
    if (!forceRefresh && cachedTerminalId) return cachedTerminalId;
    var url = BRIDGE_BASE.replace(/\/$/, "") + "/health";
    try {
      var r = await fetch(url, { method: "GET", mode: "cors", cache: "no-store" });
      if (!r.ok) {
        cachedTerminalId = null;
        return null;
      }
      var d = await r.json().catch(function () {
        return {};
      });
      if (d && d.ok === true && d.terminal_id) {
        cachedTerminalId = String(d.terminal_id).trim();
        return cachedTerminalId || null;
      }
    } catch (_e) {
      cachedTerminalId = null;
    }
    return null;
  }

  async function bridgeHealthOk() {
    return !!(await getBridgeTerminalId(false));
  }

  function mergeHeaders(extra) {
    var h = { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" };
    if (extra) {
      Object.keys(extra).forEach(function (k) {
        h[k] = extra[k];
      });
    }
    return h;
  }

  function pickErro(d, fallback) {
    if (!d || typeof d !== "object") return fallback;
    return d.erro || d.mensagem || d.message || fallback;
  }

  function flagSim(v) {
    return ["S", "SIM", "1", "Y", "YES", "T", "TRUE"].indexOf(String(v || "").toUpperCase()) >= 0;
  }

  function printerFromRow(row) {
    if (!row) return null;
    var cam = String(row.caminho || "").trim();
    if (cam && /^https?:\/\//i.test(cam)) cam = "";
    var nome = String(row.nomedaimpressora || "").trim();
    // Mesma regra do servidor (get_printer_from_db): caminho tem prioridade
    return (cam || nome) || null;
  }

  async function resolvePrinterName(body) {
    body = body || {};
    lastPrinterResolveError = null;
    var origem = body.origem || "casa";
    var terminalId = await getBridgeTerminalId(false);
    if (terminalId) {
      try {
        var u =
          "/api/impressora-para-origem?origem=" +
          encodeURIComponent(origem) +
          "&terminal_id=" +
          encodeURIComponent(terminalId);
        if (body.impressora_id != null && String(body.impressora_id).trim() !== "") {
          u += "&impressora_id=" + encodeURIComponent(String(body.impressora_id).trim());
        }
        var rT = await fetch(u, { credentials: "same-origin" });
        var dT = await rT.json().catch(function () {
          return {};
        });
        if (rT.ok && dT.sucesso && dT.printer) {
          var pT = String(dT.printer).trim();
          if (!/^https?:\/\//i.test(pT)) return pT;
        }
        lastPrinterResolveError = pickErro(
          dT,
          "Não foi possível resolver impressora para este terminal."
        );
        return null;
      } catch (eT) {
        lastPrinterResolveError = String((eT && eT.message) || eT || "Erro ao resolver impressora.");
        return null;
      }
    }
    if (body.impressora_id != null && String(body.impressora_id).trim() !== "") {
      var urlList = "/api/impressoras-cadastro";
      try {
        var rList = await fetch(urlList, { credentials: "same-origin" });
        var dList = await rList.json().catch(function () {
          return {};
        });
        var list = dList.impressoras || [];
        var iid = parseInt(body.impressora_id, 10);
        for (var i = 0; i < list.length; i++) {
          if (Number(list[i].id) === iid) {
            return printerFromRow(list[i]);
          }
        }
      } catch (_e) {}
    }
    try {
      var u = "/api/impressora-para-origem?origem=" + encodeURIComponent(origem);
      var r = await fetch(u, { credentials: "same-origin" });
      var d = await r.json().catch(function () {
        return {};
      });
      if (r.ok && d.sucesso && d.printer) {
        var p = String(d.printer).trim();
        if (!/^https?:\/\//i.test(p)) return p;
        return null;
      }
    } catch (_e2) {}
    var urlCad = "/api/impressoras-cadastro";
    try {
      var r2 = await fetch(urlCad, { credentials: "same-origin" });
      var d2 = await r2.json().catch(function () {
        return {};
      });
      var rows = d2.impressoras || [];
      var wantMesa = origem === "mesa" || body.conta_mesa;
      for (var j = 0; j < rows.length; j++) {
        if (wantMesa && flagSim(rows[j].conta_mesa)) return printerFromRow(rows[j]);
        if (!wantMesa && flagSim(rows[j].comanda_delivery)) return printerFromRow(rows[j]);
      }
    } catch (_e3) {}
    return null;
  }

  async function tryBridgePrint(body) {
    var terminalId = await getBridgeTerminalId(false);
    var printer = await resolvePrinterName(body);
    if (!printer) {
      if (lastPrinterResolveError) {
        return {
          ok: false,
          status: 403,
          data: {},
          printer: null,
          erro: lastPrinterResolveError,
        };
      }
      var origem = body.origem || "casa";
      var flag =
        origem === "mesa" || body.conta_mesa
          ? "conta_mesa = 'S'"
          : "comanda_delivery = 'S'";
      return {
        ok: false,
        status: 0,
        data: {},
        printer: null,
        erro:
          "Nenhuma impressora no cadastro para esta tela (" +
          flag +
          " na tabela impressoras). Atualize nomedaimpressora/caminho no MySQL.",
      };
    }
    var payload = Object.assign({}, body);
    payload.printer = printer;
    if (terminalId) payload.terminal_id = terminalId;
    if (!(await bridgeHealthOk())) {
      return {
        ok: false,
        status: 0,
        data: {},
        printer: printer,
        erro:
          "Print Bridge OFF neste PC. Duplo clique em deploy\\print_bridge\\iniciar-print-bridge.bat " +
          "e deixe a janela aberta. Teste no navegador: " +
          BRIDGE_BASE.replace(/\/$/, "") +
          "/health",
      };
    }
    var url = BRIDGE_BASE.replace(/\/$/, "") + "/imprimir";
    try {
      var r = await fetch(url, {
        method: "POST",
        mode: "cors",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      var d = await r.json().catch(function () {
        return {};
      });
      var ok = r.ok && d.sucesso !== false;
      return {
        ok: ok,
        status: r.status,
        data: d,
        printer: d.printer || printer,
        erro: ok ? null : pickErro(d, "Bridge recusou impressão (HTTP " + r.status + ")"),
      };
    } catch (e) {
      return {
        ok: false,
        status: 0,
        data: {},
        printer: printer,
        erro:
          "Print Bridge OFF neste PC. Abra iniciar-print-bridge.bat e teste " +
          BRIDGE_BASE.replace(/\/$/, "") +
          "/health no navegador.",
      };
    }
  }

  function apiUrl(path) {
    if (typeof lojaUrl === "function") return lojaUrl(path);
    var b = window.LOJA_BASE || "";
    if (!b && typeof location !== "undefined") {
      var m = (location.pathname || "").match(/^(\/LojaOnline)/i);
      if (m) b = m[1];
    }
    if (!path) return b || "/";
    if (/^https?:\/\//i.test(path)) return path;
    if (path.charAt(0) !== "/") path = "/" + path;
    return (b || "") + path;
  }

  function apiFullUrl(path) {
    var rel = apiUrl(path);
    if (typeof location !== "undefined" && location.origin) {
      return location.origin.replace(/\/$/, "") + (rel.charAt(0) === "/" ? rel : "/" + rel);
    }
    return rel;
  }

  function stripControlForServer(s) {
    return String(s || "").replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, "");
  }

  async function confirmOnServer(body, printerUsed) {
    var payload = Object.assign({}, body, {
      printer: printerUsed || body.printer || "",
    });
    var terminalId = await getBridgeTerminalId(false);
    if (terminalId) payload.terminal_id = terminalId;
    if (payload && typeof payload === "object" && payload.conteudo != null) {
      payload.conteudo = stripControlForServer(payload.conteudo);
    }
    var tentativas = [
      { path: "/api/casa/confirmar-impressao", extra: {} },
      { path: "/imprimir", extra: { apenas_confirmar: true } },
    ];
    var ultimo = null;
    for (var t = 0; t < tentativas.length; t++) {
      var url = apiFullUrl(tentativas[t].path);
      var bodySend = Object.assign({}, payload, tentativas[t].extra);
      try {
        var r = await fetch(url, {
          method: "POST",
          credentials: "same-origin",
          headers: mergeHeaders(),
          body: JSON.stringify(bodySend),
        });
        if (r.status === 404 && t < tentativas.length - 1) {
          ultimo = { status: 404, erro: "Rota " + tentativas[t].path + " não encontrada (404)." };
          continue;
        }
        var d = await r.json().catch(function () {
          return { _parse_fail: true, _status: r.status };
        });
        var ok = r.ok && d.sucesso !== false;
        if (ok) {
          return { ok: true, status: r.status, data: d, erro: null };
        }
        ultimo = {
          status: r.status,
          erro: pickErro(
            d,
            d._parse_fail
              ? "Servidor HTTP " + r.status + " em " + tentativas[t].path + " (faça login de novo ou atualize app.py no servidor)."
              : "Falha ao confirmar (HTTP " + r.status + ")"
          ),
          data: d,
        };
        if (r.status !== 404) break;
      } catch (e) {
        ultimo = { status: 0, erro: "Rede: " + ((e && e.message) || e), data: {} };
      }
    }
    return {
      ok: false,
      status: ultimo ? ultimo.status : 0,
      data: (ultimo && ultimo.data) || {},
      erro: (ultimo && ultimo.erro) || "Falha ao confirmar no servidor.",
    };
  }

  async function serverPrintOnly(body) {
    var url = apiUrl("/imprimir");
    try {
      var r = await fetch(url, {
        method: "POST",
        credentials: "same-origin",
        headers: mergeHeaders(),
        body: JSON.stringify(body),
      });
      var d = await r.json().catch(function () {
        return {};
      });
      var ok = r.ok && d.sucesso !== false;
      return {
        ok: ok,
        status: r.status,
        data: d,
        erro: ok ? null : pickErro(d, "Servidor HTTP " + r.status),
      };
    } catch (e) {
      return { ok: false, status: 0, data: {}, erro: "Rede: " + ((e && e.message) || e) };
    }
  }

  window.lojaGetBridgeTerminalId = getBridgeTerminalId;
  window.lojaImprimir = async function (body) {
    body = body || {};
    if (body.impressora_id != null && !body.printer) {
      var p = await resolvePrinterName(body);
      if (p === null && body.impressora_id) {
        return serverPrintOnly(body).then(function (srv) {
          return {
            ok: srv.ok,
            status: srv.status,
            data: Object.assign({}, srv.data, { erro: srv.erro }),
          };
        });
      }
    }

    var br = await tryBridgePrint(body);
    if (body && body.skip_confirm) {
      return {
        ok: br.ok,
        status: br.status,
        data: Object.assign({}, br.data, {
          erro: br.ok ? null : br.erro,
          printer: br.printer,
          printer_windows: (br.data && br.data.printer_windows) || br.printer,
          via: "bridge",
        }),
        via: "bridge",
      };
    }
    if (br.ok) {
      var conf = await confirmOnServer(body, br.printer);
      if (conf.ok) {
        return {
          ok: true,
          status: conf.status,
          data: Object.assign({}, conf.data, {
            printer: br.printer,
            printer_windows: (br.data && br.data.printer_windows) || br.printer,
            via: "bridge",
          }),
          via: "bridge",
        };
      }
      return {
        ok: false,
        status: conf.status,
        data: {
          erro:
            "Cupom impresso no PC, porém: " +
            (conf.erro || "falha ao confirmar no servidor."),
          bridge_ok: true,
        },
      };
    }

    if (br.erro && !br.ok) {
      return { ok: false, status: br.status, data: Object.assign({}, br.data, { erro: br.erro }) };
    }

    var srv = await serverPrintOnly(body);
    if (srv.ok) {
      return { ok: true, status: srv.status, data: srv.data, via: srv.data.via || "servidor" };
    }
    var err = srv.erro || br.erro || "Falha na impressão.";
    if (String(err).indexOf("linux") >= 0) {
      err =
        "Abra iniciar-print-bridge.bat neste PC e tente de novo. (O servidor não imprime direto.)";
    }
    return { ok: false, status: srv.status || br.status, data: Object.assign({}, srv.data, { erro: err }) };
  };
})();
