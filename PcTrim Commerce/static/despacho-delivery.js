(function () {
  "use strict";

  function el(id) {
    return document.getElementById(id);
  }

  function fmtMoney(n) {
    try {
      return new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(Number(n) || 0);
    } catch (_) {
      return String(n);
    }
  }

  async function fetchJson(url, opts) {
    const r = await fetch(
      url,
      Object.assign(
        {
          credentials: "same-origin",
          headers: { Accept: "application/json" },
        },
        opts || {}
      )
    );
    const ct = (r.headers.get("content-type") || "").toLowerCase();
    const data = ct.includes("application/json") ? await r.json().catch(function () { return {}; }) : {};
    return { r: r, data: data };
  }

  function setMsg(text, ok) {
    var m = el("despacho-msg");
    if (!m) return;
    m.textContent = text || "";
    m.className = "despacho-msg" + (ok ? " ok" : "");
  }

  function close() {
    var root = el("despacho-delivery-modal");
    if (!root) return;
    root.hidden = true;
    document.body.style.overflow = "";
  }

  function preselectPedido(nropedido) {
    var n = Number(nropedido) || 0;
    if (!n) return;
    var inp = document.querySelector(
      '#despacho-pedidos-list input[name="despacho-pedido"][value="' + n + '"]'
    );
    if (inp) {
      inp.checked = true;
      selectedNropedido = n;
      try {
        inp.focus();
      } catch (_) {}
    } else {
      setMsg(
        "Este pedido não aparece na lista de despacho (confirme se é DELIVERY com todas as linhas em ABERTO).",
        false
      );
    }
  }

  function open(prefNropedido) {
    var root = el("despacho-delivery-modal");
    if (!root) return;
    root.hidden = false;
    document.body.style.overflow = "hidden";
    var pref = Number(prefNropedido) || 0;
    loadData().then(function () {
      if (pref) preselectPedido(pref);
    });
  }

  var selectedNropedido = null;

  function renderPedidos(pedidos) {
    var host = el("despacho-pedidos-list");
    if (!host) return;
    selectedNropedido = null;
    if (!pedidos || !pedidos.length) {
      host.innerHTML = '<div style="padding:12px;font-weight:600;color:var(--muted,#888);">Nenhum pedido delivery em ABERTO para despacho.</div>';
      return;
    }
    host.innerHTML = pedidos
      .map(function (p) {
        var nro = Number(p.nropedido) || 0;
        var tel = (p.telefone || "").trim();
        var cli = (p.cliente || "").trim();
        var nom = (p.nome || "").trim();
        var resumo = [tel && "Tel. " + tel, cli || nom].filter(Boolean).join(" · ") || "—";
        var tot = fmtMoney(p.total_valor);
        return (
          '<label class="despacho-row">' +
          '<input type="radio" name="despacho-pedido" value="' +
          nro +
          '">' +
          "<div><strong>#" +
          nro +
          "</strong><small>" +
          resumo +
          " · " +
          tot +
          "</small></div></label>"
        );
      })
      .join("");
    host.querySelectorAll('input[name="despacho-pedido"]').forEach(function (inp) {
      inp.addEventListener("change", function () {
        selectedNropedido = Number(inp.value) || null;
      });
    });
  }

  function renderEntregadores(list) {
    var sel = el("despacho-select-entregador");
    if (!sel) return;
    sel.innerHTML = "";
    if (!list || !list.length) {
      var o = document.createElement("option");
      o.value = "";
      o.textContent = "— Sem entregadores cadastrados —";
      sel.appendChild(o);
      return;
    }
    var ph = document.createElement("option");
    ph.value = "";
    ph.textContent = "— Escolha o entregador —";
    sel.appendChild(ph);
    list.forEach(function (e) {
      var opt = document.createElement("option");
      opt.value = String(e.chave);
      opt.textContent = "#" + e.chave + " — " + (e.nome || "—");
      sel.appendChild(opt);
    });
  }

  async function loadData() {
    setMsg("", false);
    var host = el("despacho-pedidos-list");
    if (host) host.innerHTML = "Carregando…";
    var sel = el("despacho-select-entregador");
    if (sel) sel.innerHTML = '<option value="">— Carregando —</option>';

    try {
      var pRes = await fetchJson("/api/delivery-pedidos-despacho");
      var eRes = await fetchJson("/api/listar-entregadores");
      if (!pRes.r.ok || !pRes.data.sucesso) {
        renderPedidos([]);
        setMsg((pRes.data && pRes.data.erro) || "Erro ao listar pedidos.", false);
      } else {
        renderPedidos(pRes.data.pedidos || []);
      }
      if (!eRes.r.ok || !eRes.data.sucesso) {
        renderEntregadores([]);
        if (!pRes.r.ok || !pRes.data.sucesso) {
          setMsg((eRes.data && eRes.data.erro) || "Erro ao listar entregadores.", false);
        }
      } else {
        renderEntregadores(eRes.data.entregadores || []);
      }
    } catch (err) {
      setMsg("Falha de rede ao carregar dados.", false);
      if (host) host.innerHTML = "";
    }
  }

  async function onConfirm() {
    setMsg("", false);
    var cod = el("despacho-select-entregador");
    var codigo = cod ? Number(cod.value || 0) : 0;
    if (!selectedNropedido) {
      setMsg("Selecione um pedido.", false);
      return;
    }
    if (!codigo) {
      setMsg("Selecione um entregador.", false);
      return;
    }
    var btn = el("despacho-btn-confirmar");
    if (btn) btn.disabled = true;
    try {
      var res = await fetchJson("/api/despachar-delivery", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ nropedido: selectedNropedido, codigo_entregador: codigo }),
      });
      if (res.r.ok && res.data.sucesso) {
        setMsg(res.data.mensagem || "Despacho concluído.", true);
        await loadData();
        try {
          document.dispatchEvent(new CustomEvent("lojaonline:delivery-despachado", { detail: { nropedido: selectedNropedido } }));
        } catch (_) {}
        setTimeout(close, 900);
      } else {
        setMsg((res.data && res.data.erro) || "Não foi possível despachar.", false);
      }
    } catch (_) {
      setMsg("Erro de rede ao despachar.", false);
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  window.LojaOnlineDespachoDelivery = { open: open, close: close, reload: loadData };

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-despacho-open]").forEach(function (b) {
      b.addEventListener("click", function (e) {
        e.preventDefault();
        open();
      });
    });
    var root = el("despacho-delivery-modal");
    if (root) {
      root.querySelectorAll("[data-despacho-close]").forEach(function (x) {
        x.addEventListener("click", function (e) {
          e.preventDefault();
          close();
        });
      });
    }
    var c = el("despacho-btn-confirmar");
    if (c) c.addEventListener("click", onConfirm);
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") {
        var root = el("despacho-delivery-modal");
        if (root && !root.hidden) close();
      }
    });
  });
})();
