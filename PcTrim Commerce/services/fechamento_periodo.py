"""Fechamento de período: arquiva linhas de pedido_diarios em pedido_periodos (MySQL 5.x)."""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from database import conectar


def _parse_dia(s: Optional[str]) -> datetime:
    if not s or not str(s).strip():
        raise ValueError("Data obrigatória")
    return datetime.strptime(str(s).strip()[:10], "%Y-%m-%d")


def intervalo_datetimes(data_inicio: str, data_fim: str) -> Tuple[datetime, datetime]:
    """Retorna [início inclusivo, fim exclusivo) em data_criacao."""
    d0 = _parse_dia(data_inicio)
    d1 = _parse_dia(data_fim) + timedelta(days=1)
    if d0 >= d1:
        raise ValueError("data_inicio deve ser anterior ou igual a data_fim")
    return d0, d1


def _colunas_pedido_diarios_sem_chave(cursor) -> List[str]:
    cursor.execute("SHOW COLUMNS FROM pedido_diarios")
    rows = cursor.fetchall()
    out = []
    for r in rows:
        name = r[0] if not isinstance(r, dict) else r.get("Field")
        if name and str(name).lower() != "chave":
            out.append(str(name))
    return out


def _where_fechamento(id_cliente: int, d0: datetime, d1: datetime) -> Tuple[str, Tuple[Any, ...]]:
    """
    Linhas elegíveis ao fechamento: ITEM_REMOVIDO (qualquer origem) ou recebidas.
    Recebido: origem MESA usa status_mesa=RECEBIDO; demais origens usam status_pedido=RECEBIDO.
    """
    sql = f"""
        id_cliente = %s
        AND data_criacao >= %s
        AND data_criacao < %s
        AND (
            UPPER(TRIM(COALESCE(status_pedido, ''))) = 'ITEM_REMOVIDO'
            OR (
                (UPPER(TRIM(COALESCE(origem, ''))) = 'MESA'
                 AND UPPER(TRIM(COALESCE(status_mesa, ''))) = 'RECEBIDO')
                OR (UPPER(TRIM(COALESCE(origem, ''))) <> 'MESA'
                    AND UPPER(TRIM(COALESCE(status_pedido, ''))) = 'RECEBIDO')
            )
        )
    """
    params = (int(id_cliente), d0, d1)
    return sql.strip(), params


def _where_periodo_diario(id_cliente: int, d0: datetime, d1: datetime) -> Tuple[str, Tuple[Any, ...]]:
    """Intervalo de data_criacao no diário (qualquer status)."""
    sql = """
        id_cliente = %s
        AND data_criacao >= %s
        AND data_criacao < %s
    """
    params = (int(id_cliente), d0, d1)
    return sql.strip(), params


def _mensagem_erro_relatorios(exc: Exception | str) -> str:
    texto = str(exc or "").strip()
    if not texto:
        return "Pasta de relatorios indisponivel. Verifique as permissoes do diretorio configurado."
    if isinstance(exc, PermissionError) or "access is denied" in texto.lower() or "acesso negado" in texto.lower():
        return "Pasta de relatorios sem permissao de acesso. Verifique as permissoes do diretorio configurado."
    return "Nao foi possivel preparar a pasta de relatorios. Verifique a configuracao do diretorio."


def _sql_recebido_para_faturamento() -> str:
    """
    Linha considerada recebida para faturamento / relatórios:
    origem MESA → status_mesa = RECEBIDO; caso contrário → status_pedido = RECEBIDO.
    """
    return (
        "("
        "  (UPPER(TRIM(COALESCE(origem, ''))) = 'MESA' "
        "   AND UPPER(TRIM(COALESCE(status_mesa, ''))) = 'RECEBIDO')"
        "  OR (UPPER(TRIM(COALESCE(origem, ''))) <> 'MESA' "
        "      AND UPPER(TRIM(COALESCE(status_pedido, ''))) = 'RECEBIDO')"
        ")"
    )


def _sql_excluir_comanda_cancelada() -> str:
    return "UPPER(TRIM(COALESCE(status_comanda, ''))) <> 'CANCELADA'"


def _sql_faturamento_linha() -> str:
    return f"({_sql_recebido_para_faturamento()}) AND ({_sql_excluir_comanda_cancelada()})"


def _normalizar_forma_pagamento(label: str) -> str:
    """
    Agrupa rótulos livres da baixa em categorias para prestação de contas.
    Ordem de teste importa (ex.: 'cartão crédito' antes de genérico 'cartão').
    """
    s = re.sub(r"\s+", " ", str(label or "").strip().lower())
    if not s:
        return "Outros"
    if "pix" in s:
        return "PIX"
    if "dinheir" in s or "especi" in s or s in ("din", "cash"):
        return "Dinheiro"
    if "créd" in s or "cred" in s or "credito" in s:
        return "Cartão crédito"
    if "déb" in s or "deb" in s or "debito" in s:
        return "Cartão débito"
    if "vale" in s or "refei" in s or "alimen" in s:
        return "Vale/refeição"
    if "transf" in s or "ted" in s or "doc" in s or "depós" in s or "deposito" in s:
        return "Transferência"
    if "boleto" in s:
        return "Boleto"
    if "cart" in s or "card" in s:
        return "Cartão (não especificado)"
    if "misto" in s:
        return "Misto (detalhe em baixa)"
    return "Outros"


def _parse_baixa_pagamentos_json(raw: str) -> Optional[List[dict]]:
    raw = str(raw or "").strip()
    if not raw or raw[0] not in "{[":
        return None
    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(obj, dict):
        return None
    pag = obj.get("pagamentos")
    if not isinstance(pag, list):
        return None
    out: List[dict] = []
    for p in pag:
        if not isinstance(p, dict):
            continue
        forma = str(p.get("forma") or "").strip()
        try:
            valor = float(p.get("valor") or 0)
        except (TypeError, ValueError):
            valor = 0.0
        if valor > 0 and forma:
            out.append({"forma": forma, "valor": valor})
    return out or None


def garantir_diretorio_relatorios(id_cliente: int) -> dict:
    """Cria C:\\Geral\\Relatorios e subpasta do cliente."""
    base = os.environ.get("LOJA_RELATORIOS_DIR", r"C:\Geral\Relatorios")
    try:
        os.makedirs(base, exist_ok=True)
        os.makedirs(os.path.join(base, str(int(id_cliente))), exist_ok=True)
        return {"sucesso": True, "base": base}
    except OSError as e:
        return {"sucesso": False, "erro": _mensagem_erro_relatorios(e), "base": base}


def _money_br(v: float) -> str:
    try:
        n = float(v)
    except (TypeError, ValueError):
        n = 0.0
    return "R$ " + f"{n:.2f}".replace(".", ",")


def resumo_financeiro_fechamento(id_cliente: int, data_inicio: str, data_fim: str) -> dict:
    """Agregados financeiros no período: recebido (MESA: status_mesa; outras: status_pedido) e ITEM_REMOVIDO."""
    d0, d1 = intervalo_datetimes(data_inicio, data_fim)
    garantir_diretorio_relatorios(id_cliente)
    conn = None
    cur = None
    try:
        conn = conectar()
        cur = conn.cursor(dictionary=True)
        w, p = _where_fechamento(id_cliente, d0, d1)
        cur.execute(
            f"""
            SELECT COALESCE(SUM(CAST(preco AS DECIMAL(14,4)) * CAST(quantidade AS DECIMAL(14,4))), 0) AS t
            FROM pedido_diarios WHERE {w}
            """,
            p,
        )
        total_geral = float((cur.fetchone() or {}).get("t") or 0)
        cur.execute(
            f"""
            SELECT
                CASE
                    WHEN UPPER(TRIM(COALESCE(status_pedido, ''))) = 'ITEM_REMOVIDO' THEN 'ITEM_REMOVIDO'
                    WHEN UPPER(TRIM(COALESCE(origem, ''))) = 'MESA'
                         AND UPPER(TRIM(COALESCE(status_mesa, ''))) = 'RECEBIDO' THEN 'RECEBIDO'
                    ELSE UPPER(TRIM(COALESCE(status_pedido, '')))
                END AS st,
                COALESCE(SUM(CAST(preco AS DECIMAL(14,4)) * CAST(quantidade AS DECIMAL(14,4))), 0) AS total
            FROM pedido_diarios WHERE {w}
            GROUP BY
                CASE
                    WHEN UPPER(TRIM(COALESCE(status_pedido, ''))) = 'ITEM_REMOVIDO' THEN 'ITEM_REMOVIDO'
                    WHEN UPPER(TRIM(COALESCE(origem, ''))) = 'MESA'
                         AND UPPER(TRIM(COALESCE(status_mesa, ''))) = 'RECEBIDO' THEN 'RECEBIDO'
                    ELSE UPPER(TRIM(COALESCE(status_pedido, '')))
                END
            """,
            p,
        )
        por_status_val = [
            {"status": (row.get("st") or ""), "total": float(row.get("total") or 0)}
            for row in (cur.fetchall() or [])
        ]
        cur.execute(
            f"""
            SELECT TRIM(COALESCE(NULLIF(formapagamento, ''), '(sem forma)')) AS fp,
                   COALESCE(SUM(CAST(preco AS DECIMAL(14,4)) * CAST(quantidade AS DECIMAL(14,4))), 0) AS total
            FROM pedido_diarios WHERE {w}
            GROUP BY TRIM(COALESCE(NULLIF(formapagamento, ''), '(sem forma)'))
            ORDER BY total DESC
            """,
            p,
        )
        por_forma = [
            {"forma": (row.get("fp") or ""), "total": float(row.get("total") or 0)}
            for row in (cur.fetchall() or [])
        ]
        texto = _formatar_resumo_texto_impressao(
            id_cliente, data_inicio[:10], data_fim[:10], total_geral, por_status_val, por_forma
        )
        return {
            "sucesso": True,
            "data_inicio": data_inicio[:10],
            "data_fim": data_fim[:10],
            "total_geral": total_geral,
            "por_status": por_status_val,
            "por_forma_pagamento": por_forma,
            "texto_impressao": texto,
        }
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def _formatar_resumo_texto_impressao(
    id_cliente: int,
    di: str,
    df: str,
    total_geral: float,
    por_status: List[dict],
    por_forma: List[dict],
) -> str:
    lines = [
        "========== FECHAMENTO DE CAIXA ==========",
        f"id_cliente: {id_cliente}",
        f"Periodo: {di} a {df} (fim do dia incluso)",
        f"TOTAL GERAL: {_money_br(total_geral)}",
        "",
        "--- Por status ---",
    ]
    for x in por_status:
        lines.append(f"  {x.get('status') or '-'} : {_money_br(float(x.get('total') or 0))}")
    lines.append("")
    lines.append("--- Por forma de pagamento (campo formapagamento) ---")
    for x in por_forma:
        lines.append(f"  {x.get('forma') or '-'} : {_money_br(float(x.get('total') or 0))}")
    lines.append("")
    lines.append(
        "(Linhas elegiveis: ITEM_REMOVIDO; recebido: MESA com status_mesa=RECEBIDO, demais origens com status_pedido=RECEBIDO)"
    )
    lines.append("==========================================")
    return "\n".join(lines)


def preview_fechamento(id_cliente: int, data_inicio: str, data_fim: str) -> dict:
    d0, d1 = intervalo_datetimes(data_inicio, data_fim)
    pasta_info = garantir_diretorio_relatorios(id_cliente)
    conn = None
    cur = None
    try:
        conn = conectar()
        cur = conn.cursor(dictionary=True)
        w, p = _where_fechamento(id_cliente, d0, d1)
        cur.execute(f"SELECT COUNT(*) AS n FROM pedido_diarios WHERE {w}", p)
        n_linhas = int((cur.fetchone() or {}).get("n") or 0)
        cur.execute(
            f"""
            SELECT
                CASE
                    WHEN UPPER(TRIM(COALESCE(status_pedido, ''))) = 'ITEM_REMOVIDO' THEN 'ITEM_REMOVIDO'
                    WHEN UPPER(TRIM(COALESCE(origem, ''))) = 'MESA'
                         AND UPPER(TRIM(COALESCE(status_mesa, ''))) = 'RECEBIDO' THEN 'RECEBIDO'
                    ELSE UPPER(TRIM(COALESCE(status_pedido, '')))
                END AS st,
                COUNT(*) AS c
            FROM pedido_diarios WHERE {w}
            GROUP BY
                CASE
                    WHEN UPPER(TRIM(COALESCE(status_pedido, ''))) = 'ITEM_REMOVIDO' THEN 'ITEM_REMOVIDO'
                    WHEN UPPER(TRIM(COALESCE(origem, ''))) = 'MESA'
                         AND UPPER(TRIM(COALESCE(status_mesa, ''))) = 'RECEBIDO' THEN 'RECEBIDO'
                    ELSE UPPER(TRIM(COALESCE(status_pedido, '')))
                END
            """,
            p,
        )
        por_status = [{"status": row["st"], "linhas": int(row["c"])} for row in (cur.fetchall() or [])]
        cur.execute(
            f"""
            SELECT COUNT(DISTINCT CONCAT(COALESCE(origem,''), ':', CAST(nropedido AS CHAR(20)))) AS n
            FROM pedido_diarios WHERE {w}
            """,
            p,
        )
        n_grupos = int((cur.fetchone() or {}).get("n") or 0)
        out = {
            "sucesso": True,
            "data_inicio": data_inicio[:10],
            "data_fim": data_fim[:10],
            "linhas": n_linhas,
            "pedidos_origem_numero_distintos": n_grupos,
            "por_status": por_status,
        }
        if pasta_info.get("sucesso"):
            out["pasta_relatorios"] = pasta_info.get("base")
        else:
            out["pasta_relatorios_erro"] = pasta_info.get("erro")
            out["pasta_relatorios_indisponivel"] = True
        return out
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def relatorio_gerencial_periodo(
    id_cliente: int,
    data_inicio: str,
    data_fim: str,
    *,
    cursor: Optional[Any] = None,
) -> dict:
    """
    Relatório gerencial para prestação de contas no mesmo intervalo do fechamento (pedido_diarios).
    Pagamentos: prioriza JSON em baixa_pagamento por pedido (origem+nropedido); senão formapagamento + total do pedido.
    Se `cursor` for passado (dict cursor), usa a mesma conexão/transação (ex.: antes do DELETE no fechamento).
    """
    d0, d1 = intervalo_datetimes(data_inicio, data_fim)
    if cursor is None:
        garantir_diretorio_relatorios(id_cliente)
    wp, pp = _where_periodo_diario(id_cliente, d0, d1)
    di = data_inicio[:10]
    df = data_fim[:10]
    conn = None
    cur = cursor
    own_cursor = cursor is None
    try:
        if own_cursor:
            conn = conectar()
            cur = conn.cursor(dictionary=True)
            garantir_diretorio_relatorios(id_cliente)

        if cur is None:
            return {"sucesso": False, "erro": "Cursor indisponível para relatório gerencial."}

        sr = _sql_faturamento_linha()
        sr_recebido = _sql_recebido_para_faturamento()
        cur.execute(
            f"""
            SELECT UPPER(TRIM(COALESCE(origem, ''))) AS og,
                   COALESCE(SUM(CAST(preco AS DECIMAL(14, 4)) * CAST(quantidade AS DECIMAL(14, 4))), 0) AS total,
                   COUNT(DISTINCT CONCAT(UPPER(TRIM(COALESCE(origem, ''))), ':', CAST(nropedido AS CHAR(20)))) AS pedidos
            FROM pedido_diarios
            WHERE {wp}
              AND {sr}
            GROUP BY UPPER(TRIM(COALESCE(origem, '')))
            """,
            pp,
        )
        por_canal: List[dict] = []
        tot_recebido = 0.0
        tot_pedidos_recebido = 0
        for row in cur.fetchall() or []:
            og = str(row.get("og") or "—").strip() or "—"
            total = float(row.get("total") or 0)
            ped = int(row.get("pedidos") or 0)
            tot_recebido += total
            tot_pedidos_recebido += ped
            ticket = (total / ped) if ped > 0 else 0.0
            por_canal.append({"origem": og, "faturamento": total, "pedidos": ped, "ticket_medio": ticket})

        cur.execute(
            f"""
            SELECT COUNT(*) AS n_linhas,
                   COALESCE(SUM(CAST(preco AS DECIMAL(14, 4)) * CAST(quantidade AS DECIMAL(14, 4))), 0) AS total
            FROM pedido_diarios
            WHERE {wp}
              AND UPPER(TRIM(COALESCE(status_pedido, ''))) = 'ITEM_REMOVIDO'
            """,
            pp,
        )
        row_rm = cur.fetchone() or {}
        rem_linhas = int(row_rm.get("n_linhas") or 0)
        rem_valor = float(row_rm.get("total") or 0)

        cur.execute(
            f"""
            SELECT COUNT(DISTINCT CONCAT(UPPER(TRIM(COALESCE(origem, ''))), ':', CAST(nropedido AS CHAR(20)))) AS n
            FROM pedido_diarios
            WHERE {wp}
              AND UPPER(TRIM(COALESCE(status_comanda, ''))) = 'MODIFICADA'
            """,
            pp,
        )
        mod_total = int((cur.fetchone() or {}).get("n") or 0)

        cur.execute(
            f"""
            SELECT COUNT(DISTINCT CONCAT(UPPER(TRIM(COALESCE(origem, ''))), ':', CAST(nropedido AS CHAR(20)))) AS n
            FROM pedido_diarios
            WHERE {wp}
              AND UPPER(TRIM(COALESCE(status_comanda, ''))) = 'MODIFICADA'
              AND NOT ({sr_recebido})
            """,
            pp,
        )
        mod_aberto = int((cur.fetchone() or {}).get("n") or 0)

        cur.execute(
            f"""
            SELECT COUNT(DISTINCT CONCAT(UPPER(TRIM(COALESCE(origem, ''))), ':', CAST(nropedido AS CHAR(20)))) AS n
            FROM pedido_diarios
            WHERE {wp}
              AND UPPER(TRIM(COALESCE(status_comanda, ''))) = 'CANCELADA'
            """,
            pp,
        )
        canceladas_total = int((cur.fetchone() or {}).get("n") or 0)

        cur.execute(
            f"""
            SELECT COUNT(DISTINCT CONCAT(UPPER(TRIM(COALESCE(origem, ''))), ':', CAST(nropedido AS CHAR(20)))) AS n
            FROM pedido_diarios
            WHERE {wp}
              AND UPPER(TRIM(COALESCE(status_comanda, ''))) = 'CANCELADA'
              AND NOT ({sr_recebido})
            """,
            pp,
        )
        canceladas_aberto = int((cur.fetchone() or {}).get("n") or 0)

        cur.execute(
            f"""
            SELECT COUNT(DISTINCT CONCAT(UPPER(TRIM(COALESCE(origem, ''))), ':', CAST(nropedido AS CHAR(20)))) AS n
            FROM pedido_diarios
            WHERE {wp}
              AND UPPER(TRIM(COALESCE(status_pedido, ''))) = 'AGUARDE'
            """,
            pp,
        )
        pedidos_aguarde = int((cur.fetchone() or {}).get("n") or 0)

        cur.execute(
            f"""
            SELECT COALESCE(NULLIF(TRIM(codigoproduto), ''), NULLIF(TRIM(produto), ''), '(sem ref)') AS ref,
                   MAX(TRIM(COALESCE(produto, ''))) AS nome,
                   COALESCE(SUM(CAST(quantidade AS DECIMAL(14, 4))), 0) AS qtd,
                   COALESCE(SUM(CAST(preco AS DECIMAL(14, 4)) * CAST(quantidade AS DECIMAL(14, 4))), 0) AS total
            FROM pedido_diarios
            WHERE {wp}
              AND {sr}
            GROUP BY COALESCE(NULLIF(TRIM(codigoproduto), ''), NULLIF(TRIM(produto), ''), '(sem ref)')
            ORDER BY total DESC
            LIMIT 20
            """,
            pp,
        )
        top_produtos = [
            {
                "ref": (r.get("ref") or r.get("nome") or "")[:120],
                "produto": (r.get("nome") or r.get("ref") or "")[:200],
                "quantidade": float(r.get("qtd") or 0),
                "total": float(r.get("total") or 0),
            }
            for r in (cur.fetchall() or [])
        ]

        cur.execute(
            f"""
            SELECT HOUR(data_criacao) AS hr,
                   COUNT(*) AS n_itens,
                   COALESCE(SUM(CAST(preco AS DECIMAL(14, 4)) * CAST(quantidade AS DECIMAL(14, 4))), 0) AS total
            FROM pedido_diarios
            WHERE {wp}
              AND {sr}
            GROUP BY HOUR(data_criacao)
            ORDER BY hr
            """,
            pp,
        )
        por_hora = [
            {"hora": int(r.get("hr") or 0), "itens": int(r.get("n_itens") or 0), "total": float(r.get("total") or 0)}
            for r in (cur.fetchall() or [])
        ]

        cur.execute(
            f"""
            SELECT origem, nropedido,
                   MAX(COALESCE(baixa_pagamento, '')) AS baixa_pagamento,
                   MAX(COALESCE(formapagamento, '')) AS formapagamento,
                   COALESCE(SUM(CAST(preco AS DECIMAL(14, 4)) * CAST(quantidade AS DECIMAL(14, 4))), 0) AS total_pedido
            FROM pedido_diarios
            WHERE {wp}
              AND {sr}
            GROUP BY origem, nropedido
            """,
            pp,
        )
        pedidos_rows = list(cur.fetchall() or [])
        pag_norm: Dict[str, float] = defaultdict(float)
        for pr in pedidos_rows:
            bp = str(pr.get("baixa_pagamento") or "").strip()
            parsed = _parse_baixa_pagamentos_json(bp)
            total_ped = float(pr.get("total_pedido") or 0)
            if parsed:
                for p in parsed:
                    bucket = _normalizar_forma_pagamento(p.get("forma"))
                    try:
                        v = float(p.get("valor") or 0)
                    except (TypeError, ValueError):
                        v = 0.0
                    if v > 0:
                        pag_norm[bucket] += v
            else:
                fp = str(pr.get("formapagamento") or "").strip()
                bucket = _normalizar_forma_pagamento(fp if fp else "Outros")
                if total_ped > 0:
                    pag_norm[bucket] += total_ped

        por_forma_normalizada = sorted(
            [{"categoria": k, "total": round(float(v), 2)} for k, v in pag_norm.items()],
            key=lambda x: -x["total"],
        )

        novos_clientes = None
        cur.execute("SHOW COLUMNS FROM clientes LIKE 'data_criacao'")
        if cur.fetchone():
            cur.execute(
                """
                SELECT COUNT(*) AS n
                FROM clientes
                WHERE id_cliente = %s
                  AND data_criacao >= %s
                  AND data_criacao < %s
                """,
                (int(id_cliente), d0, d1),
            )
            novos_clientes = int((cur.fetchone() or {}).get("n") or 0)

        mix: List[dict] = []
        if tot_recebido > 0:
            for c in por_canal:
                mix.append(
                    {
                        "origem": c["origem"],
                        "percentual_faturamento": round(100.0 * float(c["faturamento"]) / tot_recebido, 2),
                    }
                )

        taxa_remocao_valor = round(100.0 * rem_valor / (tot_recebido + rem_valor), 2) if (tot_recebido + rem_valor) > 0 else 0.0

        payload = {
            "sucesso": True,
            "data_inicio": di,
            "data_fim": df,
            "id_cliente": int(id_cliente),
            "faturamento_recebido_total": round(tot_recebido, 2),
            "pedidos_recebidos_distintos": tot_pedidos_recebido,
            "por_canal": por_canal,
            "mix_percentual_canal": mix,
            "item_removido_linhas": rem_linhas,
            "item_removido_valor": round(rem_valor, 2),
            "taxa_remocao_valor_pct": taxa_remocao_valor,
            "comandas_modificadas_pedidos": mod_total,
            "comandas_modificadas_nao_recebido_pedidos": mod_aberto,
            "comandas_canceladas_pedidos": canceladas_total,
            "comandas_canceladas_nao_recebido_pedidos": canceladas_aberto,
            "pedidos_aguarde_distintos_periodo": pedidos_aguarde,
            "pagamentos_por_categoria": por_forma_normalizada,
            "top_produtos": top_produtos,
            "por_hora_recebido": por_hora,
            "novos_clientes_cadastro": novos_clientes,
        }
        payload["texto_impressao"] = _formatar_relatorio_gerencial_texto(payload)
        return payload
    finally:
        if own_cursor and cur:
            cur.close()
        if conn:
            conn.close()


def _formatar_relatorio_gerencial_texto(d: dict) -> str:
    lines = [
        "========== RELATORIO GERENCIAL (PRESTACAO DE CONTAS) ==========",
        f"id_cliente: {d.get('id_cliente')}",
        f"Periodo: {d.get('data_inicio')} a {d.get('data_fim')} (fim do dia incluso)",
        "(Recebido: origem MESA → status_mesa=RECEBIDO; demais origens → status_pedido=RECEBIDO)",
        "",
        "--- Faturamento RECEBIDO ---",
        f"Total geral: {_money_br(float(d.get('faturamento_recebido_total') or 0))}",
        f"Pedidos distintos (recebido): {d.get('pedidos_recebidos_distintos')}",
        "",
        "--- Por canal (origem) ---",
    ]
    for c in d.get("por_canal") or []:
        lines.append(
            f"  {c.get('origem')}: {_money_br(float(c.get('faturamento') or 0))} | "
            f"pedidos={c.get('pedidos')} | ticket medio={_money_br(float(c.get('ticket_medio') or 0))}"
        )
    lines.append("")
    lines.append("--- Mix % sobre faturamento recebido ---")
    for m in d.get("mix_percentual_canal") or []:
        lines.append(f"  {m.get('origem')}: {m.get('percentual_faturamento')}%")
    lines.append("")
    lines.append("--- Pagamentos (baixa_pagamento JSON ou formapagamento) ---")
    lines.append("(Categorias normalizadas: Dinheiro, PIX, cartoes, Vale, Transferencia, Outros)")
    for p in d.get("pagamentos_por_categoria") or []:
        lines.append(f"  {p.get('categoria')}: {_money_br(float(p.get('total') or 0))}")
    lines.append("")
    lines.append("--- Cancelamentos / itens removidos ---")
    lines.append(f"  Linhas ITEM_REMOVIDO: {d.get('item_removido_linhas')}")
    lines.append(f"  Valor (itens removidos): {_money_br(float(d.get('item_removido_valor') or 0))}")
    lines.append(f"  Taxa remocao sobre (recebido+removido) valor: {d.get('taxa_remocao_valor_pct')}%")
    lines.append("")
    lines.append("--- Comandas modificadas (status_comanda) ---")
    lines.append(f"  Pedidos distintos com MODIFICADA: {d.get('comandas_modificadas_pedidos')}")
    lines.append(f"  Destes, ainda nao RECEBIDO: {d.get('comandas_modificadas_nao_recebido_pedidos')}")
    lines.append("")
    lines.append("--- Comandas canceladas (status_comanda) ---")
    lines.append(f"  Pedidos distintos com CANCELADA: {d.get('comandas_canceladas_pedidos')}")
    lines.append(f"  Destes, ainda nao RECEBIDO: {d.get('comandas_canceladas_nao_recebido_pedidos')}")
    lines.append("")
    lines.append("--- Pedidos em AGUARDE no periodo (ainda no diario) ---")
    lines.append(f"  Pedidos distintos: {d.get('pedidos_aguarde_distintos_periodo')}")
    lines.append("")
    nc = d.get("novos_clientes_cadastro")
    lines.append("--- Novos clientes (cadastro) ---")
    lines.append(f"  Quantidade: {nc if nc is not None else '(coluna data_criacao indisponivel)'}")
    lines.append("")
    lines.append("--- Top produtos (RECEBIDO, por valor) ---")
    for i, t in enumerate(d.get("top_produtos") or [], 1):
        lines.append(
            f"  {i}. {(t.get('produto') or t.get('ref') or '-')[:60]} | "
            f"qtd={t.get('quantidade')} | {_money_br(float(t.get('total') or 0))}"
        )
    lines.append("")
    lines.append("--- Movimento por hora (RECEBIDO, soma itens) ---")
    for h in d.get("por_hora_recebido") or []:
        lines.append(
            f"  {int(h.get('hora') or 0):02d}h: itens={h.get('itens')} | {_money_br(float(h.get('total') or 0))}"
        )
    lines.append("")
    lines.append("================================================================")
    return "\n".join(lines)


def _gravar_relatorio_gerencial_txt(id_cliente: int, lote: str, conteudo: str) -> Tuple[str, str]:
    base = os.environ.get("LOJA_RELATORIOS_DIR", r"C:\Geral\Relatorios")
    dia = time.strftime("%Y-%m-%d")
    pasta = os.path.join(base, str(int(id_cliente)), dia)
    os.makedirs(pasta, exist_ok=True)
    sufixo = time.strftime("%H%M%S")
    nome = f"fechamento_{lote[:12]}_{sufixo}_gerencial.txt"
    caminho = os.path.join(pasta, nome)
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(conteudo)
    return caminho, nome


def _montar_relatorio_texto(
    id_cliente: int,
    lote: str,
    d0: datetime,
    d1: datetime,
    linhas: List[dict],
) -> str:
    linhas = linhas or []
    header = (
        f"FECHAMENTO DE PERÍODO (arquivo)\n"
        f"id_cliente={id_cliente}\n"
        f"lote={lote}\n"
        f"periodo_inicio={d0.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"periodo_fim_exclusivo={d1.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"linhas_arquivadas={len(linhas)}\n"
        f"---\n"
    )
    cols_pref = (
        "chave_orig",
        "origem",
        "nropedido",
        "status_pedido",
        "data_criacao",
        "produto",
        "quantidade",
        "preco",
        "formapagamento",
        "cliente",
    )
    body = "\t".join(cols_pref) + "\n"
    for r in linhas:
        row = []
        for c in cols_pref:
            if c == "chave_orig":
                row.append(str(r.get("chave_orig_pedido_diarios") or r.get("chave") or ""))
            else:
                row.append(str(r.get(c) if r.get(c) is not None else ""))
        body += "\t".join(row) + "\n"
    return header + body


def _gravar_relatorio_txt(id_cliente: int, lote: str, conteudo: str) -> Tuple[str, str]:
    base = os.environ.get("LOJA_RELATORIOS_DIR", r"C:\Geral\Relatorios")
    dia = time.strftime("%Y-%m-%d")
    pasta = os.path.join(base, str(int(id_cliente)), dia)
    os.makedirs(pasta, exist_ok=True)
    sufixo = time.strftime("%H%M%S")
    nome = f"fechamento_{lote[:12]}_{sufixo}.txt"
    caminho = os.path.join(pasta, nome)
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(conteudo)
    return caminho, nome


def executar_fechamento(id_cliente: int, data_inicio: str, data_fim: str) -> dict:
    """
    Transação: copia linhas elegíveis para pedido_periodos e remove de pedido_diarios.
    Em seguida grava .txt com o lote (dados lidos de pedido_periodos).
    """
    d0, d1 = intervalo_datetimes(data_inicio, data_fim)
    lote = uuid.uuid4().hex
    arquivado = datetime.now()
    conn = None
    cur = None
    try:
        conn = conectar()
        cur = conn.cursor()
        try:
            conn.start_transaction()
        except Exception:
            pass

        cur.execute("SELECT chave FROM pedido_diarios WHERE " + _where_fechamento(id_cliente, d0, d1)[0] + " FOR UPDATE", _where_fechamento(id_cliente, d0, d1)[1])
        chaves = [int(r[0]) for r in cur.fetchall() if r and r[0] is not None]
        if not chaves:
            conn.rollback()
            return {"sucesso": False, "erro": "Nenhuma linha elegível no período (recebido conforme origem / ITEM_REMOVIDO)."}

        cols = _colunas_pedido_diarios_sem_chave(cur)
        if not cols:
            conn.rollback()
            return {"sucesso": False, "erro": "Não foi possível ler colunas de pedido_diarios."}

        col_list = ", ".join(cols)
        # INSERT ... SELECT com colunas alinhadas + metadados
        sql_ins = (
            f"INSERT INTO pedido_periodos ({col_list}, arquivado_em, lote, chave_orig_pedido_diarios) "
            f"SELECT {col_list}, %s, %s, chave FROM pedido_diarios WHERE chave IN ({','.join(['%s'] * len(chaves))})"
        )
        params_ins = (arquivado, lote, *chaves)
        cur.execute(sql_ins, params_ins)

        gerencial: dict = {"sucesso": False, "texto_impressao": ""}
        cur_dict = conn.cursor(dictionary=True)
        try:
            gerencial = relatorio_gerencial_periodo(int(id_cliente), data_inicio, data_fim, cursor=cur_dict)
        except Exception as e_ger:
            gerencial = {"sucesso": False, "erro": str(e_ger), "texto_impressao": ""}
        finally:
            cur_dict.close()

        sql_del = f"DELETE FROM pedido_diarios WHERE chave IN ({','.join(['%s'] * len(chaves))})"
        cur.execute(sql_del, tuple(chaves))

        conn.commit()

        cur2 = conn.cursor(dictionary=True)
        cur2.execute(
            f"""
            SELECT chave, chave_orig_pedido_diarios, origem, nropedido, status_pedido, data_criacao,
                   produto, quantidade, preco, formapagamento, cliente
            FROM pedido_periodos
            WHERE id_cliente = %s AND lote = %s
            ORDER BY chave
            """,
            (int(id_cliente), lote),
        )
        rel_rows = list(cur2.fetchall() or [])
        cur2.close()

        texto = _montar_relatorio_texto(id_cliente, lote, d0, d1, rel_rows)
        caminho, nome = _gravar_relatorio_txt(id_cliente, lote, texto)

        out = {
            "sucesso": True,
            "lote": lote,
            "linhas_arquivadas": len(chaves),
            "arquivo": nome,
            "caminho": caminho,
        }
        if gerencial.get("sucesso") and str(gerencial.get("texto_impressao") or "").strip():
            try:
                c_ger, n_ger = _gravar_relatorio_gerencial_txt(id_cliente, lote, str(gerencial["texto_impressao"]))
                out["arquivo_gerencial"] = n_ger
                out["caminho_gerencial"] = c_ger
            except OSError as oe:
                out["arquivo_gerencial_erro"] = _mensagem_erro_relatorios(oe)
        elif not gerencial.get("sucesso"):
            out["relatorio_gerencial_erro"] = gerencial.get("erro") or "Falha ao montar relatório gerencial."

        return out
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        erro = _mensagem_erro_relatorios(e) if isinstance(e, OSError) else str(e)
        return {"sucesso": False, "erro": erro}
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def ensure_pedido_periodos_table() -> None:
    """Cria pedido_periodos a partir do layout atual de pedido_diarios e colunas de auditoria."""
    conn = None
    cur = None
    try:
        conn = conectar()
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS pedido_periodos LIKE pedido_diarios
            """
        )
        cur.execute("SHOW COLUMNS FROM pedido_periodos LIKE 'arquivado_em'")
        if cur.fetchone() is None:
            cur.execute(
                "ALTER TABLE pedido_periodos ADD COLUMN arquivado_em DATETIME NULL, "
                "ADD COLUMN lote VARCHAR(36) NULL, "
                "ADD COLUMN chave_orig_pedido_diarios INT NULL"
            )
        cur.execute("SHOW INDEX FROM pedido_periodos WHERE Key_name = 'idx_pp_cliente_arq'")
        if cur.fetchone() is None:
            try:
                cur.execute(
                    "CREATE INDEX idx_pp_cliente_arq ON pedido_periodos (id_cliente, arquivado_em)"
                )
            except Exception:
                pass
        conn.commit()
    except Exception as e:
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        print("[PEDIDO_PERIODOS TABELA ERRO]", e, flush=True)
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def ensure_purge_event() -> None:
    """Tenta registrar EVENT diário para expurgo > 1 ano (pode falhar sem privilégio)."""
    conn = None
    cur = None
    try:
        conn = conectar()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT COUNT(*) FROM information_schema.EVENTS
            WHERE EVENT_SCHEMA = DATABASE() AND EVENT_NAME = 'ev_loja_purge_pedido_periodos'
            """
        )
        n = int((cur.fetchone() or [0])[0])
        if n == 0:
            cur.execute(
                """
                CREATE EVENT ev_loja_purge_pedido_periodos
                ON SCHEDULE EVERY 1 DAY
                STARTS (TIMESTAMP(CURRENT_DATE) + INTERVAL 3 HOUR)
                DO
                  DELETE FROM pedido_periodos
                  WHERE arquivado_em IS NOT NULL
                    AND arquivado_em < DATE_SUB(NOW(), INTERVAL 1 YEAR)
                """
            )
            conn.commit()
    except Exception as e:
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        print("[PEDIDO_PERIODOS EVENT ERRO]", e, flush=True)
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
