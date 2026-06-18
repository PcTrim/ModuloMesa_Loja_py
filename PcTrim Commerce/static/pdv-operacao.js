(() => {
  const state = {
    mesa: null,
    modo: "mesa",
    classificacao: null,
    produtos: [],
  };

  const el = (id) => document.getElementById(id);
  const money = (n) => `R$ ${Number(n || 0).toFixed(2)}`;

  function setModo(modo) {
    state.modo = modo;
    document.querySelectorAll("[data-modo]").forEach((b) => b.classList.toggle("active", b.dataset.modo === modo));
    const d = el("delivery-form");
    if (d) d.style.display = modo === "delivery" ? "grid" : "none";
  }

  async function loadMesas() {
    const wrap = el("mesas-grid");
    if (!wrap) return;
    const res = await fetch("/api/mesa-todos");
    const data = await res.json();
    const mesas = Array.isArray(data) ? data : (data.registros || data.mesas || []);
    wrap.innerHTML = "";
    mesas.forEach((m) => {
      const card = document.createElement("button");
      card.className = "pdv-card";
      card.style.width = "48px";
      card.style.height = "48px";
      card.style.padding = "4px";
      const st = String(m.status_mesa || m.status || "").toUpperCase();
      const isConta = st === "CONTA" || st === "CONTA-PEDIDA";
      card.style.borderTop = `3px solid ${isConta ? "#f59e0b" : (m.ocupada ? "#10b981" : "#2a2a40")}`;
      card.innerHTML = `<div style="font-size:11px;font-weight:800;">${m.mesanro || m.mesa || "-"}</div><div style="font-size:10px;color:#10b981;">${money(m.total || 0)}</div>`;
      card.onclick = () => selectMesa(m.mesanro || m.mesa);
      wrap.appendChild(card);
    });
  }

  async function selectMesa(mesa) {
    state.mesa = mesa;
    const badge = el("mesa-badge");
    if (badge) badge.textContent = `Mesa ${mesa}`;
    await loadItensMesa();
  }

  async function loadItensMesa() {
    if (!state.mesa) return;
    const res = await fetch(`/api/mesa/${state.mesa}`);
    const data = await res.json();
    const itens = data.itens || data.items || [];
    const list = el("itens-list");
    if (!list) return;
    list.innerHTML = "";
    let subtotal = 0;
    itens.forEach((it) => {
      subtotal += Number(it.total || it.valor || (it.preco * (it.qtd || 1)) || 0);
      const row = document.createElement("div");
      row.className = "pdv-card";
      row.style.padding = "6px";
      row.innerHTML = `<div style="display:flex;justify-content:space-between;gap:6px;"><span style="font-size:12px">${it.produto || it.nome || "-"}</span><button class="pdv-btn pdv-btn-outline" style="padding:2px 6px;" data-del="${it.id || it.item_id || 0}">×</button></div><div style="font-size:11px;color:#9ca3b0">${(it.obs || "").trim()}</div><div style="font-size:11px;color:#10b981">${money(it.total || it.preco || 0)}</div>`;
      list.appendChild(row);
    });
    const serv = subtotal * 0.1;
    el("subtotal") && (el("subtotal").textContent = money(subtotal));
    el("servico") && (el("servico").textContent = money(serv));
    el("total") && (el("total").textContent = money(subtotal + serv));

    list.querySelectorAll("[data-del]").forEach((b) => {
      b.onclick = async () => {
        const id = b.getAttribute("data-del");
        if (!id || !state.mesa) return;
        await fetch(`/api/mesa/${state.mesa}/item/${id}`, { method: "DELETE" });
        await loadItensMesa();
      };
    });
  }

  async function loadClassificacoes() {
    const res = await fetch("/api/listar-classificacoes");
    const data = await res.json();
    const list = Array.isArray(data) ? data : (data.classificacoes || []);
    const wrap = el("class-tabs");
    if (!wrap) return;
    wrap.innerHTML = "";
    list.forEach((c, i) => {
      const nome = c.nome || c.classificacao || c.descricao || `Classe ${i + 1}`;
      const b = document.createElement("button");
      b.className = "pdv-pill";
      b.textContent = nome;
      b.onclick = () => loadProdutos(nome);
      wrap.appendChild(b);
      if (i === 0) loadProdutos(nome);
    });
  }

  async function loadProdutos(classificacao) {
    state.classificacao = classificacao;
    const res = await fetch(`/produtos_por_classificacao/${encodeURIComponent(classificacao)}`);
    const data = await res.json();
    state.produtos = Array.isArray(data) ? data : (data.produtos || []);
    renderProdutos();
  }

  function renderProdutos() {
    const q = (el("busca-produto")?.value || "").toLowerCase().trim();
    const wrap = el("prod-grid");
    if (!wrap) return;
    wrap.innerHTML = "";
    state.produtos.filter((p) => (p.produto || p.nome || "").toLowerCase().includes(q)).forEach((p) => {
      const card = document.createElement("div");
      card.className = "pdv-card";
      card.innerHTML = `<div style="font-size:12px;font-weight:700">${p.produto || p.nome}</div><div style="font-size:12px;color:#10b981">${money(p.preco)}</div><button class="pdv-btn pdv-btn-purple" style="width:100%;margin-top:6px">+</button>`;
      card.querySelector("button").onclick = () => addItem(p);
      wrap.appendChild(card);
    });
  }

  async function addItem(p) {
    if (!state.mesa) return alert("Selecione uma mesa.");
    await fetch("/api/salvar-mesa", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mesanro: state.mesa, produto: p.produto || p.nome, preco: p.preco, qtd: 1, obs: "" }),
    });
    await loadItensMesa();
    await loadMesas();
  }

  async function loadFormasPagamento() {
    const host = el("formas-pagamento-list");
    if (!host) return;
    const res = await fetch("/api/formas-pagamento");
    const data = await res.json();
    const formas = data.formas || [];
    host.innerHTML = "";
    formas.forEach((f) => {
      const b = document.createElement("button");
      b.className = "pdv-btn pdv-btn-green";
      b.style.width = "100%";
      b.style.marginBottom = "6px";
      b.textContent = f.forma || f.nome || "Forma";
      host.appendChild(b);
    });
  }

  function init() {
    document.querySelectorAll("[data-modo]").forEach((b) => (b.onclick = () => setModo(b.dataset.modo)));
    el("busca-produto")?.addEventListener("input", renderProdutos);
    el("btn-open-pagamento")?.addEventListener("click", loadFormasPagamento);
    loadMesas();
    loadClassificacoes();
    setModo("mesa");
  }

  document.addEventListener("DOMContentLoaded", init);
})();
