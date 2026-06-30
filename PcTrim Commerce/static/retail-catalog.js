/**
 * Helpers para APIs do catálogo retail (fetch + mensagens de erro).
 */
(function (g) {
  async function parseApiResponse(resp) {
    var data = {};
    try {
      data = await resp.json();
    } catch (_) {
      data = {};
    }
    if (!resp.ok || data.sucesso === false) {
      var msg = data.erro || data.mensagem || "Erro HTTP " + resp.status;
      if (resp.status === 404) {
        msg += " — atualize o deploy ou reinicie o servidor Flask.";
      } else if (resp.status === 403) {
        msg += " — disponível apenas para lojas varejo.";
      } else if (resp.status === 401) {
        msg = "Sessão expirada. Faça login novamente.";
      }
      throw new Error(msg);
    }
    return data;
  }

  g.retailApiJson = async function (url, options) {
    var resp = await fetch(url, options || {});
    return parseApiResponse(resp);
  };
})(window);
