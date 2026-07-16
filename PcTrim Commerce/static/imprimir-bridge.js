/**
 * Impressão: bridge local (PC Windows) + confirmação no servidor (Hostinger/Linux).
 */
(function () {
  var BRIDGE_BASE = window.LOJA_PRINT_BRIDGE || "http://127.0.0.1:9123";
  var cachedTerminalId = null;
  var cachedHealth = null;
  var lastBridgeError = null;
  var lastPrinterResolveError = null;
  var agentPopup = null;
  var agentReady = false;
  var printJobSeq = 0;

  function bridgeBase() {
    return BRIDGE_BASE.replace(/\/$/, "");
  }

  async function getBridgeHealth(forceRefresh) {
    if (!forceRefresh && cachedHealth && cachedHealth.ok) return cachedHealth;
    var url = bridgeBase() + "/health";
    lastBridgeError = null;
    try {
      var r = await fetch(url, { method: "GET", mode: "cors", cache: "no-store" });
      if (!r.ok) {
        cachedTerminalId = null;
        cachedHealth = null;
        lastBridgeError = "HTTP " + r.status + " em " + url;
        return null;
      }
      var d = await r.json().catch(function () {
        return {};
      });
      if (d && d.ok === true && d.terminal_id) {
        cachedTerminalId = String(d.terminal_id).trim();
        cachedHealth = d;
        return d;
      }
      cachedTerminalId = null;
      cachedHealth = null;
      lastBridgeError = "Resposta /health sem terminal_id.";
      return null;
    } catch (e) {
      cachedTerminalId = null;
      cachedHealth = null;
      var msg = String((e && e.message) || e || "Failed to fetch");
      if (/Failed to fetch|NetworkError|Load failed/i.test(msg)) {
        lastBridgeError =
          "Navegador bloqueou " +
          url +
          " (site VPS → localhost). Abra o Print Bridge, aceite acesso à rede local se o Chrome pedir, e tente de novo.";
      } else {
        lastBridgeError = msg;
      }
      return null;
    }
  }

  async function getBridgeTerminalId(forceRefresh) {
    if (!forceRefresh && cachedTerminalId) return cachedTerminalId;
    var d = await getBridgeHealth(!!forceRefresh);
    return d && d.terminal_id ? String(d.terminal_id).trim() : null;
  }

  function getLastBridgeError() {
    return lastBridgeError;
  }

  async function bridgeHealthOk() {
    return !!(await getBridgeTerminalId(false));
  }

  function applyPairedHealth(d) {
    if (!d || !d.terminal_id) return null;
    var health = {
      ok: true,
      terminal_id: String(d.terminal_id).trim(),
      impressoras_windows: Array.isArray(d.impressoras_windows) ? d.impressoras_windows : [],
      platform: d.platform || "",
      pywin32: !!d.pywin32,
    };
    cachedTerminalId = health.terminal_id;
    cachedHealth = health;
    lastBridgeError = null;
    return health;
  }

  /**
   * Contorna bloqueio Chrome (site VPS → 127.0.0.1): abre popup localhost /pair e recebe postMessage.
   */
  function pairBridge(timeoutMs) {
    timeoutMs = timeoutMs || 45000;
    return new Promise(function (resolve) {
      var url = bridgeBase() + "/pair";
      var done = false;
      var popup = null;
      var timer = null;

      function finish(health, err) {
        if (done) return;
        done = true;
        try {
          window.removeEventListener("message", onMsg);
        } catch (_e) {}
        if (timer) clearTimeout(timer);
        try {
          if (popup && !popup.closed) popup.close();
        } catch (_e2) {}
        if (err) {
          lastBridgeError = err;
          resolve(null);
        } else {
          resolve(applyPairedHealth(health));
        }
      }

      function onMsg(ev) {
        var d = ev && ev.data;
        if (!d || d.type !== "loja-print-bridge-pair") return;
        if (!d.ok || !d.terminal_id) {
          finish(null, "Pairing sem terminal_id.");
          return;
        }
        finish(d, null);
      }

      window.addEventListener("message", onMsg);
      try {
        popup = window.open(url, "lojaPrintBridgePair", "width=420,height=260");
      } catch (e) {
        finish(null, "Não foi possível abrir o popup do Print Bridge.");
        return;
      }
      if (!popup) {
        finish(
          null,
          "Popup bloqueado. Permita popups para este site e clique em Detectar Print Bridge de novo."
        );
        return;
      }
      timer = setTimeout(function () {
        finish(
          null,
          "Tempo esgotado no pairing. Confirme que iniciar-print-bridge.bat está aberto e tente Detectar de novo."
        );
      }, timeoutMs);
    });
  }

  async function getBridgeHealthOrPair(forceRefresh) {
    var h = await getBridgeHealth(!!forceRefresh);
    if (h) return h;
    return await pairBridge();
  }

  function ensureAgent(timeoutMs) {
    timeoutMs = timeoutMs || 20000;
    return new Promise(function (resolve) {
      if (agentPopup && !agentPopup.closed && agentReady) {
        resolve(true);
        return;
      }
      var done = false;
      var timer = null;
      var url = bridgeBase() + "/agent";

      function finish(ok, err) {
        if (done) return;
        done = true;
        try {
          window.removeEventListener("message", onMsg);
        } catch (_e) {}
        if (timer) clearTimeout(timer);
        if (!ok && err) lastBridgeError = err;
        resolve(!!ok);
      }

      function onMsg(ev) {
        var d = ev && ev.data;
        if (!d || d.type !== "loja-print-bridge-agent-ready") return;
        if (d.ok && d.terminal_id) applyPairedHealth(d);
        agentReady = true;
        finish(true, null);
      }

      window.addEventListener("message", onMsg);
      try {
        if (!agentPopup || agentPopup.closed) {
          agentReady = false;
          agentPopup = window.open(url, "lojaPrintBridgeAgent", "width=440,height=280");
        } else {
          try {
            agentPopup.location.href = url;
          } catch (_e2) {
            agentPopup = window.open(url, "lojaPrintBridgeAgent", "width=440,height=280");
          }
          agentReady = false;
        }
      } catch (e) {
        finish(false, "Não foi possível abrir o popup do Print Bridge Agent.");
        return;
      }
      if (!agentPopup) {
        finish(
          false,
          "Popup bloqueado. Permita popups para este site (Print Bridge Agent) e tente imprimir de novo."
        );
        return;
      }
      timer = setTimeout(function () {
        finish(
          false,
          "Print Bridge Agent não respondeu. Confirme iniciar-print-bridge.bat aberto e permita o popup."
        );
      }, timeoutMs);
    });
  }

  function printViaAgent(payload, timeoutMs) {
    timeoutMs = timeoutMs || 60000;
    return new Promise(function (resolve) {
      var jobId = "job-" + Date.now() + "-" + ++printJobSeq;
      var done = false;
      var timer = null;

      function finish(result) {
        if (done) return;
        done = true;
        try {
          window.removeEventListener("message", onMsg);
        } catch (_e) {}
        if (timer) clearTimeout(timer);
        resolve(result);
      }

      function onMsg(ev) {
        var d = ev && ev.data;
        if (!d || d.type !== "loja-print-bridge-print-result") return;
        if (String(d.jobId || "") !== jobId) return;
        finish({
          ok: !!d.ok,
          status: d.status || 0,
          data: d.data || {},
          printer: d.printer || payload.printer || null,
          erro: d.ok ? null : d.erro || "Agent recusou impressão.",
        });
      }

      window.addEventListener("message", onMsg);
      try {
        if (!agentPopup || agentPopup.closed) {
          finish({
            ok: false,
            status: 0,
            data: {},
            printer: payload.printer || null,
            erro: "Agent fechado. Tente imprimir de novo (popup).",
          });
          return;
        }
        agentPopup.postMessage(
          { type: "loja-print-bridge-print", jobId: jobId, payload: payload },
          "*"
        );
      } catch (e) {
        finish({
          ok: false,
          status: 0,
          data: {},
          printer: payload.printer || null,
          erro: "Falha ao enviar job ao agent: " + ((e && e.message) || e),
        });
        return;
      }
      timer = setTimeout(function () {
        finish({
          ok: false,
          status: 0,
          data: {},
          printer: payload.printer || null,
          erro: "Tempo esgotado aguardando o Print Bridge Agent.",
        });
      }, timeoutMs);
    });
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
    // Agent popup: contorna bloqueio Chrome (VPS → 127.0.0.1) e informa terminal_id no ready.
    var agentOk = await ensureAgent();
    if (!agentOk) {
      return {
        ok: false,
        status: 0,
        data: {},
        printer: null,
        erro:
          lastBridgeError ||
          "Print Bridge Agent indisponível. Abra iniciar-print-bridge.bat e permita o popup ao imprimir.",
      };
    }

    var terminalId = cachedTerminalId;
    var printer = String(body.printer || "").trim();
    if (!printer || /^https?:\/\//i.test(printer)) {
      printer = await resolvePrinterName(body);
    }
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

    // Fetch direto (ok em localhost); se Chrome bloquear, imprime via agent.
    var url = bridgeBase() + "/imprimir";
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
    } catch (_e) {
      return await printViaAgent(payload);
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
  window.lojaGetBridgeHealth = getBridgeHealth;
  window.lojaGetLastBridgeError = getLastBridgeError;
  window.lojaPairBridge = pairBridge;
  window.lojaGetBridgeHealthOrPair = getBridgeHealthOrPair;
  window.lojaImprimir = async function (body) {
    body = body || {};
    var origem = String(body.origem || "").trim().toLowerCase();
    if (origem === "preparo") {
      var iidPrep = parseInt(body.impressora_id, 10);
      if (!Number.isFinite(iidPrep) || iidPrep <= 0) {
        return {
          ok: false,
          status: 400,
          data: {
            erro:
              "Preparo exige impressora_id (setor). Cadastre imprenro no produto e na impressora.",
          },
        };
      }
    }

    var tidKnown = cachedTerminalId || (await getBridgeTerminalId(false));
    var bridgeContext = !!(tidKnown || agentReady || (agentPopup && !agentPopup.closed));

    if (body.impressora_id != null && !body.printer) {
      var p = await resolvePrinterName(body);
      if (p === null && body.impressora_id) {
        if (bridgeContext || tidKnown) {
          return {
            ok: false,
            status: 403,
            data: {
              erro:
                lastPrinterResolveError ||
                "Caminho local não resolvido para esta impressora neste terminal. Configure em Configurações > Impressão deste terminal.",
            },
          };
        }
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
      // Com Bridge/terminal: nunca cair em serverPrintOnly (evita impressão na VPS).
      if (bridgeContext || tidKnown || cachedTerminalId) {
        return {
          ok: false,
          status: br.status || 0,
          data: Object.assign({}, br.data, { erro: br.erro }),
          via: "bridge",
        };
      }
      return { ok: false, status: br.status, data: Object.assign({}, br.data, { erro: br.erro }) };
    }

    if (bridgeContext || tidKnown || cachedTerminalId) {
      return {
        ok: false,
        status: br.status || 0,
        data: {
          erro:
            br.erro ||
            "Falha na impressão via Print Bridge. Verifique o bat, o Agent e o mapeamento do terminal.",
        },
        via: "bridge",
      };
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
