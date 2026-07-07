"""Campanhas promocionais (desconto, frete grátis, brinde)."""
from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Optional

from services.business_mode import is_retail

COD_CAMPANHA = "CAMPANHA"
COD_AJUSTE_TECNICO = "AJUSTE_TECNICO"

TIPOS_CAMPANHA = frozenset({"desconto_percentual", "desconto_valor", "frete_gratis", "brinde"})
APLICA_EM_VALORES = frozenset({"todos", "produtos", "categorias"})

_MARCADOR_DADOS = "campanha"


class CampanhaError(ValueError):
    """Erro de validação ou regra de negócio de campanhas."""


def _parse_decimal(value, field: str) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ValueError) as exc:
        raise CampanhaError(f"{field} inválido.") from exc


def _parse_ids_json(value) -> list[int]:
    if value is None or value == "":
        return []
    if isinstance(value, (list, tuple)):
        raw = value
    elif isinstance(value, str):
        try:
            raw = json.loads(value)
        except json.JSONDecodeError as exc:
            raise CampanhaError("Lista de IDs inválida.") from exc
    else:
        return []
    if not isinstance(raw, list):
        raise CampanhaError("Lista de IDs deve ser um array.")
    out: list[int] = []
    for item in raw:
        try:
            out.append(int(item))
        except (TypeError, ValueError) as exc:
            raise CampanhaError("ID inválido na lista.") from exc
    return out


def _parse_dt(value):
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    formats = (
        ("%Y-%m-%dT%H:%M:%S", 19),
        ("%Y-%m-%dT%H:%M", 16),
        ("%Y-%m-%d %H:%M:%S", 19),
        ("%Y-%m-%d %H:%M", 16),
        ("%Y-%m-%d", 10),
    )
    for fmt, length in formats:
        try:
            return datetime.strptime(text[:length], fmt)
        except ValueError:
            continue
    raise CampanhaError("Data inválida.")


def _coerce_dt(value):
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    try:
        return _parse_dt(value)
    except CampanhaError:
        return None


def _limite_vigencia_fim(dt: datetime) -> datetime:
    """Se data_fim for só data ou meia-noite, estende vigência até o fim do dia."""
    if dt.hour == 0 and dt.minute == 0 and dt.second == 0:
        return dt.replace(hour=23, minute=59, second=59, microsecond=0)
    return dt


def _campanha_ativa_agora(row: dict) -> bool:
    if not row:
        return False
    if int(row.get("ativo") or 0) != 1:
        return False
    now = datetime.now()
    di = _coerce_dt(row.get("data_inicio"))
    df = _coerce_dt(row.get("data_fim"))
    if di and di > now:
        return False
    if df and _limite_vigencia_fim(df) < now:
        return False
    return True


def _codigo_ignorado_subtotal(codigoproduto: str) -> bool:
    cod = str(codigoproduto or "").strip().upper()
    return cod in (COD_CAMPANHA, COD_AJUSTE_TECNICO)


def _status_removido(status_pedido: str) -> bool:
    return str(status_pedido or "").strip().upper() == "ITEM_REMOVIDO"


def _filtrar_itens_validos(itens: list[dict]) -> list[dict]:
    out = []
    for it in itens or []:
        if _status_removido(it.get("status_pedido")):
            continue
        if _codigo_ignorado_subtotal(it.get("codigoproduto")):
            continue
        if _dados_item_eh_brinde_campanha(it.get("dados_item")):
            continue
        out.append(it)
    return out


def _dados_item_eh_brinde_campanha(dados_item) -> bool:
    if not dados_item:
        return False
    try:
        data = json.loads(str(dados_item))
    except json.JSONDecodeError:
        return False
    if not isinstance(data, dict):
        return False
    return bool(data.get(_MARCADOR_DADOS) or data.get("campanha_brinde"))


def _marcador_dados_item(campanha_id: int, extra: Optional[dict] = None) -> str:
    payload = {"campanha": True, "campanha_id": int(campanha_id)}
    if extra:
        payload.update(extra)
    return json.dumps(payload, ensure_ascii=False)


def _row_to_api(row: dict) -> dict:
    if not row:
        return {}
    out = dict(row)
    for key in ("produtos_ids", "categorias_ids"):
        if key in out and out[key] is not None and not isinstance(out[key], (list, dict)):
            try:
                out[key] = json.loads(out[key])
            except (TypeError, json.JSONDecodeError):
                out[key] = []
    for key in ("valor_beneficio", "condicao_valor_minimo"):
        if key in out and out[key] is not None:
            try:
                out[key] = float(out[key])
            except (TypeError, ValueError):
                pass
    for key in ("data_inicio", "data_fim", "created_at", "updated_at"):
        if key in out and isinstance(out[key], datetime):
            out[key] = out[key].isoformat(sep=" ", timespec="seconds")
    return out


def validar_payload_campanha(payload: dict, *, partial: bool = False) -> dict:
    if not isinstance(payload, dict):
        raise CampanhaError("Payload inválido.")
    data: dict[str, Any] = {}

    if "nome" in payload or not partial:
        nome = str(payload.get("nome") or "").strip()
        if not nome:
            raise CampanhaError("Nome da campanha é obrigatório.")
        if len(nome) > 120:
            raise CampanhaError("Nome deve ter no máximo 120 caracteres.")
        data["nome"] = nome

    if "tipo" in payload or not partial:
        tipo = str(payload.get("tipo") or "").strip().lower()
        if tipo not in TIPOS_CAMPANHA:
            raise CampanhaError("Tipo de campanha inválido.")
        data["tipo"] = tipo

    tipo = data.get("tipo") or str(payload.get("tipo") or "").strip().lower()

    if tipo == "frete_gratis":
        data["valor_beneficio"] = None

    if "valor_beneficio" in payload or (not partial and tipo in ("desconto_percentual", "desconto_valor", "brinde")):
        vb = _parse_decimal(payload.get("valor_beneficio"), "valor_beneficio")
        if tipo == "desconto_percentual":
            if vb is None or vb <= 0 or vb > 100:
                raise CampanhaError("Percentual deve estar entre 0 e 100.")
        elif tipo == "desconto_valor":
            if vb is None or vb <= 0:
                raise CampanhaError("Valor do desconto deve ser maior que zero.")
        elif tipo == "brinde":
            if vb is None or int(vb) <= 0:
                raise CampanhaError("Informe o produto (ID) do brinde.")
            data["valor_beneficio"] = float(int(vb))
        else:
            data["valor_beneficio"] = float(vb) if vb is not None else None
        if tipo != "brinde" and vb is not None:
            data["valor_beneficio"] = float(vb)

    if "condicao_valor_minimo" in payload or not partial:
        vmin = _parse_decimal(payload.get("condicao_valor_minimo"), "condicao_valor_minimo")
        data["condicao_valor_minimo"] = float(vmin) if vmin is not None else None

    if "aplica_em" in payload or not partial:
        aplica = str(payload.get("aplica_em") or "todos").strip().lower()
        if aplica not in APLICA_EM_VALORES:
            raise CampanhaError("Campo aplica_em inválido.")
        data["aplica_em"] = aplica

    aplica = data.get("aplica_em") or str(payload.get("aplica_em") or "todos").strip().lower()

    produtos_ids = _parse_ids_json(payload.get("produtos_ids")) if "produtos_ids" in payload else None
    categorias_ids = _parse_ids_json(payload.get("categorias_ids")) if "categorias_ids" in payload else None

    if not partial:
        if aplica == "produtos" and not produtos_ids:
            raise CampanhaError("Selecione ao menos um produto.")
        if aplica == "categorias" and not categorias_ids:
            raise CampanhaError("Selecione ao menos uma categoria.")
    if produtos_ids is not None:
        data["produtos_ids"] = produtos_ids
    if categorias_ids is not None:
        data["categorias_ids"] = categorias_ids

    if "ativo" in payload or not partial:
        raw_ativo = payload.get("ativo") if "ativo" in payload else 1
        data["ativo"] = 1 if str(raw_ativo).strip().lower() in ("1", "true", "sim", "s", "yes", "on") or raw_ativo is True else 0

    if "data_inicio" in payload:
        di = payload.get("data_inicio")
        data["data_inicio"] = _parse_dt(di) if di not in (None, "") else None
    if "data_fim" in payload:
        df = payload.get("data_fim")
        data["data_fim"] = _parse_dt(df) if df not in (None, "") else None

    if not partial and data.get("data_inicio") and data.get("data_fim"):
        if data["data_fim"] < data["data_inicio"]:
            raise CampanhaError("Data fim deve ser posterior à data início.")

    return data


def listar_campanhas(cur, id_cliente: int) -> list[dict]:
    cur.execute(
        """
        SELECT id, id_cliente, nome, tipo, valor_beneficio, condicao_valor_minimo,
               aplica_em, produtos_ids, categorias_ids, ativo, data_inicio, data_fim,
               created_at, updated_at
        FROM campanhas
        WHERE id_cliente = %s
        ORDER BY ativo DESC, nome ASC
        """,
        (int(id_cliente),),
    )
    return [_row_to_api(r) for r in (cur.fetchall() or [])]


def obter_campanha(cur, id_cliente: int, campanha_id: int) -> Optional[dict]:
    cur.execute(
        """
        SELECT id, id_cliente, nome, tipo, valor_beneficio, condicao_valor_minimo,
               aplica_em, produtos_ids, categorias_ids, ativo, data_inicio, data_fim,
               created_at, updated_at
        FROM campanhas
        WHERE id = %s AND id_cliente = %s
        LIMIT 1
        """,
        (int(campanha_id), int(id_cliente)),
    )
    row = cur.fetchone()
    return _row_to_api(row) if row else None


def salvar_campanha(cur, id_cliente: int, payload: dict, campanha_id: Optional[int] = None) -> dict:
    data = validar_payload_campanha(payload, partial=False)
    produtos_json = json.dumps(data.get("produtos_ids") or [])
    categorias_json = json.dumps(data.get("categorias_ids") or [])
    if campanha_id:
        cur.execute(
            """
            UPDATE campanhas SET
              nome=%s, tipo=%s, valor_beneficio=%s, condicao_valor_minimo=%s,
              aplica_em=%s, produtos_ids=%s, categorias_ids=%s,
              ativo=%s, data_inicio=%s, data_fim=%s
            WHERE id=%s AND id_cliente=%s
            """,
            (
                data["nome"], data["tipo"], data.get("valor_beneficio"), data.get("condicao_valor_minimo"),
                data.get("aplica_em", "todos"), produtos_json, categorias_json,
                int(data.get("ativo", 1)),
                data.get("data_inicio"), data.get("data_fim"),
                int(campanha_id), int(id_cliente),
            ),
        )
        saved_id = int(campanha_id)
    else:
        cur.execute(
            """
            INSERT INTO campanhas (
              id_cliente, nome, tipo, valor_beneficio, condicao_valor_minimo,
              aplica_em, produtos_ids, categorias_ids, ativo, data_inicio, data_fim
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                int(id_cliente), data["nome"], data["tipo"], data.get("valor_beneficio"),
                data.get("condicao_valor_minimo"), data.get("aplica_em", "todos"),
                produtos_json, categorias_json, int(data.get("ativo", 1)),
                data.get("data_inicio"), data.get("data_fim"),
            ),
        )
        saved_id = int(cur.lastrowid)
    row = obter_campanha(cur, id_cliente, saved_id)
    if not row:
        raise CampanhaError("Falha ao salvar campanha.")
    return row


def set_campanha_ativo(cur, id_cliente: int, campanha_id: int, ativo: bool) -> dict:
    cur.execute(
        "UPDATE campanhas SET ativo=%s WHERE id=%s AND id_cliente=%s",
        (1 if ativo else 0, int(campanha_id), int(id_cliente)),
    )
    if cur.rowcount <= 0:
        raise CampanhaError("Campanha não encontrada.")
    row = obter_campanha(cur, id_cliente, campanha_id)
    if not row:
        raise CampanhaError("Campanha não encontrada.")
    return row


_CODIGO_PRODUTO_CANDIDATES = (
    "codigoproduto",
    "codigo",
    "codproduto",
    "cod_produto",
    "cod_item",
    "produto_codigo",
    "ean",
    "codbarra",
    "codbarras",
    "cod_barras",
    "referencia",
    "ref",
)


def _nomes_colunas_produtos(cur) -> list[str]:
    try:
        cur.execute("SHOW COLUMNS FROM produtos")
        cols = cur.fetchall() or []
    except Exception:
        return []
    names: list[str] = []
    for c in cols:
        if isinstance(c, dict):
            field = str(c.get("Field") or "").strip()
        elif isinstance(c, (list, tuple)) and c:
            field = str(c[0] or "").strip()
        else:
            field = ""
        if field:
            names.append(field)
    return names


def _colunas_codigo_produtos(cur) -> list[str]:
    """Colunas de código em produtos existentes no schema (varejo pode não ter codigoproduto)."""
    col_by_lower = {name.lower(): name for name in _nomes_colunas_produtos(cur)}
    out: list[str] = []
    for cand in _CODIGO_PRODUTO_CANDIDATES:
        actual = col_by_lower.get(cand.lower())
        if actual and actual not in out:
            out.append(actual)
    return out


def resolver_categoria_item(
    cur,
    id_cliente: int,
    item: dict,
    *,
    retail: bool,
    cache_retail: Optional[dict[str, int]] = None,
) -> Optional[int]:
    if retail:
        cod = str(item.get("codigoproduto") or "").strip()
        if not cod:
            return None
        if cache_retail is not None and cod in cache_retail:
            return cache_retail[cod]
        cod_cols = _colunas_codigo_produtos(cur)
        where_parts = ["chave = CAST(%s AS UNSIGNED)"]
        params: list[Any] = [int(id_cliente), cod]
        for col in cod_cols:
            where_parts.append(f"TRIM(COALESCE({col},'')) = %s")
            params.append(cod)
        cur.execute(
            f"""
            SELECT category_id FROM produtos
            WHERE id_cliente = %s AND ({' OR '.join(where_parts)})
            LIMIT 1
            """,
            tuple(params),
        )
        row = cur.fetchone() or {}
        cat = row.get("category_id")
        if cat is not None:
            if cache_retail is not None:
                cache_retail[cod] = int(cat)
            return int(cat)
        return None
    cc = item.get("cod_classe")
    if cc is None:
        cc = item.get("classe")
    try:
        return int(cc) if cc is not None and str(cc).strip() != "" else None
    except (TypeError, ValueError):
        return None


def _batch_categorias_retail(cur, id_cliente: int, codigos: list[str]) -> dict[str, int]:
    if not codigos:
        return {}
    uniq = list({str(c).strip() for c in codigos if str(c).strip()})
    if not uniq:
        return {}
    cod_cols = _colunas_codigo_produtos(cur)
    placeholders = ",".join(["%s"] * len(uniq))
    where_parts = [f"CAST(chave AS CHAR) IN ({placeholders})"]
    params: list[Any] = [int(id_cliente)] + uniq

    int_codes: list[int] = []
    for c in uniq:
        try:
            int_codes.append(int(c))
        except (TypeError, ValueError):
            pass
    if int_codes:
        ph_int = ",".join(["%s"] * len(int_codes))
        where_parts.append(f"chave IN ({ph_int})")
        params.extend(int_codes)

    for col in cod_cols:
        where_parts.append(f"TRIM(COALESCE({col},'')) IN ({placeholders})")
        params.extend(uniq)

    sel_cod_cols = ""
    if cod_cols:
        sel_cod_cols = ", " + ", ".join(
            f"TRIM(COALESCE({col},'')) AS _cod_{i}" for i, col in enumerate(cod_cols)
        )

    cur.execute(
        f"""
        SELECT chave, category_id{sel_cod_cols}
        FROM produtos
        WHERE id_cliente = %s AND ({' OR '.join(where_parts)})
        """,
        tuple(params),
    )
    out: dict[str, int] = {}
    for row in cur.fetchall() or []:
        cat = row.get("category_id")
        if cat is None:
            continue
        ch = str(row.get("chave") or "").strip()
        if ch:
            out[ch] = int(cat)
        for i, _col in enumerate(cod_cols):
            cod = str(row.get(f"_cod_{i}") or "").strip()
            if cod:
                out[cod] = int(cat)
    return out


def _item_conta_para_campanha(item: dict, campanha: dict, categoria_id: Optional[int]) -> bool:
    aplica = str(campanha.get("aplica_em") or "todos").strip().lower()
    if aplica == "todos":
        return True
    if aplica == "produtos":
        ids = _parse_ids_json(campanha.get("produtos_ids"))
        cod = str(item.get("codigoproduto") or "").strip()
        try:
            cod_int = int(cod)
        except (TypeError, ValueError):
            cod_int = None
        for pid in ids:
            if cod_int is not None and pid == cod_int:
                return True
            if str(pid) == cod:
                return True
        return False
    if aplica == "categorias":
        ids = _parse_ids_json(campanha.get("categorias_ids"))
        if categoria_id is None:
            return False
        return int(categoria_id) in ids
    return False


def calcular_subtotal_elegivel(
    cur,
    id_cliente: int,
    itens: list[dict],
    campanha: dict,
    *,
    retail: Optional[bool] = None,
) -> float:
    retail = is_retail(id_cliente) if retail is None else retail
    validos = _filtrar_itens_validos(itens)
    cache: dict[str, int] = {}
    if retail:
        cods = [str(it.get("codigoproduto") or "") for it in validos]
        cache = _batch_categorias_retail(cur, id_cliente, cods)
    total = Decimal("0")
    for it in validos:
        cat = resolver_categoria_item(cur, id_cliente, it, retail=retail, cache_retail=cache)
        if not _item_conta_para_campanha(it, campanha, cat):
            continue
        preco = Decimal(str(it.get("preco") or 0))
        qtd = Decimal(str(it.get("quantidade") or 1))
        total += preco * qtd
    return float(total)


def campanha_elegivel(
    cur,
    id_cliente: int,
    campanha: dict,
    itens: list[dict],
    *,
    origem: str,
    retail: Optional[bool] = None,
) -> tuple[bool, str]:
    retail = is_retail(id_cliente) if retail is None else retail
    if not _campanha_ativa_agora(campanha):
        return False, "Campanha inativa ou fora da vigência."
    tipo = str(campanha.get("tipo") or "").strip().lower()
    if retail and tipo == "frete_gratis":
        return False, "Frete grátis não se aplica ao varejo."
    if tipo == "frete_gratis" and str(origem or "").strip().upper() != "DELIVERY":
        return False, "Frete grátis só para delivery."
    sub = calcular_subtotal_elegivel(cur, id_cliente, itens, campanha, retail=retail)
    if tipo in ("desconto_percentual", "desconto_valor", "brinde") and sub <= 0:
        return False, "Nenhum item do pedido entra nesta campanha."
    vmin = campanha.get("condicao_valor_minimo")
    if vmin is not None:
        try:
            vmin_f = float(vmin)
            if sub < vmin_f:
                return False, f"Subtotal elegível abaixo do mínimo da campanha (R$ {vmin_f:.2f})."
        except (TypeError, ValueError):
            pass
    if tipo == "brinde":
        pid = int(float(campanha.get("valor_beneficio") or 0))
        cur.execute(
            "SELECT chave, produto, preco FROM produtos WHERE id_cliente=%s AND chave=%s LIMIT 1",
            (int(id_cliente), pid),
        )
        if not cur.fetchone():
            return False, "Produto do brinde não encontrado."
    if tipo in ("desconto_percentual", "desconto_valor"):
        benef = calcular_beneficio(cur, id_cliente, campanha, itens, retail=retail)
        if abs(float(benef.get("valor") or 0)) < 0.005:
            return False, "Desconto calculado é zero."
    return True, ""


def calcular_beneficio(
    cur,
    id_cliente: int,
    campanha: dict,
    itens: list[dict],
    *,
    retail: Optional[bool] = None,
) -> dict:
    retail = is_retail(id_cliente) if retail is None else retail
    tipo = str(campanha.get("tipo") or "").strip().lower()
    sub = calcular_subtotal_elegivel(cur, id_cliente, itens, campanha, retail=retail)
    if tipo == "desconto_percentual":
        pct = float(campanha.get("valor_beneficio") or 0)
        valor = round(-sub * pct / 100.0, 2)
        return {"tipo": tipo, "valor": valor, "subtotal_elegivel": sub}
    if tipo == "desconto_valor":
        desconto = min(float(campanha.get("valor_beneficio") or 0), sub)
        return {"tipo": tipo, "valor": round(-desconto, 2), "subtotal_elegivel": sub}
    if tipo == "frete_gratis":
        return {"tipo": tipo, "valor": 0.0, "taxa_entrega_zerada": True, "subtotal_elegivel": sub}
    if tipo == "brinde":
        pid = int(float(campanha.get("valor_beneficio") or 0))
        cur.execute(
            "SELECT chave, produto, preco FROM produtos WHERE id_cliente=%s AND chave=%s LIMIT 1",
            (int(id_cliente), pid),
        )
        prod = cur.fetchone() or {}
        return {
            "tipo": tipo,
            "valor": 0.0,
            "produto_id": pid,
            "produto_nome": prod.get("produto") or prod.get("nome") or "Brinde",
            "subtotal_elegivel": sub,
        }
    raise CampanhaError("Tipo de campanha inválido.")


def listar_elegiveis(
    cur,
    id_cliente: int,
    itens: list[dict],
    *,
    origem: str,
    retail: Optional[bool] = None,
) -> list[dict]:
    return listar_elegiveis_detalhado(
        cur, id_cliente, itens, origem=origem, retail=retail
    )["campanhas"]


def listar_elegiveis_detalhado(
    cur,
    id_cliente: int,
    itens: list[dict],
    *,
    origem: str,
    retail: Optional[bool] = None,
) -> dict:
    retail = is_retail(id_cliente) if retail is None else retail
    rows = listar_campanhas(cur, id_cliente)
    elegiveis: list[dict] = []
    indisponiveis: list[dict] = []
    for camp in rows:
        camp_id = camp.get("id")
        nome = str(camp.get("nome") or "Campanha")
        if int(camp.get("ativo") or 0) != 1:
            indisponiveis.append({
                "id": camp_id,
                "nome": nome,
                "motivo": "Campanha inativa.",
            })
            continue
        ok, motivo = campanha_elegivel(cur, id_cliente, camp, itens, origem=origem, retail=retail)
        if not ok:
            indisponiveis.append({
                "id": camp_id,
                "nome": nome,
                "motivo": motivo or "Campanha não elegível.",
            })
            continue
        benef = calcular_beneficio(cur, id_cliente, camp, itens, retail=retail)
        elegiveis.append({**camp, "beneficio": benef})
    return {"campanhas": elegiveis, "indisponiveis": indisponiveis}


def _carregar_itens_pedido(cur, id_cliente: int, nropedido: int, origem: str) -> list[dict]:
    cur.execute(
        """
        SELECT chave, codigoproduto, produto, preco, quantidade, classe, cod_classe,
               dados_item, status_pedido, obs_item
        FROM pedido_diarios
        WHERE id_cliente=%s AND nropedido=%s AND origem=%s
          AND UPPER(COALESCE(status_pedido,'')) <> 'ITEM_REMOVIDO'
        ORDER BY chave ASC
        """,
        (int(id_cliente), int(nropedido), str(origem).strip().upper()),
    )
    return list(cur.fetchall() or [])


def remover_campanhas_pedido(cur, id_cliente: int, nropedido: int, origem: str) -> None:
    orig = str(origem or "").strip().upper()
    cur.execute(
        """
        DELETE FROM pedido_diarios
        WHERE id_cliente=%s AND nropedido=%s AND origem=%s AND UPPER(TRIM(COALESCE(codigoproduto,'')))=%s
        """,
        (int(id_cliente), int(nropedido), orig, COD_CAMPANHA),
    )
    cur.execute(
        """
        DELETE FROM pedido_diarios
        WHERE id_cliente=%s AND nropedido=%s AND origem=%s
          AND dados_item LIKE %s
        """,
        (int(id_cliente), int(nropedido), orig, '%"campanha"%'),
    )


def _resolver_cod_classe_linha_pedido(
    cur,
    id_cliente: int,
    base: dict,
    itens: list[dict],
    *,
    retail: bool,
) -> Optional[int]:
    """Resolve cod_classe para linha técnica (campanha/ajuste). Varejo pode não ter classificacao."""
    for fonte in (base,):
        cc = fonte.get("cod_classe")
        if cc is not None and str(cc).strip() != "":
            try:
                return int(cc)
            except (TypeError, ValueError):
                pass
    for it in _filtrar_itens_validos(itens):
        cc = it.get("cod_classe")
        if cc is not None and str(cc).strip() != "":
            try:
                return int(cc)
            except (TypeError, ValueError):
                pass
    if retail:
        validos = _filtrar_itens_validos(itens)
        if validos:
            cat = resolver_categoria_item(cur, id_cliente, validos[0], retail=True)
            if cat is not None:
                return int(cat)
        return None
    return None


def aplicar_campanha_pedido(
    cur,
    id_cliente: int,
    nropedido: int,
    origem: str,
    campanha_id: int,
    *,
    cod_usuario: int,
    insert_line: Callable[..., None],
) -> dict:
    """Aplica uma campanha ao pedido (substitui campanha anterior)."""
    orig = str(origem or "").strip().upper()
    if orig not in ("DELIVERY", "BALCAO"):
        raise CampanhaError("Origem inválida.")
    camp = obter_campanha(cur, id_cliente, campanha_id)
    if not camp:
        raise CampanhaError("Campanha não encontrada.")
    itens = _carregar_itens_pedido(cur, id_cliente, nropedido, orig)
    if not _filtrar_itens_validos(itens):
        raise CampanhaError("Pedido sem itens elegíveis.")
    retail = is_retail(id_cliente)
    ok, motivo = campanha_elegivel(cur, id_cliente, camp, itens, origem=orig, retail=retail)
    if not ok:
        raise CampanhaError(motivo or "Campanha não elegível.")
    benef = calcular_beneficio(cur, id_cliente, camp, itens, retail=retail)

    remover_campanhas_pedido(cur, id_cliente, nropedido, orig)

    cur.execute(
        """
        SELECT telefone, cep, nome, endereco, nrocasa, complemento, cliente, formapagamento,
               cod_classe, entregador, UPPER(COALESCE(status_pedido,'')) AS status_pedido
        FROM pedido_diarios
        WHERE nropedido=%s AND id_cliente=%s AND origem=%s
          AND UPPER(COALESCE(status_pedido,'')) <> 'ITEM_REMOVIDO'
        ORDER BY chave DESC LIMIT 1
        """,
        (int(nropedido), int(id_cliente), orig),
    )
    base = cur.fetchone() or {}
    if not base:
        raise CampanhaError("Pedido não encontrado.")
    cod_classe = _resolver_cod_classe_linha_pedido(cur, id_cliente, base, itens, retail=retail)
    if cod_classe is None and not retail:
        raise CampanhaError("Não foi possível resolver cod_classe do pedido.")

    status_insert = "ABERTO" if str(base.get("status_pedido") or "").upper() == "ABERTO" else "AGUARDE"

    cur.execute(
        "SELECT COALESCE(MAX(lancamento),0) AS m FROM pedido_diarios WHERE id_cliente=%s AND nropedido=%s AND origem=%s",
        (int(id_cliente), int(nropedido), orig),
    )
    row_max = cur.fetchone() or {}
    lancamento = int(row_max.get("m") or 0) + 1
    if lancamento > 2147483647:
        lancamento = 1

    tipo = str(camp.get("tipo") or "").strip().lower()
    result = {
        "sucesso": True,
        "campanha_id": int(campanha_id),
        "campanha_nome": camp.get("nome"),
        "tipo": tipo,
        "beneficio": benef,
    }

    if tipo == "frete_gratis":
        result["taxa_entrega_zerada"] = True
        return result

    if tipo in ("desconto_percentual", "desconto_valor"):
        valor = float(benef.get("valor") or 0)
        if valor == 0:
            return result
        insert_line(
            cur,
            origem=orig,
            nropedido=nropedido,
            id_cliente=id_cliente,
            telefone=str(base.get("telefone") or ""),
            cep=str(base.get("cep") or ""),
            nome=str(base.get("nome") or ""),
            endereco=str(base.get("endereco") or ""),
            nrocasa=str(base.get("nrocasa") or ""),
            complemento=str(base.get("complemento") or ""),
            codigoproduto=COD_CAMPANHA,
            produto=str(camp.get("nome") or "Campanha"),
            preco=valor,
            quantidade=1.0,
            classe=COD_CAMPANHA,
            obs_item="",
            dados_item=_marcador_dados_item(int(campanha_id)),
            obs_geral="",
            cliente=str(base.get("cliente") or base.get("nome") or ""),
            cod_classe=cod_classe,
            cod_usuario=cod_usuario,
            status_pedido=status_insert,
            status_comanda="MODIFICADA",
            lancamento=lancamento,
            nrolancamento=None,
            formapagamento=str(base.get("formapagamento") or ""),
            entregador=str(base.get("entregador") or ""),
        )
        return result

    if tipo == "brinde":
        pid = int(benef.get("produto_id") or 0)
        cur.execute(
            "SELECT chave, produto, preco, classe, cod_classe FROM produtos WHERE id_cliente=%s AND chave=%s LIMIT 1",
            (int(id_cliente), pid),
        )
        prod = cur.fetchone() or {}
        if not prod:
            raise CampanhaError("Produto do brinde não encontrado.")
        insert_line(
            cur,
            origem=orig,
            nropedido=nropedido,
            id_cliente=id_cliente,
            telefone=str(base.get("telefone") or ""),
            cep=str(base.get("cep") or ""),
            nome=str(base.get("nome") or ""),
            endereco=str(base.get("endereco") or ""),
            nrocasa=str(base.get("nrocasa") or ""),
            complemento=str(base.get("complemento") or ""),
            codigoproduto=str(prod.get("chave") or pid),
            produto=str(prod.get("produto") or benef.get("produto_nome") or "Brinde"),
            preco=0.0,
            quantidade=1.0,
            classe=str(prod.get("classe") or prod.get("cod_classe") or ""),
            obs_item="Brinde (campanha)",
            dados_item=_marcador_dados_item(int(campanha_id), {"campanha_brinde": True}),
            obs_geral="",
            cliente=str(base.get("cliente") or base.get("nome") or ""),
            cod_classe=prod.get("cod_classe") or cod_classe,
            cod_usuario=cod_usuario,
            status_pedido=status_insert,
            status_comanda="MODIFICADA",
            lancamento=lancamento,
            nrolancamento=None,
            formapagamento=str(base.get("formapagamento") or ""),
            entregador=str(base.get("entregador") or ""),
        )
        return result

    raise CampanhaError("Tipo de campanha não suportado.")


def listar_categorias_opcoes(cur, id_cliente: int, *, retail: bool) -> list[dict]:
    if retail:
        cur.execute(
            """
            SELECT id, nome, ativo, ordem_exibicao
            FROM categoria
            WHERE id_cliente=%s AND ativo=1
            ORDER BY ordem_exibicao ASC, nome ASC
            """,
            (int(id_cliente),),
        )
        return [
            {"id": r.get("id"), "nome": r.get("nome"), "tipo": "categoria"}
            for r in (cur.fetchall() or [])
        ]
    cur.execute(
        """
        SELECT chave AS id, COALESCE(nomeclassificacao, classificacao, '') AS nome
        FROM classificacao
        WHERE id_cliente=%s
        ORDER BY nome ASC
        """,
        (int(id_cliente),),
    )
    return [
        {"id": r.get("id"), "nome": r.get("nome"), "tipo": "classificacao"}
        for r in (cur.fetchall() or [])
    ]


def ensure_campanhas_schema() -> None:
    """Cria tabela campanhas em produção e homologação (idempotente)."""
    from pathlib import Path

    from config import Config
    from database import conectar_admin_optional

    sql_path = Path(__file__).resolve().parent.parent / "sql" / "criar_tabela_campanhas.sql"
    sql = sql_path.read_text(encoding="utf-8")

    targets = ["production"]
    if Config.admin_db_configured("homologation"):
        targets.append("homologation")

    for target in targets:
        conn = None
        cur = None
        try:
            conn = conectar_admin_optional(target=target)
            if conn is None:
                continue
            cur = conn.cursor()
            for stmt in sql.split(";"):
                chunk = stmt.strip()
                if chunk:
                    cur.execute(chunk)
            conn.commit()
        except Exception as e:
            try:
                if conn:
                    conn.rollback()
            except Exception:
                pass
            print(f"[SCHEMA CAMPANHAS ERRO {target}]", e, flush=True)
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()
