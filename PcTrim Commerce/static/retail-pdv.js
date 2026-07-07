/**
 * PDV retail: navegação por categoria/subcategoria na tela /casa.
 * Requer window.RetailPdv.loadCatalogTabs({ state, el, renderProdutos }) chamado do index.html.
 */
(function (g) {
  "use strict";

  var _ctx = null;

  function apiJson(url) {
    return fetch(url, { headers: { Accept: "application/json" } }).then(function (res) {
      return res.json().then(function (data) {
        if (!res.ok) {
          var err = new Error((data && (data.erro || data.mensagem)) || "Erro na requisição");
          err.status = res.status;
          err.data = data;
          throw err;
        }
        return data;
      });
    });
  }

  function showLoading() {
    if (!_ctx) return;
    var grid = _ctx.el("prod-grid");
    if (!grid) return;
    grid.innerHTML = '<div class="prod-empty">Carregando produtos...</div>';
  }

  function renderCategoryTabs(categorias) {
    var wrap = _ctx.el("class-tabs");
    if (!wrap) return;
    wrap.innerHTML = "";
    categorias.forEach(function (cat, idx) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = cat.nome || "Categoria";
      btn.setAttribute("data-cat-id", String(cat.id));
      btn.onclick = function () {
        wrap.querySelectorAll("button").forEach(function (b) {
          b.classList.remove("active");
        });
        btn.classList.add("active");
        g.RetailPdv.selectCategoria(cat.id, cat.nome || "Categoria");
      };
      wrap.appendChild(btn);
      if (idx === 0) {
        btn.classList.add("active");
        g.RetailPdv.selectCategoria(cat.id, cat.nome || "Categoria");
      }
    });
  }

  function renderSubcategoryTabs(subcategorias, categoriaId) {
    var wrap = _ctx.el("subcat-tabs");
    if (!wrap) return;
    wrap.innerHTML = "";

    function mkBtn(label, subId, isActive) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = label;
      btn.onclick = function () {
        wrap.querySelectorAll("button").forEach(function (b) {
          b.classList.remove("active");
        });
        btn.classList.add("active");
        g.RetailPdv.loadProdutos(categoriaId, subId);
      };
      if (isActive) btn.classList.add("active");
      wrap.appendChild(btn);
    }

    mkBtn("Todos", null, true);
    subcategorias.forEach(function (sub) {
      mkBtn(sub.nome || "Sub", sub.id, false);
    });
  }

  g.RetailPdv = {
    loadCatalogTabs: async function (ctx) {
      _ctx = ctx;
      showLoading();
      try {
        var data = await apiJson("/api/retail/categorias?ativo=1");
        var list = (data && data.categorias) || [];
        list.sort(function (a, b) {
          var oa = Number(a.ordem_exibicao) || 0;
          var ob = Number(b.ordem_exibicao) || 0;
          if (oa !== ob) return oa - ob;
          return String(a.nome || "").localeCompare(String(b.nome || ""), "pt-BR");
        });
        if (!list.length) {
          var grid = ctx.el("prod-grid");
          if (grid) {
            grid.innerHTML = '<div class="prod-empty">Nenhum produto encontrado</div>';
          }
          return;
        }
        renderCategoryTabs(list);
      } catch (e) {
        console.error("[RetailPdv]", e);
        var gridErr = ctx.el("prod-grid");
        if (gridErr) {
          gridErr.innerHTML = '<div class="prod-empty">Erro ao carregar categorias.</div>';
        }
      }
    },

    selectCategoria: async function (categoriaId, categoriaNome) {
      if (!_ctx) return;
      _ctx.state.retailCategoriaId = categoriaId;
      _ctx.state.retailSubcategoriaId = null;
      _ctx.state.retailCategoriaNome = categoriaNome || null;
      _ctx.state.classificacao = categoriaNome || null;
      var busca = _ctx.el("busca-produto");
      if (busca) busca.value = "";
      showLoading();
      try {
        var data = await apiJson(
          "/api/retail/subcategorias?categoria_id=" + encodeURIComponent(categoriaId) + "&ativo=1"
        );
        var subs = (data && data.subcategorias) || [];
        subs.sort(function (a, b) {
          var oa = Number(a.ordem_exibicao) || 0;
          var ob = Number(b.ordem_exibicao) || 0;
          if (oa !== ob) return oa - ob;
          return String(a.nome || "").localeCompare(String(b.nome || ""), "pt-BR");
        });
        renderSubcategoryTabs(subs, categoriaId);
        await g.RetailPdv.loadProdutos(categoriaId, null);
      } catch (e) {
        console.error("[RetailPdv]", e);
        var gridErr = _ctx.el("prod-grid");
        if (gridErr) {
          gridErr.innerHTML = '<div class="prod-empty">Erro ao carregar subcategorias.</div>';
        }
      }
    },

    loadProdutos: async function (categoriaId, subcategoriaId) {
      if (!_ctx) return;
      _ctx.state.retailCategoriaId = categoriaId;
      _ctx.state.retailSubcategoriaId = subcategoriaId;
      showLoading();
      try {
        var qs =
          "?categoria_id=" +
          encodeURIComponent(categoriaId) +
          (subcategoriaId != null ? "&subcategoria_id=" + encodeURIComponent(subcategoriaId) : "");
        var data = await apiJson("/api/retail/pdv/produtos" + qs);
        _ctx.state.produtos = (data && data.produtos) || [];
        _ctx.renderProdutos();
      } catch (e) {
        console.error("[RetailPdv]", e);
        var gridErr = _ctx.el("prod-grid");
        if (gridErr) {
          gridErr.innerHTML = '<div class="prod-empty">Erro ao carregar produtos.</div>';
        }
      }
    },
  };
})(window);
