/**
 * Modo varejo (BUSINESS_TYPE=retail): PDV balcão apenas.
 * Requer window.__LOJA_RETAIL definido antes deste script (partial retail_mode.html).
 */
(function (g) {
  "use strict";

  var IS_RETAIL = !!g.__LOJA_RETAIL;
  g.IS_RETAIL = IS_RETAIL;
  g.LABEL_PEDIDO = IS_RETAIL ? "Venda" : "Pedido";

  g.applyRetailUi = function applyRetailUi() {
    if (!IS_RETAIL) return;
    g.document.querySelectorAll("[data-retail-hide]").forEach(function (b) {
      b.style.display = "none";
      b.classList.remove("active");
    });
    var balcaoBtn = g.document.querySelector('[data-modo="balcao"]');
    if (balcaoBtn) balcaoBtn.classList.add("active");
  };

  g.retailBlockModo = function retailBlockModo(modo) {
    return IS_RETAIL && (modo === "mesa" || modo === "delivery");
  };

  g.retailForceBalcaoState = function retailForceBalcaoState(state) {
    if (!IS_RETAIL || !state) return;
    state.modo = "balcao";
  };

  g.retailCasaPath = function retailCasaPath() {
    return IS_RETAIL ? "/casa?modo=balcao" : null;
  };

  g.retailGoCasa = function retailGoCasa() {
    if (!IS_RETAIL) return false;
    if (typeof g.lojaGo === "function") {
      g.lojaGo("/casa?modo=balcao");
    } else {
      g.location.assign("/casa?modo=balcao");
    }
    return true;
  };
})(window);
