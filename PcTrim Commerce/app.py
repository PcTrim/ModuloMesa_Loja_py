print("USANDO APP CERTO")
import os
print("TEMPLATE PATH:", os.path.abspath("templates"))

from dotenv import load_dotenv

load_dotenv()

from flask import Flask, render_template, jsonify, request, session, redirect, url_for, make_response, Response
import mysql.connector
import decimal
import traceback
from pprint import pprint
import requests
import math
import re
import sys
import time
import tempfile
import json
import unicodedata
from datetime import date, datetime, time as dt_time
from urllib.parse import quote

from config import Config
from version import get_app_version
from database import conectar
from auth_routes import auth_bp
from blueprints import register_domain_blueprints
from decorators import login_required, restaurant_only
from services.business_mode import is_retail
from services.dados_loja import obter_dados_loja
from services import uazapi as uazapi_service
from services import terminal_impressao as terminal_impressao_service
from services.fechamento_periodo import (
    ensure_pedido_periodos_table,
    ensure_purge_event,
    executar_fechamento,
    preview_fechamento,
    relatorio_gerencial_periodo,
    resumo_financeiro_fechamento,
)

_PYWIN32_SYS = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".venv", "Lib", "site-packages", "pywin32_system32")
if os.path.isdir(_PYWIN32_SYS):
    if _PYWIN32_SYS not in sys.path:
        sys.path.insert(0, _PYWIN32_SYS)
    os.environ["PATH"] = _PYWIN32_SYS + os.pathsep + os.environ.get("PATH", "")
    if hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(_PYWIN32_SYS)
        except Exception:
            pass

try:
    import win32print
except Exception:
    win32print = None
try:
    from deploy.print_bridge.printer_match import (
        find_best_printer_match as _find_best_printer_match,
        normalize_printer_name as _normalize_printer_name,
        resolve_windows_printer as _resolve_windows_printer,
    )
except ImportError:
    try:
        from printer_match import (
            find_best_printer_match as _find_best_printer_match,
            normalize_printer_name as _normalize_printer_name,
            resolve_windows_printer as _resolve_windows_printer,
        )
    except ImportError:
        _find_best_printer_match = None
        _normalize_printer_name = None
        _resolve_windows_printer = None

try:
    import win32api
except Exception:
    win32api = None


_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
Config.validate_required()
app = Flask(__name__, template_folder="templates", static_folder=os.path.join(_BASE_DIR, "static"))
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.secret_key = Config.SECRET_KEY
app.config["SESSION_COOKIE_SAMESITE"] = Config.SESSION_COOKIE_SAMESITE
app.config["SESSION_COOKIE_SECURE"] = Config.SESSION_COOKIE_SECURE
if Config.SESSION_COOKIE_DOMAIN:
    app.config["SESSION_COOKIE_DOMAIN"] = Config.SESSION_COOKIE_DOMAIN
if Config.URL_PREFIX:
    app.config["APPLICATION_ROOT"] = Config.URL_PREFIX
    app.config["SESSION_COOKIE_PATH"] = Config.URL_PREFIX


class _PrefixMiddleware:
    def __init__(self, wsgi_app, prefix: str):
        self.wsgi_app = wsgi_app
        self.prefix = (prefix or "").rstrip("/")

    def __call__(self, environ, start_response):
        prefix = self.prefix
        if prefix:
            path = (environ.get("PATH_INFO") or "") or "/"
            if path == prefix:
                environ["SCRIPT_NAME"] = prefix
                environ["PATH_INFO"] = "/"
            elif path.startswith(prefix + "/"):
                environ["SCRIPT_NAME"] = prefix
                environ["PATH_INFO"] = path[len(prefix) :] or "/"
        return self.wsgi_app(environ, start_response)


if Config.URL_PREFIX:
    app.wsgi_app = _PrefixMiddleware(app.wsgi_app, Config.URL_PREFIX)
app.register_blueprint(auth_bp)
register_domain_blueprints(app)


@app.context_processor
def inject_app_globals():
    retail = is_retail()
    return {
        "app_version": get_app_version(),
        "url_prefix": Config.URL_PREFIX,
        "business_type": "varejo" if retail else "restaurante",
        "is_retail": retail,
        "IS_RETAIL": retail,
        "is_platform_admin": Config.is_platform_admin(session.get("usuario_logado")),
    }


@app.after_request
def _evitar_cache_html(response):
    """Respostas HTML sempre frescas — evita ver layout antigo por cache do navegador."""
    ct = response.headers.get("Content-Type", "")
    if "text/html" in ct:
        response.headers["Cache-Control"] = "no-store, max-age=0, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        response.headers["X-App-Version"] = get_app_version()
    return response


@app.errorhandler(404)
def _api_not_found(e):
    try:
        if str(request.path or "").startswith("/api/"):
            return jsonify({"sucesso": False, "erro": "Rota não encontrada.", "path": request.path}), 404
    except Exception:
        pass
    return e


@app.errorhandler(405)
def _api_method_not_allowed(e):
    try:
        if str(request.path or "").startswith("/api/"):
            allow = None
            try:
                allow = sorted(list(getattr(e, "valid_methods", None) or []))
            except Exception:
                allow = None
            return jsonify({
                "sucesso": False,
                "erro": "Método não permitido.",
                "path": request.path,
                "method": request.method,
                "allow": allow,
            }), 405
    except Exception:
        pass
    return e


# ROTA PARA EXIBIR A PÁGINA DE FORMAS DE PAGAMENTO
@app.route('/formas-pagamento', methods=['GET'])
@login_required
def formas_pagamento_page():
    return render_template('formas_pagamento.html')

# ROTA PARA CONFIGURAÇÕES
@app.route('/configuracoes')
@login_required
def configuracoes():
    id_cliente = session.get("id_cliente")
    dados_loja = obter_dados_loja(id_cliente) or {}
    nome_fantasia = dados_loja.get("nome", "Minha Loja")
    return render_template(
        "configuracoes.html",
        id_cliente=id_cliente,
        nome_fantasia=nome_fantasia,
    )


@app.route("/configuracoes-dados")
@login_required
def configuracoes_dados():
    """Tabela de configurações (JSON) — link a partir do painel de configurações."""
    return render_template("configuracoes_dados.html")


def _append_loja_erro_log(titulo, detalhes_texto):
    """Registra erros em disco (útil quando o app roda com pythonw.exe sem console)."""
    path = os.path.join(_BASE_DIR, "loja_erros.log")
    try:
        bloco = (
            f"\n{'=' * 60}\n"
            f"{time.strftime('%Y-%m-%d %H:%M:%S')} {titulo}\n"
            f"{detalhes_texto}\n"
        )
        with open(path, "a", encoding="utf-8") as f:
            f.write(bloco)
    except Exception as log_exc:
        try:
            print("[LOJA_ERROS.LOG]", log_exc, flush=True)
        except Exception:
            pass


# ===================== API /casa (deliverypendente) =====================
def _ensure_obs_columns():
    conn = None
    cur = None
    try:
        conn = conectar()
        cur = conn.cursor()
        cur.execute("SHOW COLUMNS FROM deliverypendente LIKE 'obs_item'")
        if cur.fetchone() is None:
            cur.execute("ALTER TABLE deliverypendente ADD COLUMN obs_item TEXT NULL")
        cur.execute("SHOW COLUMNS FROM deliverypendente LIKE 'obs_geral'")
        if cur.fetchone() is None:
            cur.execute("ALTER TABLE deliverypendente ADD COLUMN obs_geral TEXT NULL")
        cur.execute("SHOW TABLES LIKE 'mesa'")
        if cur.fetchone() is not None:
            cur.execute("SHOW COLUMNS FROM mesa LIKE 'obs_item'")
            if cur.fetchone() is None:
                cur.execute("ALTER TABLE mesa ADD COLUMN obs_item TEXT NULL")
        conn.commit()
    except Exception as e:
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        print("[OBS COLUNAS ERRO]", e, flush=True)
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

def _buscar_nropedido_aguarde_por_telefone(cur, id_cliente, telefone_raw):
    tel_digits = "".join(ch for ch in str(telefone_raw or "") if ch.isdigit())
    if not tel_digits:
        return None
    cur.execute(
        """
        SELECT nropedido, telefone
        FROM pedido_diarios
        WHERE id_cliente = %s
          AND origem = 'DELIVERY'
          AND UPPER(COALESCE(status_pedido, '')) = 'AGUARDE'
          AND UPPER(COALESCE(status_pedido, '')) <> 'ITEM_REMOVIDO'
        ORDER BY nropedido ASC
        """,
        (id_cliente,),
    )
    rows = cur.fetchall() or []
    for row in rows:
        db_tel = "".join(ch for ch in str((row or {}).get("telefone") or "") if ch.isdigit())
        if not db_tel:
            continue
        if db_tel == tel_digits or db_tel.endswith(tel_digits) or tel_digits.endswith(db_tel):
            try:
                return int((row or {}).get("nropedido") or 0) or None
            except Exception:
                continue
    return None

def _telefones_compativeis(a_raw, b_raw):
    a = "".join(ch for ch in str(a_raw or "") if ch.isdigit())
    b = "".join(ch for ch in str(b_raw or "") if ch.isdigit())
    if not a or not b:
        return False
    return a == b or a.endswith(b) or b.endswith(a)


def _sql_historico_cliente_recebido(table_name: str) -> str:
    arq_col = "arquivado_em" if table_name == "pedido_periodos" else "NULL AS arquivado_em"
    return f"""
        SELECT origem, nropedido, data_criacao, {arq_col}, telefone, produto,
               quantidade, preco, obs_item, obs_geral
        FROM {table_name}
        WHERE id_cliente = %s
          AND UPPER(TRIM(COALESCE(origem, ''))) IN ('DELIVERY', 'BALCAO')
          AND UPPER(TRIM(COALESCE(status_pedido, ''))) = 'RECEBIDO'
        ORDER BY data_criacao DESC, chave DESC
        LIMIT 2000
    """


def _filtrar_linhas_historico_por_telefone(rows, telefone):
    out = []
    for row in rows or []:
        if _telefones_compativeis((row or {}).get("telefone"), telefone):
            out.append(row)
    return out


def _agrupar_pedidos_historico_cliente(rows):
    pedidos = {}
    for row in rows or []:
        origem = str((row or {}).get("origem") or "").strip().upper() or "DELIVERY"
        nro = int((row or {}).get("nropedido") or 0)
        if nro <= 0:
            continue
        key = (origem, nro)
        bucket = pedidos.get(key)
        data_ref = (row or {}).get("data_criacao") or (row or {}).get("arquivado_em") or ""
        if bucket is None:
            bucket = {
                "nropedido": nro,
                "origem": origem,
                "data": str(data_ref) if data_ref is not None else "",
                "_data_sort": data_ref,
                "obs_geral": str((row or {}).get("obs_geral") or "").strip(),
                "itens": [],
            }
            pedidos[key] = bucket
        elif data_ref and (not bucket.get("_data_sort") or str(data_ref) > str(bucket.get("_data_sort") or "")):
            bucket["_data_sort"] = data_ref
            bucket["data"] = str(data_ref)
        if not bucket.get("obs_geral"):
            og = str((row or {}).get("obs_geral") or "").strip()
            if og:
                bucket["obs_geral"] = og
        item_nome = str((row or {}).get("produto") or "").strip()
        if item_nome:
            bucket["itens"].append(
                {
                    "produto": item_nome,
                    "quantidade": float((row or {}).get("quantidade") or 0),
                    "preco": float((row or {}).get("preco") or 0),
                    "obs_item": str((row or {}).get("obs_item") or "").strip(),
                }
            )
    ordered = sorted(
        pedidos.values(),
        key=lambda x: (str(x.get("_data_sort") or ""), int(x.get("nropedido") or 0)),
        reverse=True,
    )
    for b in ordered:
        b.pop("_data_sort", None)
    return ordered


def _historico_cliente_from_pedido_tabelas(cur, id_cliente, telefone):
    rows = []
    for tbl in ("pedido_diarios", "pedido_periodos"):
        try:
            cur.execute(_sql_historico_cliente_recebido(tbl), (id_cliente,))
            rows.extend(cur.fetchall() or [])
        except Exception:
            continue
    rows = _filtrar_linhas_historico_por_telefone(rows, telefone)
    return _agrupar_pedidos_historico_cliente(rows)


def _historico_cliente_from_liquidada(cur, id_cliente, telefone):
    cur.execute(
        """
        SELECT *
        FROM liquidada
        WHERE id_cliente = %s
        ORDER BY chave DESC
        LIMIT 2000
        """,
        (id_cliente,),
    )
    all_rows = cur.fetchall() or []
    rows = _filtrar_linhas_historico_por_telefone(all_rows, telefone)
    pedidos = {}
    for row in rows:
        nro = int(row.get("nropedido") or 0)
        if nro <= 0:
            continue
        key = ("LEGADO", nro)
        bucket = pedidos.get(key)
        if bucket is None:
            data_ref = (
                row.get("data_criacao")
                or row.get("data")
                or row.get("datapedido")
                or row.get("datahora")
                or row.get("created_at")
                or ""
            )
            bucket = {
                "nropedido": nro,
                "origem": "LEGADO",
                "data": str(data_ref) if data_ref is not None else "",
                "_data_sort": data_ref,
                "obs_geral": str(row.get("obs_geral") or "").strip(),
                "itens": [],
            }
            pedidos[key] = bucket
        item_nome = str(row.get("produto") or "").strip()
        if item_nome:
            bucket["itens"].append(
                {
                    "produto": item_nome,
                    "quantidade": float(row.get("quantidade") or 0),
                    "preco": float(row.get("preco") or 0),
                    "obs_item": str(row.get("obs_item") or "").strip(),
                }
            )
    ordered = sorted(
        pedidos.values(),
        key=lambda x: (str(x.get("_data_sort") or ""), int(x.get("nropedido") or 0)),
        reverse=True,
    )
    for b in ordered:
        b.pop("_data_sort", None)
    return ordered


def _enriquecer_descricao_produto_pedido_rows(cur, id_cliente, rows):
    """
    Preenche descricao_produto sem JOIN na query principal (evita erro SQL com
    codigoproduto não numérico, p.ex. AJUSTE_TECNICO, e diferenças de modo estrito).
    """
    if not rows or id_cliente is None:
        return
    chaves_unicas = set()
    for r in rows:
        cp = str((r or {}).get("codigoproduto") or "").strip()
        if cp.isdigit():
            try:
                chaves_unicas.add(int(cp))
            except (TypeError, ValueError):
                pass
    desc_map = {}
    if chaves_unicas:
        lista = sorted(chaves_unicas)
        ph = ",".join(["%s"] * len(lista))
        cur.execute(
            f"SELECT chave, IFNULL(descricao, '') AS descricao FROM produtos WHERE id_cliente = %s AND chave IN ({ph})",
            (id_cliente, *lista),
        )
        for pr in cur.fetchall() or []:
            if pr:
                desc_map[int(pr.get("chave"))] = str(pr.get("descricao") or "")
    for r in rows:
        if not r:
            continue
        cp = str(r.get("codigoproduto") or "").strip()
        if cp.isdigit():
            try:
                r["descricao_produto"] = desc_map.get(int(cp), "")
            except (TypeError, ValueError):
                r["descricao_produto"] = ""
        else:
            r["descricao_produto"] = ""


def _insert_pedido_diarios_from_casa(
    cur,
    *,
    origem,
    nropedido,
    id_cliente,
    telefone,
    cep,
    nome,
    endereco,
    nrocasa,
    complemento,
    codigoproduto,
    produto,
    preco,
    quantidade,
    classe,
    obs_item,
    dados_item,
    obs_geral,
    cliente,
    cod_classe,
    cod_usuario,
    status_pedido,
    status_comanda,
    lancamento,
    nrolancamento,
    formapagamento,
    entregador,
):
    cols = [
        "origem",
        "nropedido",
        "status_pedido",
        "status_comanda",
        "telefone",
        "cep",
        "nome",
        "endereco",
        "nrocasa",
        "complemento",
        "codigoproduto",
        "produto",
        "preco",
        "quantidade",
        "obs_item",
        "dados_item",
        "obs_geral",
        "classe",
        "cod_classe",
        "cod_usuario",
        "cliente",
        "id_cliente",
        "formapagamento",
        "lancamento",
        "nrolancamento",
        "entregador",
    ]
    vals = [
        str(origem or "").strip().upper(),
        int(nropedido),
        str(status_pedido or "AGUARDE"),
        str(status_comanda or "NORMAL"),
        str(telefone or ""),
        str(cep or ""),
        str(nome or ""),
        str(endereco or ""),
        str(nrocasa or ""),
        str(complemento or ""),
        str(codigoproduto or ""),
        str(produto or ""),
        float(preco or 0),
        float(quantidade or 1),
        str(obs_item or ""),
        str(dados_item or ""),
        str(obs_geral or ""),
        str(classe or ""),
        cod_classe,
        cod_usuario,
        str(cliente or ""),
        int(id_cliente),
        str(formapagamento or ""),
        int(lancamento or 0) if lancamento is not None else None,
        int(nrolancamento or 0) if nrolancamento is not None else None,
        str(entregador or ""),
    ]
    ph = ", ".join(["%s"] * len(cols))
    cur.execute(
        f"INSERT INTO pedido_diarios ({', '.join(cols)}) VALUES ({ph})",
        tuple(vals),
    )


STATUS_COMANDA_CANCELADA = "CANCELADA"
_STATUS_PEDIDO_CANCELAVEL = frozenset({"ABERTO", "ABERTA", "AGUARDE", "ROTA"})
_MSG_CASA_BLOQUEADO = "Comanda cancelada ou pedido em ROTA/RECEBIDO não pode ser alterado na tela /casa."


def _sql_comanda_cancelada(alias="pd"):
    return f"UPPER(TRIM(COALESCE({alias}.status_comanda, ''))) = 'CANCELADA'"


def _origem_delivery_balcao_valida(origem):
    return str(origem or "").strip().upper() in ("DELIVERY", "BALCAO")


def _casa_forcar_balcao_se_varejo(data):
    if not is_retail():
        return data
    if data is None:
        data = {}
    elif not isinstance(data, dict):
        data = dict(data)
    else:
        data = dict(data)
    data["modo"] = "balcao"
    data["origem"] = "BALCAO"
    return data


def _comanda_esta_cancelada(cur, id_cliente, origem, nropedido):
    orig = str(origem or "").strip().upper()
    if not _origem_delivery_balcao_valida(orig):
        return False
    cur.execute(
        f"""
        SELECT 1
        FROM pedido_diarios
        WHERE id_cliente = %s AND origem = %s AND nropedido = %s
          AND {_sql_comanda_cancelada('pedido_diarios')}
        LIMIT 1
        """,
        (int(id_cliente), orig, int(nropedido)),
    )
    return cur.fetchone() is not None


def _sql_linha_ativa_pedido(alias="pd"):
    """Linha ativa da comanda: status_pedido diferente de ITEM_REMOVIDO."""
    return f"UPPER(TRIM(COALESCE({alias}.status_pedido, ''))) <> 'ITEM_REMOVIDO'"


def _comanda_pode_cancelar(cur, id_cliente, origem, nropedido):
    orig = str(origem or "").strip().upper()
    if not _origem_delivery_balcao_valida(orig):
        return False, "Origem inválida. Use DELIVERY ou BALCAO."
    np = int(nropedido or 0)
    if np <= 0:
        return False, "Número do pedido inválido."
    cur.execute(
        """
        SELECT COUNT(*) AS n
        FROM pedido_diarios
        WHERE id_cliente = %s AND origem = %s AND nropedido = %s
        """,
        (int(id_cliente), orig, np),
    )
    row_n = cur.fetchone() or {}
    total_linhas = int((row_n.get("n") if isinstance(row_n, dict) else row_n[0]) or 0)
    if total_linhas <= 0:
        return False, "Pedido não encontrado."
    if _comanda_esta_cancelada(cur, id_cliente, orig, np):
        return False, "Comanda já está cancelada."
    cur.execute(
        f"""
        SELECT 1
        FROM pedido_diarios pd
        WHERE pd.id_cliente = %s AND pd.origem = %s AND pd.nropedido = %s
          AND {_sql_linha_ativa_pedido('pd')}
          AND UPPER(TRIM(COALESCE(pd.status_pedido, ''))) = 'RECEBIDO'
        LIMIT 1
        """,
        (int(id_cliente), orig, np),
    )
    if cur.fetchone():
        return False, "Pedido já RECEBIDO não pode ser cancelado."
    cur.execute(
        f"""
        SELECT UPPER(TRIM(COALESCE(pd.status_pedido, ''))) AS st
        FROM pedido_diarios pd
        WHERE pd.id_cliente = %s AND pd.origem = %s AND pd.nropedido = %s
          AND {_sql_linha_ativa_pedido('pd')}
        """,
        (int(id_cliente), orig, np),
    )
    rows = cur.fetchall() or []
    if not rows:
        return True, ""
    ativas = []
    for row in rows:
        if isinstance(row, dict):
            st = str(row.get("st") or "").strip().upper()
        else:
            st = str(row[0] or "").strip().upper()
        ativas.append(st)
    invalidas = [st for st in ativas if st not in _STATUS_PEDIDO_CANCELAVEL]
    if invalidas:
        return False, f"Status do pedido ({invalidas[0]}) não permite cancelamento."
    return True, ""


def _casa_pedido_bloqueado_info(cur, id_cliente, nropedido, origem=None):
    params = [int(nropedido), int(id_cliente)]
    if origem and _origem_delivery_balcao_valida(origem):
        orig_clause = " AND origem = %s "
        params.append(str(origem).strip().upper())
    else:
        orig_clause = " AND origem IN ('DELIVERY','BALCAO') "
    cur.execute(
        f"""
        SELECT 1
        FROM pedido_diarios
        WHERE nropedido = %s AND id_cliente = %s {orig_clause}
          AND {_sql_comanda_cancelada('pedido_diarios')}
        LIMIT 1
        """,
        tuple(params),
    )
    if cur.fetchone():
        return {"bloqueado": True, "comanda_cancelada": True, "motivo_bloqueio": "Comanda cancelada."}
    cur.execute(
        f"""
        SELECT 1
        FROM pedido_diarios
        WHERE nropedido = %s AND id_cliente = %s {orig_clause}
          AND UPPER(TRIM(COALESCE(status_pedido, ''))) IN ('RECEBIDO','ROTA')
        LIMIT 1
        """,
        tuple(params),
    )
    if cur.fetchone():
        return {
            "bloqueado": True,
            "comanda_cancelada": False,
            "motivo_bloqueio": "Pedido em ROTA ou já RECEBIDO.",
        }
    return {"bloqueado": False, "comanda_cancelada": False, "motivo_bloqueio": ""}


def _assert_casa_editavel(cur, id_cliente, nropedido, origem=None):
    info = _casa_pedido_bloqueado_info(cur, id_cliente, nropedido, origem)
    if info.get("bloqueado"):
        return jsonify({"sucesso": False, "erro": _MSG_CASA_BLOQUEADO}), 409
    return None


def _ensure_status_comanda_column():
    conn = None
    cur = None
    try:
        conn = conectar()
        cur = conn.cursor()
        cur.execute("SHOW COLUMNS FROM deliverypendente LIKE 'status_comanda'")
        if cur.fetchone() is None:
            cur.execute("ALTER TABLE deliverypendente ADD COLUMN status_comanda VARCHAR(20) NULL")
            conn.commit()
    except Exception as e:
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        print("[STATUS_COMANDA COLUNA ERRO]", e, flush=True)
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

def _ensure_pedido_diarios_table():
    conn = None
    cur = None
    try:
        conn = conectar()
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS pedido_diarios (
                chave INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                origem VARCHAR(20) NOT NULL,
                nropedido INT NOT NULL,
                status_pedido VARCHAR(20) NULL,
                status_comanda VARCHAR(30) NULL,
                telefone VARCHAR(30) NULL,
                cep VARCHAR(20) NULL,
                nome VARCHAR(255) NULL,
                endereco VARCHAR(255) NULL,
                nrocasa VARCHAR(40) NULL,
                complemento VARCHAR(120) NULL,
                referencia VARCHAR(255) NULL,
                bairro VARCHAR(120) NULL,
                cidade VARCHAR(120) NULL,
                estado VARCHAR(10) NULL,
                codigoproduto VARCHAR(80) NULL,
                produto VARCHAR(255) NOT NULL,
                preco DECIMAL(10,2) DEFAULT 0,
                quantidade DECIMAL(10,3) DEFAULT 1,
                obs_item TEXT NULL,
                dados_item TEXT NULL,
                obs_geral TEXT NULL,
                classe VARCHAR(120) NULL,
                cod_classe INT NULL,
                cod_usuario INT NULL,
                cliente VARCHAR(255) NULL,
                id_cliente INT NOT NULL,
                formapagamento VARCHAR(80) NULL,
                lancamento INT NULL,
                nrolancamento BIGINT NULL,
                data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_pd_cliente_pedido (id_cliente, nropedido),
                INDEX idx_pd_origem_status (origem, status_pedido),
                INDEX idx_pd_status_comanda (status_comanda),
                INDEX idx_pd_codproduto (codigoproduto),
                INDEX idx_pd_lancamento (lancamento, nrolancamento)
            )
            """
        )
        cur.execute("SHOW COLUMNS FROM pedido_diarios LIKE 'status_mesa'")
        if cur.fetchone() is None:
            cur.execute("ALTER TABLE pedido_diarios ADD COLUMN status_mesa VARCHAR(20) NULL AFTER nropedido")
        cur.execute("SHOW COLUMNS FROM pedido_diarios LIKE 'entregador'")
        if cur.fetchone() is None:
            cur.execute("ALTER TABLE pedido_diarios ADD COLUMN entregador VARCHAR(150) NULL AFTER classe")
        cur.execute("SHOW COLUMNS FROM pedido_diarios LIKE 'dados_item'")
        if cur.fetchone() is None:
            cur.execute("ALTER TABLE pedido_diarios ADD COLUMN dados_item TEXT NULL AFTER obs_item")
        cur.execute("SHOW COLUMNS FROM pedido_diarios LIKE 'baixa_pagamento'")
        if cur.fetchone() is None:
            cur.execute("ALTER TABLE pedido_diarios ADD COLUMN baixa_pagamento TEXT NULL AFTER formapagamento")
        conn.commit()
    except Exception as e:
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        print("[PEDIDO_DIARIOS TABELA ERRO]", e, flush=True)
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def _ensure_formapagamento_troco_column():
    conn = None
    cur = None
    try:
        conn = conectar()
        cur = conn.cursor()
        cur.execute("SHOW COLUMNS FROM formapagamento LIKE 'troco'")
        if cur.fetchone() is None:
            cur.execute(
                "ALTER TABLE formapagamento ADD COLUMN troco CHAR(1) NOT NULL DEFAULT 'N' AFTER forma"
            )
        conn.commit()
    except Exception as e:
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        print("[FORMAPAGAMENTO TROCO COLUNA ERRO]", e, flush=True)
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def _ensure_pedido_diarios_valor_pago_troco():
    conn = None
    cur = None
    try:
        conn = conectar()
        cur = conn.cursor()
        cur.execute("SHOW COLUMNS FROM pedido_diarios LIKE 'valor_pago_troco'")
        if cur.fetchone() is None:
            cur.execute(
                "ALTER TABLE pedido_diarios ADD COLUMN valor_pago_troco DECIMAL(12,2) NULL AFTER formapagamento"
            )
        conn.commit()
    except Exception as e:
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        print("[PEDIDO_DIARIOS VALOR_PAGO_TROCO ERRO]", e, flush=True)
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def _ensure_pedido_diarios_preparo_columns():
    conn = None
    cur = None
    try:
        conn = conectar()
        cur = conn.cursor()
        cur.execute("SHOW COLUMNS FROM pedido_diarios LIKE 'imp_preparo'")
        if cur.fetchone() is None:
            cur.execute(
                "ALTER TABLE pedido_diarios ADD COLUMN imp_preparo CHAR(1) NOT NULL DEFAULT 'N' AFTER dados_item"
            )
        cur.execute("SHOW COLUMNS FROM pedido_diarios LIKE 'imp_preparo_em'")
        if cur.fetchone() is None:
            cur.execute("ALTER TABLE pedido_diarios ADD COLUMN imp_preparo_em DATETIME NULL AFTER imp_preparo")
        conn.commit()
    except Exception as e:
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        print("[PEDIDO_DIARIOS PREPARO COLUNAS ERRO]", e, flush=True)
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def _preencher_impressoras_produto(cur, id_cliente, rows, src_cod_field="codigoproduto", dest_field="impressoras_produto"):
    if not id_cliente or not rows:
        return
    def _code_variants(v):
        s = str(v or "").strip()
        if not s:
            return []
        out = [s]
        s2 = s.strip()
        if s2.isdigit():
            nz = s2.lstrip("0") or "0"
            if nz not in out:
                out.append(nz)
        return out
    precisa = False
    for r in rows:
        try:
            v = (r.get(dest_field) if isinstance(r, dict) else None) or ""
        except Exception:
            v = ""
        if not str(v).strip():
            precisa = True
            break
    if not precisa:
        return
    codes = []
    for r in rows:
        try:
            v = r.get(src_cod_field) if isinstance(r, dict) else None
        except Exception:
            v = None
        for sv in _code_variants(v):
            if sv:
                codes.append(sv)
    codes = list(dict.fromkeys(codes))
    if not codes:
        return
    try:
        cur.execute("SHOW COLUMNS FROM produtos")
        cols = cur.fetchall() or []
    except Exception:
        return
    col_names = []
    for c in cols:
        if isinstance(c, dict):
            col_names.append(str(c.get("Field") or ""))
        elif isinstance(c, (list, tuple)) and c:
            col_names.append(str(c[0] or ""))
    col_set = {c.lower() for c in col_names if c}
    setor_col = None
    if "impressora" in col_set:
        setor_col = "impressora"
    elif "impressoras" in col_set:
        setor_col = "impressoras"
    if not setor_col:
        return
    candidates = [
        "chave",
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
    ]
    match_cols = []
    for c in candidates:
        if c.lower() in col_set and c not in match_cols:
            match_cols.append(c)
    if "chave" not in match_cols:
        match_cols.insert(0, "chave")
    ph = ",".join(["%s"] * len(codes))
    where_parts = []
    params = [int(id_cliente)]
    for c in match_cols:
        where_parts.append(f"p.{c} IN ({ph})")
        params.extend(codes)
    where_sql = " OR ".join(where_parts) if where_parts else "1=0"
    sel_cols = ", ".join([f"p.{c} AS {c}" for c in match_cols if c != "chave"])
    if sel_cols:
        sel_cols = ", " + sel_cols
    q = f"SELECT p.chave AS chave, COALESCE(p.{setor_col},'') AS setor{sel_cols} FROM produtos p WHERE p.id_cliente = %s AND ({where_sql})"
    try:
        cur.execute(q, tuple(params))
        prod_rows = cur.fetchall() or []
    except Exception:
        return
    mapa = {}
    for pr in prod_rows:
        if not isinstance(pr, dict):
            continue
        setor = str(pr.get("setor") or "").strip()
        if not setor:
            continue
        for c in match_cols:
            if c == "chave":
                vv = pr.get("chave")
            else:
                vv = pr.get(c)
            for sv in _code_variants(vv):
                if sv and sv not in mapa:
                    mapa[sv] = setor
    if not mapa:
        return
    for r in rows:
        if not isinstance(r, dict):
            continue
        cur_setor = str(r.get(dest_field) or "").strip()
        if cur_setor:
            continue
        key_raw = r.get(src_cod_field)
        for key in _code_variants(key_raw):
            if key and key in mapa:
                r[dest_field] = mapa[key]
                break


def _forma_pagamento_exige_troco(cur, id_cliente, nome_forma):
    """True se cadastro da forma indica troco (S/SIM/1/Y)."""
    if not id_cliente or not (nome_forma or "").strip():
        return False
    cur.execute("SHOW COLUMNS FROM formapagamento LIKE 'troco'")
    if cur.fetchone() is None:
        return False
    cur.execute(
        """
        SELECT UPPER(TRIM(COALESCE(troco, ''))) AS t
        FROM formapagamento
        WHERE id_cliente = %s AND UPPER(TRIM(forma)) = UPPER(TRIM(%s))
        LIMIT 1
        """,
        (id_cliente, nome_forma.strip()),
    )
    row = cur.fetchone()
    if not row:
        return False
    if isinstance(row, dict):
        t = str(row.get("t") or "").strip().upper()
    else:
        t = str(row[0] or "").strip().upper()
    return t in ("S", "SIM", "1", "Y")


def _ensure_classificacao_opcoes_columns():
    conn = None
    cur = None
    try:
        conn = conectar()
        cur = conn.cursor()
        cur.execute("SHOW COLUMNS FROM classificacao LIKE 'op_tamanhos'")
        if cur.fetchone() is None:
            cur.execute("ALTER TABLE classificacao ADD COLUMN op_tamanhos TEXT NULL")
        cur.execute("SHOW COLUMNS FROM classificacao LIKE 'op_massas'")
        if cur.fetchone() is None:
            cur.execute("ALTER TABLE classificacao ADD COLUMN op_massas TEXT NULL")
        cur.execute("SHOW COLUMNS FROM classificacao LIKE 'op_bordas'")
        if cur.fetchone() is None:
            cur.execute("ALTER TABLE classificacao ADD COLUMN op_bordas TEXT NULL")
        cur.execute("SHOW COLUMNS FROM classificacao LIKE 'op_coberturas'")
        if cur.fetchone() is None:
            cur.execute("ALTER TABLE classificacao ADD COLUMN op_coberturas TEXT NULL")
        cur.execute("SHOW COLUMNS FROM classificacao LIKE 'op_adicionais'")
        if cur.fetchone() is None:
            cur.execute("ALTER TABLE classificacao ADD COLUMN op_adicionais TEXT NULL")
        conn.commit()
    except Exception as e:
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        print("[CLASSIFICACAO OPCOES COLUNAS ERRO]", e, flush=True)
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def _ensure_produtos_barcode_column():
    conn = None
    cur = None
    try:
        conn = conectar()
        cur = conn.cursor()
        cur.execute("SHOW COLUMNS FROM produtos LIKE 'barcode'")
        if cur.fetchone() is None:
            cur.execute("ALTER TABLE produtos ADD COLUMN barcode VARCHAR(50) NULL DEFAULT NULL")
        conn.commit()
    except Exception as e:
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        print("[PRODUTOS BARCODE COLUNA ERRO]", e, flush=True)
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def _ensure_tipo_negocio_column():
    conn = None
    cur = None
    try:
        conn = conectar()
        cur = conn.cursor()
        cur.execute("SHOW COLUMNS FROM dadosloja LIKE 'tipo_negocio'")
        if cur.fetchone() is None:
            cur.execute(
                "ALTER TABLE dadosloja ADD COLUMN tipo_negocio VARCHAR(20) NOT NULL DEFAULT 'restaurante'"
            )
        conn.commit()
    except Exception as e:
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        print("[DADOSLOJA TIPO_NEGOCIO COLUNA ERRO]", e, flush=True)
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def bootstrap_schema():
    try:
        _ensure_tipo_negocio_column()
        _ensure_obs_columns()
        _ensure_produtos_barcode_column()
        _ensure_status_comanda_column()
        _ensure_pedido_diarios_table()
        _ensure_formapagamento_troco_column()
        _ensure_pedido_diarios_valor_pago_troco()
        ensure_pedido_periodos_table()
        ensure_purge_event()
        _ensure_classificacao_opcoes_columns()
        _ensure_impressoras_table()
        _ensure_terminal_impressora_table()
        _ensure_whatsapp_config_table()
        _ensure_whatsapp_log_table()
    except Exception as e:
        print("[SCHEMA BOOTSTRAP ERRO]", e, flush=True)
        traceback.print_exc()


def _ensure_impressoras_table():
    conn = None
    cur = None
    try:
        conn = conectar()
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS impressoras (
                id INT AUTO_INCREMENT PRIMARY KEY,
                nomedaimpressora VARCHAR(255) NOT NULL,
                imprenro TINYINT NOT NULL DEFAULT 0
            )
            """
        )
        cur.execute("SHOW COLUMNS FROM impressoras LIKE 'imprenro'")
        if not cur.fetchone():
            cur.execute("ALTER TABLE impressoras ADD COLUMN imprenro TINYINT NOT NULL DEFAULT 0")
        cur.execute("SHOW COLUMNS FROM impressoras LIKE 'caminho'")
        if not cur.fetchone():
            cur.execute("ALTER TABLE impressoras ADD COLUMN caminho VARCHAR(512) DEFAULT ''")
        cur.execute("SHOW COLUMNS FROM impressoras LIKE 'conta_mesa'")
        if not cur.fetchone():
            cur.execute("ALTER TABLE impressoras ADD COLUMN conta_mesa VARCHAR(1) DEFAULT 'N'")
        cur.execute("SHOW COLUMNS FROM impressoras LIKE 'comanda_delivery'")
        if not cur.fetchone():
            cur.execute("ALTER TABLE impressoras ADD COLUMN comanda_delivery VARCHAR(1) DEFAULT 'N'")
        cur.execute("SHOW COLUMNS FROM impressoras LIKE 'feed_final_linhas'")
        if not cur.fetchone():
            cur.execute("ALTER TABLE impressoras ADD COLUMN feed_final_linhas TINYINT NOT NULL DEFAULT 6")
        cur.execute("SHOW COLUMNS FROM impressoras LIKE 'id_cliente'")
        if not cur.fetchone():
            cur.execute("ALTER TABLE impressoras ADD COLUMN id_cliente INT DEFAULT NULL")
        cur.execute("SHOW COLUMNS FROM impressoras LIKE 'data_criacao'")
        if not cur.fetchone():
            cur.execute("ALTER TABLE impressoras ADD COLUMN data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        conn.commit()
    except Exception as e:
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        print("[IMPRESSORAS TABELA ERRO]", e, flush=True)
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def _ensure_terminal_impressora_table():
    """Mapeamento terminal (PC) -> caminho_local por impressora lógica."""
    conn = None
    cur = None
    try:
        conn = conectar()
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS terminal_impressora (
                id INT AUTO_INCREMENT PRIMARY KEY,
                terminal_id VARCHAR(120) NOT NULL,
                impressora_id INT NOT NULL,
                caminho_local VARCHAR(512) NOT NULL DEFAULT '',
                id_cliente INT NOT NULL,
                data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uq_terminal_imp (terminal_id, impressora_id, id_cliente)
            )
            """
        )
        cur.execute("SHOW INDEX FROM terminal_impressora WHERE Key_name = 'uq_terminal_imp'")
        if not cur.fetchone():
            cur.execute(
                """
                DELETE t1 FROM terminal_impressora t1
                INNER JOIN terminal_impressora t2
                  ON t1.terminal_id = t2.terminal_id
                 AND t1.impressora_id = t2.impressora_id
                 AND t1.id_cliente = t2.id_cliente
                 AND (
                   t1.data_criacao < t2.data_criacao
                   OR (t1.data_criacao = t2.data_criacao AND t1.id < t2.id)
                 )
                """
            )
            cur.execute(
                """
                ALTER TABLE terminal_impressora
                ADD UNIQUE KEY uq_terminal_imp (terminal_id, impressora_id, id_cliente)
                """
            )
        conn.commit()
    except Exception as e:
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        print("[TERMINAL IMPRESSORA TABELA ERRO]", e, flush=True)
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def _ensure_whatsapp_config_table():
    """Configuração de WhatsApp (uazapi) por loja. 1 linha por id_cliente.

    Aditiva: CREATE TABLE IF NOT EXISTS, não toca em tabelas de venda/impressão.
    """
    conn = None
    cur = None
    try:
        conn = conectar()
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS whatsapp_config (
                id INT AUTO_INCREMENT PRIMARY KEY,
                id_cliente INT NOT NULL,
                ativo TINYINT NOT NULL DEFAULT 0,
                instancia_nome VARCHAR(120) DEFAULT NULL,
                instancia_token VARCHAR(255) DEFAULT NULL,
                url VARCHAR(255) DEFAULT NULL,
                notif_delivery_copia TINYINT NOT NULL DEFAULT 0,
                notif_despacho TINYINT NOT NULL DEFAULT 0,
                notif_balcao_pronto TINYINT NOT NULL DEFAULT 0,
                notif_mesa_conta TINYINT NOT NULL DEFAULT 0,
                texto_despacho_cliente TEXT,
                texto_balcao_pronto TEXT,
                data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uq_whatsapp_config_cliente (id_cliente)
            )
            """
        )
        conn.commit()
    except Exception as e:
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        print("[WHATSAPP CONFIG TABELA ERRO]", e, flush=True)
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def _ensure_whatsapp_log_table():
    """Auditoria de envios de WhatsApp por loja."""
    conn = None
    cur = None
    try:
        conn = conectar()
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS whatsapp_log (
                id INT AUTO_INCREMENT PRIMARY KEY,
                id_cliente INT DEFAULT NULL,
                telefone VARCHAR(40) DEFAULT NULL,
                evento VARCHAR(60) DEFAULT NULL,
                status VARCHAR(20) DEFAULT NULL,
                erro VARCHAR(500) DEFAULT NULL,
                data TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()
    except Exception as e:
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        print("[WHATSAPP LOG TABELA ERRO]", e, flush=True)
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def _impressora_purpose_from_origem(origem, dados=None):
    """Mapeia origem do pedido para flag na tabela impressoras."""
    o = (origem or "").strip().lower()
    if o == "mesa" or (dados and dados.get("conta_mesa")):
        return "conta_mesa"
    return "comanda_delivery"


@app.route("/api/casa/pedido-aguarde", methods=["GET"])
@login_required
def api_casa_pedido_aguarde():
    conn = None
    cur = None
    try:
        id_cliente = session.get("id_cliente")
        if not id_cliente:
            return jsonify({"sucesso": False, "erro": "Sessão inválida."}), 401
        telefone = request.args.get("telefone")
        tel_digits = "".join(ch for ch in str(telefone or "") if ch.isdigit())
        if not tel_digits:
            return jsonify({"sucesso": True, "encontrado": False})
        conn = conectar()
        cur = conn.cursor(dictionary=True)
        nropedido = _buscar_nropedido_aguarde_por_telefone(cur, id_cliente, tel_digits)
        if not nropedido:
            return jsonify({"sucesso": True, "encontrado": False})
        return jsonify({"sucesso": True, "encontrado": True, "nropedido": int(nropedido)})
    except Exception as e:
        print("[CASA PEDIDO AGUARDE ERRO]", e, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route("/api/casa/pedidos-aguarde", methods=["GET"])
@login_required
def api_casa_pedidos_aguarde():
    """Lista pedidos distintos ainda em AGUARDE (ex.: após novo número sem concluir o anterior)."""
    conn = None
    cur = None
    try:
        id_cliente = session.get("id_cliente")
        if not id_cliente:
            return jsonify({"sucesso": False, "erro": "Sessão inválida."}), 401
        origem_sql = "AND d.origem = 'BALCAO'" if is_retail() else "AND d.origem IN ('DELIVERY','BALCAO')"
        conn = conectar()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            f"""
            SELECT d.nropedido AS nropedido,
                   MAX(NULLIF(TRIM(d.telefone), '')) AS telefone,
                   MAX(NULLIF(TRIM(d.nome), '')) AS nome,
                   MAX(NULLIF(TRIM(d.cliente), '')) AS cliente,
                   COUNT(*) AS linhas
            FROM pedido_diarios d
            WHERE d.id_cliente = %s
              {origem_sql}
              AND UPPER(COALESCE(d.status_pedido, '')) = 'AGUARDE'
              AND UPPER(COALESCE(d.status_pedido, '')) <> 'ITEM_REMOVIDO'
              AND NOT ({_sql_comanda_cancelada('d')})
            GROUP BY d.nropedido
            ORDER BY d.nropedido DESC
            """,
            (id_cliente,),
        )
        rows = cur.fetchall() or []
        pedidos = []
        for row in rows:
            np = int((row or {}).get("nropedido") or 0)
            if not np:
                continue
            tel = (row or {}).get("telefone") or ""
            nome = (row or {}).get("nome") or (row or {}).get("cliente") or ""
            pedidos.append(
                {
                    "nropedido": np,
                    "telefone": tel,
                    "nome": str(nome).strip(),
                    "linhas": int((row or {}).get("linhas") or 0),
                }
            )
        return jsonify({"sucesso": True, "pedidos": pedidos, "total": len(pedidos)})
    except Exception as e:
        print("[CASA PEDIDOS AGUARDE ERRO]", e, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route("/api/casa/buscar-cep", methods=["GET"])
@login_required
@restaurant_only
def api_casa_buscar_cep():
    """Consulta ViaCEP e retorna campos de endereço para preenchimento automático no /casa."""
    cep_raw = request.args.get("cep", "").strip()
    cep_digits = "".join(ch for ch in cep_raw if ch.isdigit())
    if len(cep_digits) != 8:
        return jsonify({"sucesso": False, "erro": "CEP deve ter 8 dígitos."}), 400
    try:
        r = requests.get(
            f"https://viacep.com.br/ws/{cep_digits}/json/",
            timeout=6,
            headers={"User-Agent": "novaloja-cep/1.0"},
        )
        if r.status_code != 200:
            return jsonify({"sucesso": False, "erro": "CEP não encontrado."}), 404
        data = r.json()
        if data.get("erro"):
            return jsonify({"sucesso": False, "erro": "CEP não encontrado."}), 404
        return jsonify({
            "sucesso": True,
            "cep": f"{cep_digits[:5]}-{cep_digits[5:]}",
            "logradouro": data.get("logradouro") or "",
            "bairro": data.get("bairro") or "",
            "cidade": data.get("localidade") or "",
            "estado": data.get("uf") or "",
        })
    except Exception as e:
        print("[BUSCAR CEP ERRO]", e, flush=True)
        return jsonify({"sucesso": False, "erro": "Falha ao consultar CEP."}), 500


@app.route("/api/casa/item", methods=["POST"])
@login_required
def api_casa_add_item():
    conn = None
    cur = None
    try:
        data = request.get_json(silent=True) or {}
        data = _casa_forcar_balcao_se_varejo(data)
        nropedido = data.get("nropedido")
        item = data.get("item") or {}
        nome = (item.get("nome") or "").strip()
        if not nome:
            return jsonify({"sucesso": False, "erro": "Nome do item é obrigatório"}), 400

        id_cliente = session.get("id_cliente")
        if not id_cliente:
            return jsonify({"sucesso": False, "erro": "Sessão inválida: id_cliente não encontrado. Faça login novamente."}), 401
        conn = conectar()
        try:
            conn.start_transaction()
        except Exception:
            pass
        cur = conn.cursor(dictionary=True)
        modo_payload = str(data.get("modo") or "").strip().upper()
        telefone = (data.get("telefone") or "").strip()
        telefone_upper = telefone.upper()
        if modo_payload in ("DELIVERY", "BALCAO", "MESA"):
            origem = modo_payload
        elif telefone_upper.startswith("BALCAO"):
            origem = "BALCAO"
        elif telefone_upper.startswith("MESA"):
            origem = "MESA"
        else:
            origem = "DELIVERY"
        nropedido_int = 0
        try:
            nropedido_int = int(nropedido) if nropedido is not None and str(nropedido).strip() != "" else 0
        except Exception:
            nropedido_int = 0
        if origem in ("DELIVERY", "BALCAO") and nropedido_int > 0:
            cur.execute(
                """
                SELECT 1
                FROM pedido_diarios
                WHERE nropedido = %s AND id_cliente = %s AND origem IN ('DELIVERY','BALCAO')
                LIMIT 1
                """,
                (int(nropedido_int), id_cliente),
            )
            if not cur.fetchone():
                nropedido_int = 0
        if origem == "MESA" and not nropedido_int:
            return jsonify({"sucesso": False, "erro": "nropedido é obrigatório"}), 400
        if origem == "BALCAO":
            if not nropedido_int:
                cur.execute("SELECT contador FROM contadorpedido WHERE id_cliente = %s FOR UPDATE", (id_cliente,))
                resultado_cnt = cur.fetchone()
                if resultado_cnt:
                    novo_numero = int(resultado_cnt["contador"]) + 1
                    cur.execute("UPDATE contadorpedido SET contador = %s WHERE id_cliente = %s", (novo_numero, id_cliente))
                    nropedido_int = novo_numero
                else:
                    cur.execute("INSERT INTO contadorpedido (contador, id_cliente) VALUES (1, %s)", (id_cliente,))
                    nropedido_int = 1
            telefone = _normalizar_telefone_balcao(telefone, nropedido_int, id_cliente)
            if _telefone_whatsapp_valido(telefone):
                _propagar_telefone_balcao_pedido(
                    cur,
                    id_cliente,
                    nropedido_int,
                    telefone,
                    nome=(data.get("nome") or data.get("cliente") or "").strip(),
                    cliente=(data.get("cliente") or data.get("nome") or "").strip(),
                )
        if origem == "DELIVERY":
            telefone_digits = "".join(ch for ch in str(telefone or "") if ch.isdigit())
            if not telefone_digits:
                return jsonify({"sucesso": False, "erro": "Telefone inválido para Delivery."}), 400
            pedido_aguarde = _buscar_nropedido_aguarde_por_telefone(cur, id_cliente, telefone_digits)
            if not pedido_aguarde:
                pedido_aguarde = _buscar_nropedido_aguarde_por_telefone(cur, id_cliente, telefone)
            if pedido_aguarde:
                nropedido_int = int(pedido_aguarde)
            elif not nropedido_int:
                cur.execute("SELECT contador FROM contadorpedido WHERE id_cliente = %s FOR UPDATE", (id_cliente,))
                resultado_cnt = cur.fetchone()
                if resultado_cnt:
                    novo_numero = int(resultado_cnt["contador"]) + 1
                    cur.execute("UPDATE contadorpedido SET contador = %s WHERE id_cliente = %s", (novo_numero, id_cliente))
                    nropedido_int = novo_numero
                else:
                    cur.execute("INSERT INTO contadorpedido (contador, id_cliente) VALUES (1, %s)", (id_cliente,))
                    nropedido_int = 1
            status_clause = (
                " AND origem = 'DELIVERY' "
                " AND UPPER(COALESCE(status_pedido, '')) = 'AGUARDE' "
                " AND UPPER(COALESCE(status_pedido, '')) <> 'ITEM_REMOVIDO' "
            )
            cur.execute(
                f"""
                SELECT DISTINCT telefone
                FROM pedido_diarios
                WHERE nropedido = %s AND id_cliente = %s
                {status_clause}
                """,
                (int(nropedido_int), id_cliente),
            )
            telefones_pedido = cur.fetchall() or []
            conflito_telefone = False
            for row in telefones_pedido:
                tel_existente = (row or {}).get("telefone")
                if not tel_existente:
                    continue
                if not _telefones_compativeis(tel_existente, telefone_digits):
                    conflito_telefone = True
                    break
            if conflito_telefone:
                pedido_aguarde_tel = _buscar_nropedido_aguarde_por_telefone(cur, id_cliente, telefone_digits)
                if pedido_aguarde_tel:
                    nropedido_int = int(pedido_aguarde_tel)
                else:
                    return jsonify({
                        "sucesso": False,
                        "erro": "Pedido atual pertence a outro telefone. Localize novamente.",
                        "codigo": "CONFLITO_TELEFONE_PEDIDO"
                    }), 409
        nropedido = int(nropedido_int) if nropedido_int else nropedido_int

        if origem in ("DELIVERY", "BALCAO") and int(nropedido or 0) > 0:
            blocked = _assert_casa_editavel(cur, id_cliente, int(nropedido), origem)
            if blocked:
                conn.rollback()
                return blocked

        fracionado = bool(data.get("fracionado"))
        partes = data.get("partes") if isinstance(data.get("partes"), list) else []
        formadecobrar = str(data.get("formadecobrar") or "").strip().lower()

        cod_classe = None
        classe_nome = str(item.get("classe") or "").strip()
        if classe_nome:
            cur.execute(
                """
                SELECT chave
                FROM classificacao
                WHERE nomeclassificacao = %s AND id_cliente = %s
                LIMIT 1
                """,
                (classe_nome, id_cliente),
            )
            row_cls = cur.fetchone() or {}
            cod_classe = row_cls.get("chave")
            if cod_classe is None and classe_nome.isdigit():
                cod_classe = int(classe_nome)

        cod_usuario = None
        id_usuario_sessao = session.get("id_usuario")
        if id_usuario_sessao is not None:
            try:
                cod_usuario = int(id_usuario_sessao)
            except Exception:
                cod_usuario = None
        if cod_usuario is None:
            usuario_logado = str(session.get("usuario_logado") or "").strip()
            if usuario_logado:
                cur.execute(
                    """
                    SELECT chave
                    FROM usuarios
                    WHERE usuario = %s AND id_cliente = %s
                    LIMIT 1
                    """,
                    (usuario_logado, id_cliente),
                )
                row_usr = cur.fetchone() or {}
                cod_usuario = row_usr.get("chave")

        em_recuperacao = bool(data.get("em_recuperacao"))
        # Regra operacional: item novo incluído (inclusive após F7) deve entrar como AGUARDE
        # para nova distribuição na impressão setorizada.
        status_pedido_insert = "AGUARDE"

        if fracionado and len(partes) >= 2:
            qtd_escolhida = max(1, len(partes))
            cur.execute(
                """
                SELECT COALESCE(MAX(lancamento), 0) AS max_lancamento
                FROM pedido_diarios
                WHERE id_cliente = %s AND nropedido = %s AND origem = %s
                """,
                (id_cliente, int(nropedido), origem),
            )
            row_max = cur.fetchone() or {}
            max_lancamento = int((row_max.get("max_lancamento") or 0))
            lancamento = max_lancamento + 1
            if lancamento > 2147483647:
                lancamento = 1
            precos = [float((p or {}).get("preco") or 0) for p in partes]
            maior_idx = max(range(len(precos)), key=lambda i: precos[i]) if precos else 0
            preco_base = max(precos) if precos else float(item.get("preco") or 0)
            last_pd_id = None
            for i, parte in enumerate(partes):
                nome_parte = str((parte or {}).get("nome") or nome).strip() or nome
                if qtd_escolhida >= 2:
                    nome_parte_db = f"1/{qtd_escolhida} {nome_parte}"
                else:
                    nome_parte_db = nome_parte
                cod_parte = str((parte or {}).get("codigoproduto") or item.get("codigoproduto") or "")
                obs_parte = str((parte or {}).get("obs_item") or "").strip()
                dados_parte = (parte or {}).get("dados_item")
                if dados_parte is None:
                    dados_parte = item.get("dados_item")
                preco_parte = 0.0
                if i == maior_idx:
                    preco_parte = float(preco_base)
                _insert_pedido_diarios_from_casa(
                    cur,
                    origem=origem,
                    nropedido=nropedido,
                    id_cliente=id_cliente,
                    telefone=telefone,
                    cep=(data.get("cep") or "").strip(),
                    nome=(data.get("nome") or "").strip(),
                    endereco=(data.get("endereco") or "").strip(),
                    nrocasa=(data.get("nrocasa") or "").strip(),
                    complemento=(data.get("complemento") or "").strip(),
                    codigoproduto=cod_parte,
                    produto=nome_parte_db,
                    preco=preco_parte,
                    quantidade=float(item.get("qtd") or 1),
                    classe=str(item.get("classe") or ""),
                    obs_item=obs_parte,
                    dados_item=dados_parte,
                    obs_geral=str(data.get("obs_geral") or ""),
                    cliente=(data.get("cliente") or data.get("nome") or "").strip(),
                    cod_classe=cod_classe,
                    cod_usuario=cod_usuario,
                    status_pedido=(status_pedido_insert or "AGUARDE"),
                    status_comanda=("MODIFICADA" if status_pedido_insert == "ABERTO" else "NORMAL"),
                    lancamento=lancamento,
                    nrolancamento=None,
                    formapagamento=str(data.get("formapagamento") or ""),
                    entregador=str(data.get("entregador") or ""),
                )
                last_pd_id = cur.lastrowid
            conn.commit()
            return jsonify({"sucesso": True, "id": last_pd_id, "nropedido": int(nropedido), "lancamento": lancamento, "fracionado": True, "formadecobrar": formadecobrar})

        cur.execute(
            """
            SELECT COALESCE(MAX(lancamento), 0) AS max_lancamento
            FROM pedido_diarios
            WHERE id_cliente = %s AND nropedido = %s AND origem = %s
            """,
            (id_cliente, int(nropedido), origem),
        )
        row_max = cur.fetchone() or {}
        lancamento_simples = int((row_max.get("max_lancamento") or 0)) + 1
        if lancamento_simples > 2147483647:
            lancamento_simples = 1
        _insert_pedido_diarios_from_casa(
            cur,
            origem=origem,
            nropedido=nropedido,
            id_cliente=id_cliente,
            telefone=telefone,
            cep=(data.get("cep") or "").strip(),
            nome=(data.get("nome") or "").strip(),
            endereco=(data.get("endereco") or "").strip(),
            nrocasa=(data.get("nrocasa") or "").strip(),
            complemento=(data.get("complemento") or "").strip(),
            codigoproduto=str(item.get("codigoproduto") or ""),
            produto=nome,
            preco=float(item.get("preco") or 0),
            quantidade=float(item.get("qtd") or 1),
            classe=str(item.get("classe") or ""),
            obs_item=str(item.get("obs_item") or ""),
            dados_item=item.get("dados_item"),
            obs_geral=str(data.get("obs_geral") or ""),
            cliente=(data.get("cliente") or data.get("nome") or "").strip(),
            cod_classe=cod_classe,
            cod_usuario=cod_usuario,
            status_pedido=(status_pedido_insert or "AGUARDE"),
            status_comanda=("MODIFICADA" if status_pedido_insert == "ABERTO" else "NORMAL"),
            lancamento=lancamento_simples,
            nrolancamento=None,
            formapagamento=str(data.get("formapagamento") or ""),
            entregador=str(data.get("entregador") or ""),
        )
        novo_id = cur.lastrowid
        if em_recuperacao:
            # Ao modificar comanda recuperada, toda a comanda passa a MODIFICADA.
            cur.execute(
                """
                UPDATE pedido_diarios
                SET status_comanda = 'MODIFICADA'
                WHERE nropedido = %s AND id_cliente = %s AND origem IN ('DELIVERY','BALCAO')
                """,
                (int(nropedido), id_cliente),
            )
        conn.commit()
        return jsonify({"sucesso": True, "id": novo_id, "nropedido": int(nropedido)})
    except Exception as e:
        if conn:
            conn.rollback()
        print("[CASA ADD ITEM ERRO]", e, flush=True)
        try:
            print(f"[CASA ADD ITEM ERRO] payload={data}", flush=True)
            print(f"[CASA ADD ITEM ERRO] id_cliente_sessao={session.get('id_cliente')}", flush=True)
        except Exception:
            pass
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route("/api/casa/<int:nropedido>", methods=["GET"])
@login_required
def api_casa_listar_itens(nropedido):
    conn = None
    cur = None
    try:
        _ensure_pedido_diarios_preparo_columns()
        id_cliente = session.get("id_cliente")
        if id_cliente is None:
            return jsonify({"sucesso": False, "erro": "Sessão sem loja (id_cliente). Faça login novamente."}), 401
        modo = str(request.args.get("modo") or ("balcao" if is_retail() else "delivery")).strip().lower()
        if is_retail() and modo in ("delivery", "mesa"):
            modo = "balcao"
        status_req = str(request.args.get("status") or "").strip().upper()
        telefone_req = "".join(ch for ch in str(request.args.get("telefone") or "") if ch.isdigit())
        conn = conectar()
        cur = conn.cursor(dictionary=True, buffered=True)
        prod_imp_col = None
        prod_cod_col = None
        try:
            cur.execute("SHOW COLUMNS FROM produtos LIKE 'impressora'")
            if cur.fetchone() is not None:
                prod_imp_col = "impressora"
            else:
                cur.execute("SHOW COLUMNS FROM produtos LIKE 'impressoras'")
                if cur.fetchone() is not None:
                    prod_imp_col = "impressoras"
            for cand in ("codigoproduto", "codigo", "codbarra", "cod_barras", "ean"):
                cur.execute("SHOW COLUMNS FROM produtos LIKE %s", (cand,))
                if cur.fetchone() is not None:
                    prod_cod_col = cand
                    break
        except Exception:
            prod_imp_col = None
            prod_cod_col = None
        modo_is_delivery = modo == "delivery"
        modo_is_recuperacao = modo == "recuperacao"
        modo_is_balcao_ou_mesa = modo in ("balcao", "mesa")
        origem_req = str(request.args.get("origem") or "").strip().upper()

        # Delivery normal: sem telefone não exibe itens.
        if modo_is_delivery and not telefone_req:
            return jsonify({"sucesso": True, "registros": [], "obs_geral": ""})

        origem_db = "DELIVERY"
        if modo_is_balcao_ou_mesa:
            origem_db = "BALCAO" if modo == "balcao" else "MESA"

        status_final = status_req
        if modo_is_recuperacao:
            if status_final != "ABERTO":
                status_final = "ABERTO"
        elif modo_is_delivery:
            status_final = "AGUARDE"
        elif modo_is_balcao_ou_mesa:
            # Fluxo operacional normal de balcao/mesa não deve trazer pedidos já em produção.
            status_final = "AGUARDE"

        status_clause = ""
        origem_clause = " AND d.origem = %s "
        params = [nropedido, id_cliente, origem_db]
        status_removido_clause = " AND UPPER(COALESCE(d.status_pedido, '')) <> 'ITEM_REMOVIDO' "
        if modo_is_recuperacao:
            origem_clause = " AND d.origem IN ('DELIVERY','BALCAO') "
            params = [nropedido, id_cliente]
            if origem_req in ("DELIVERY", "BALCAO"):
                origem_clause = " AND d.origem = %s "
                params = [nropedido, id_cliente, origem_req]
        if status_final:
            if modo_is_recuperacao:
                status_clause = " AND UPPER(COALESCE(d.status_pedido, '')) IN ('ABERTO','ABERTA','AGUARDE') "
            else:
                status_clause = " AND UPPER(COALESCE(d.status_pedido, '')) = %s "
                params.append(status_final)

        imp_sel = f"COALESCE(p.{prod_imp_col},'') AS impressoras_produto" if prod_imp_col else "'' AS impressoras_produto"
        join_on = ""
        if prod_imp_col:
            if prod_cod_col:
                join_on = (
                    f"p.id_cliente = d.id_cliente AND ("
                    f"p.chave = CAST(d.codigoproduto AS UNSIGNED) OR "
                    f"TRIM(COALESCE(p.{prod_cod_col},'')) = TRIM(COALESCE(d.codigoproduto,''))"
                    f")"
                )
            else:
                join_on = "p.id_cliente = d.id_cliente AND p.chave = CAST(d.codigoproduto AS UNSIGNED)"
        join_prod = (
            f"LEFT JOIN produtos p ON {join_on}" if (prod_imp_col and join_on) else ""
        )
        regs = []
        query_main = f"""
            SELECT d.chave AS chave, d.nropedido, d.produto, d.preco, d.quantidade, d.codigoproduto, d.classe, d.obs_item, d.dados_item, d.obs_geral,
                   '' AS descricao_produto, d.telefone, d.origem,
                   d.nome, d.endereco, d.nrocasa, d.complemento, d.cep,
                   COALESCE(d.lancamento, 0) AS lancamento,
                   COALESCE(d.formapagamento, '') AS formapagamento,
                   d.valor_pago_troco,
                   COALESCE(d.imp_preparo,'N') AS imp_preparo,
                   {imp_sel}
            FROM pedido_diarios d
            {join_prod}
            WHERE d.nropedido = %s AND d.id_cliente = %s
            {origem_clause}
            {status_clause}
            {status_removido_clause}
            ORDER BY d.chave DESC
        """
        try:
            cur.execute(query_main, tuple(params))
            regs = cur.fetchall() or []
        except Exception as e:
            print("[CASA] Falha ao executar query com join de produtos:", e, flush=True)
            traceback.print_exc()
            query_fallback = f"""
                SELECT d.chave AS chave, d.nropedido, d.produto, d.preco, d.quantidade, d.codigoproduto, d.classe, d.obs_item, d.dados_item, d.obs_geral,
                       '' AS descricao_produto, d.telefone, d.origem,
                       d.nome, d.endereco, d.nrocasa, d.complemento, d.cep,
                       COALESCE(d.lancamento, 0) AS lancamento,
                       COALESCE(d.formapagamento, '') AS formapagamento,
                       d.valor_pago_troco,
                       COALESCE(d.imp_preparo,'N') AS imp_preparo,
                       '' AS impressoras_produto
                FROM pedido_diarios d
                WHERE d.nropedido = %s AND d.id_cliente = %s
                {origem_clause}
                {status_clause}
                {status_removido_clause}
                ORDER BY d.chave DESC
            """
            cur.execute(query_fallback, tuple(params))
            regs = cur.fetchall() or []
        if modo_is_delivery:
            filtrados = []
            for row in regs:
                db_tel = "".join(ch for ch in str(row.get("telefone") or "") if ch.isdigit())
                if not db_tel:
                    continue
                if db_tel == telefone_req or db_tel.endswith(telefone_req) or telefone_req.endswith(db_tel):
                    filtrados.append(row)
            regs = filtrados
        _enriquecer_descricao_produto_pedido_rows(cur, id_cliente, regs)
        _preencher_impressoras_produto(cur, id_cliente, regs, src_cod_field="codigoproduto", dest_field="impressoras_produto")
        regs = [convert_types(r) for r in regs]
        obs_geral = ""
        forma_head = ""
        valor_pago_troco_head = None
        if regs:
            obs_geral = (regs[0].get("obs_geral") or "").strip()
            forma_head = str(regs[0].get("formapagamento") or "").strip()
            vraw = regs[0].get("valor_pago_troco")
            if vraw is not None and str(vraw).strip() != "":
                try:
                    valor_pago_troco_head = float(vraw)
                except (TypeError, ValueError):
                    valor_pago_troco_head = None
        cliente_data = {}
        origem_encontrada = ""
        if regs:
            base = regs[0]
            origem_encontrada = str(base.get("origem") or "").strip().upper()
            cliente_data = {
                "telefone": (base.get("telefone") or ""),
                "nome": (base.get("nome") or ""),
                "endereco": (base.get("endereco") or ""),
                "nrocasa": (base.get("nrocasa") or ""),
                "complemento": (base.get("complemento") or ""),
                "referencia": "",
                "bairro": "",
                "cidade": "",
                "estado": "",
                "cep": (base.get("cep") or ""),
            }
        elif modo_is_recuperacao:
            if origem_req in ("DELIVERY", "BALCAO"):
                cur.execute(
                    """
                    SELECT d.telefone, d.nome, d.endereco, d.nrocasa, d.complemento, d.cep,
                           UPPER(COALESCE(d.origem, '')) AS origem,
                           UPPER(COALESCE(d.status_comanda, 'NORMAL')) AS st_comanda,
                           COALESCE(d.obs_geral, '') AS obs_geral
                    FROM pedido_diarios d
                    WHERE d.nropedido = %s AND d.id_cliente = %s
                      AND d.origem = %s
                    ORDER BY d.chave DESC
                    LIMIT 1
                    """,
                    (nropedido, id_cliente, origem_req),
                )
            else:
                cur.execute(
                    """
                    SELECT d.telefone, d.nome, d.endereco, d.nrocasa, d.complemento, d.cep,
                           UPPER(COALESCE(d.origem, '')) AS origem,
                           UPPER(COALESCE(d.status_comanda, 'NORMAL')) AS st_comanda,
                           COALESCE(d.obs_geral, '') AS obs_geral
                    FROM pedido_diarios d
                    WHERE d.nropedido = %s AND d.id_cliente = %s
                      AND d.origem IN ('DELIVERY','BALCAO')
                    ORDER BY d.chave DESC
                    LIMIT 1
                    """,
                    (nropedido, id_cliente),
                )
            base_any = cur.fetchone() or {}
            origem_encontrada = str(base_any.get("origem") or "").strip().upper()
            if base_any:
                obs_geral = str(base_any.get("obs_geral") or "").strip()
                cliente_data = {
                    "telefone": (base_any.get("telefone") or ""),
                    "nome": (base_any.get("nome") or ""),
                    "endereco": (base_any.get("endereco") or ""),
                    "nrocasa": (base_any.get("nrocasa") or ""),
                    "complemento": (base_any.get("complemento") or ""),
                    "referencia": "",
                    "bairro": "",
                    "cidade": "",
                    "estado": "",
                    "cep": (base_any.get("cep") or ""),
                }

        status_comanda = "NORMAL"
        if modo_is_recuperacao:
            if origem_req in ("DELIVERY", "BALCAO"):
                cur.execute(
                    """
                    SELECT UPPER(COALESCE(status_comanda, 'NORMAL')) AS st
                    FROM pedido_diarios
                    WHERE nropedido = %s AND id_cliente = %s AND origem = %s
                    ORDER BY chave DESC
                    LIMIT 1
                    """,
                    (nropedido, id_cliente, origem_req),
                )
            else:
                cur.execute(
                    """
                    SELECT UPPER(COALESCE(status_comanda, 'NORMAL')) AS st
                    FROM pedido_diarios
                    WHERE nropedido = %s AND id_cliente = %s AND origem IN ('DELIVERY','BALCAO')
                    ORDER BY chave DESC
                    LIMIT 1
                    """,
                    (nropedido, id_cliente),
                )
        else:
            cur.execute(
                """
                SELECT UPPER(COALESCE(status_comanda, 'NORMAL')) AS st
                FROM pedido_diarios
                WHERE nropedido = %s AND id_cliente = %s AND origem = %s
                ORDER BY chave DESC
                LIMIT 1
                """,
                (nropedido, id_cliente, origem_db),
            )
        row_sc = cur.fetchone() or {}
        status_comanda = str((row_sc or {}).get("st") or "NORMAL").strip().upper() or "NORMAL"

        pedido_bloqueado_casa = False
        comanda_cancelada = False
        motivo_bloqueio = ""
        try:
            info_blk = _casa_pedido_bloqueado_info(cur, id_cliente, int(nropedido), origem_encontrada or origem_db)
            pedido_bloqueado_casa = bool(info_blk.get("bloqueado"))
            comanda_cancelada = bool(info_blk.get("comanda_cancelada"))
            motivo_bloqueio = str(info_blk.get("motivo_bloqueio") or "")
        except Exception:
            pedido_bloqueado_casa = False
            comanda_cancelada = status_comanda == STATUS_COMANDA_CANCELADA
            if comanda_cancelada:
                pedido_bloqueado_casa = True
                motivo_bloqueio = "Comanda cancelada."

        return jsonify({
            "sucesso": True,
            "registros": regs,
            "obs_geral": obs_geral,
            "formapagamento": forma_head,
            "valor_pago_troco": valor_pago_troco_head,
            "cliente": cliente_data,
            "status_comanda": status_comanda,
            "origem": origem_encontrada or origem_db,
            "pedido_bloqueado_casa": pedido_bloqueado_casa,
            "comanda_cancelada": comanda_cancelada,
            "motivo_bloqueio": motivo_bloqueio,
        })
    except Exception as e:
        print("[CASA LISTA ERRO]", e, flush=True)
        traceback.print_exc()
        tb = traceback.format_exc()
        try:
            ctx = "\n".join(
                [
                    f"nropedido={nropedido!r}",
                    f"id_cliente_session={session.get('id_cliente')!r}",
                    f"request.args={dict(request.args)!r}",
                    f"{type(e).__name__}: {e!r}",
                    tb,
                ]
            )
            _append_loja_erro_log("[api_casa_listar_itens]", ctx)
        except Exception:
            pass
        return jsonify({"sucesso": False, "erro": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route("/api/casa/<int:nropedido>/item/<int:item_id>", methods=["PATCH"])
@login_required
def api_casa_alterar_item(nropedido, item_id):
    conn = None
    cur = None
    try:
        data = request.get_json(silent=True) or {}
        qtd_raw = data.get("qtd", None)
        obs_item = data.get("obs_item", None)
        dados_item = data.get("dados_item", None)
        if qtd_raw is None and obs_item is None and dados_item is None:
            return jsonify({"sucesso": False, "erro": "Nada para atualizar"}), 400
        id_cliente = session.get("id_cliente")
        conn = conectar()
        cur = conn.cursor()
        blocked = _assert_casa_editavel(cur, id_cliente, nropedido)
        if blocked:
            return blocked
        set_parts = []
        params = []
        if qtd_raw is not None:
            qtd = float(qtd_raw or 0)
            if qtd <= 0:
                return jsonify({"sucesso": False, "erro": "Quantidade deve ser maior que zero"}), 400
            set_parts.append("quantidade = %s")
            params.append(qtd)
        if obs_item is not None:
            set_parts.append("obs_item = %s")
            params.append(str(obs_item).strip())
        if dados_item is not None:
            set_parts.append("dados_item = %s")
            params.append(str(dados_item).strip())
        params.extend([item_id, nropedido, id_cliente])
        cur.execute(
            f"UPDATE pedido_diarios SET {', '.join(set_parts)} WHERE chave = %s AND nropedido = %s AND id_cliente = %s AND origem IN ('DELIVERY','BALCAO')",
            params
        )
        conn.commit()
        if cur.rowcount == 0:
            return jsonify({"sucesso": False, "erro": "Item não encontrado"}), 404
        return jsonify({"sucesso": True})
    except Exception as e:
        if conn:
            conn.rollback()
        print("[CASA PATCH ITEM ERRO]", e, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

@app.route("/api/casa/<int:nropedido>/obs-geral", methods=["PATCH"])
@login_required
def api_casa_obs_geral(nropedido):
    conn = None
    cur = None
    try:
        data = request.get_json(silent=True) or {}
        obs_geral = (data.get("obs_geral") or "").strip()
        id_cliente = session.get("id_cliente")
        conn = conectar()
        cur = conn.cursor()
        blocked = _assert_casa_editavel(cur, id_cliente, nropedido)
        if blocked:
            return blocked
        cur.execute(
            "UPDATE pedido_diarios SET obs_geral = %s WHERE nropedido = %s AND id_cliente = %s AND origem IN ('DELIVERY','BALCAO')",
            (obs_geral, nropedido, id_cliente),
        )
        conn.commit()
        return jsonify({"sucesso": True})
    except Exception as e:
        if conn:
            conn.rollback()
        print("[CASA OBS GERAL ERRO]", e, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route("/api/casa/<int:nropedido>/item/<int:item_id>", methods=["DELETE"])
@login_required
def api_casa_remover_item(nropedido, item_id):
    conn = None
    cur = None
    try:
        id_cliente = session.get("id_cliente")
        conn = conectar()
        cur = conn.cursor()
        blocked = _assert_casa_editavel(cur, id_cliente, nropedido)
        if blocked:
            return blocked
        cur.execute(
            """
            SELECT COALESCE(lancamento, 0) AS lancamento,
                   UPPER(COALESCE(status_pedido,'')) AS status_pedido,
                   UPPER(COALESCE(origem,'')) AS origem
            FROM pedido_diarios
            WHERE chave = %s AND nropedido = %s AND id_cliente = %s AND origem IN ('DELIVERY','BALCAO')
            LIMIT 1
            """,
            (item_id, nropedido, id_cliente),
        )
        row = cur.fetchone()
        if not row:
            return jsonify({"sucesso": False, "erro": "Item não encontrado"}), 404
        lancamento = int(row[0] or 0)
        status_pedido_alvo = str(row[1] or "").upper()
        origem_alvo = str(row[2] or "").upper() or "DELIVERY"

        if lancamento > 0:
            cur.execute(
                """
                UPDATE pedido_diarios
                SET status_pedido = 'ITEM_REMOVIDO'
                WHERE nropedido = %s AND id_cliente = %s AND origem = %s AND lancamento = %s
                """,
                (nropedido, id_cliente, origem_alvo, lancamento),
            )
        else:
            cur.execute(
                """
                UPDATE pedido_diarios
                SET status_pedido = 'ITEM_REMOVIDO'
                WHERE chave = %s AND nropedido = %s AND id_cliente = %s AND origem = %s
                """,
                (item_id, nropedido, id_cliente, origem_alvo)
            )
        removidos_pd = cur.rowcount
        conn.commit()
        return jsonify({"sucesso": True, "removidos": removidos_pd})
    except Exception as e:
        if conn:
            conn.rollback()
        print("[CASA DELETE ITEM ERRO]", e, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route("/api/casa/<int:nropedido>", methods=["DELETE"])
@login_required
def api_casa_limpar_pedido(nropedido):
    conn = None
    cur = None
    try:
        id_cliente = session.get("id_cliente")
        conn = conectar()
        cur = conn.cursor()
        blocked = _assert_casa_editavel(cur, id_cliente, nropedido)
        if blocked:
            return blocked
        cur.execute(
            """
            UPDATE pedido_diarios
            SET status_pedido = 'ITEM_REMOVIDO'
            WHERE nropedido = %s AND id_cliente = %s AND origem IN ('DELIVERY','BALCAO')
            """,
            (nropedido, id_cliente),
        )
        removidos_pd = cur.rowcount
        conn.commit()
        return jsonify({"sucesso": True, "removidos": removidos_pd})
    except Exception as e:
        if conn:
            conn.rollback()
        print("[CASA LIMPAR PEDIDO ERRO]", e, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

@app.route("/api/casa/<int:nropedido>/formapagamento", methods=["PATCH"])
@login_required
def api_casa_formapagamento(nropedido):
    conn = None
    cur = None
    try:
        data = request.get_json(silent=True) or {}
        forma = (data.get("forma") or "").strip()
        if not forma:
            return jsonify({"sucesso": False, "erro": "Forma de pagamento é obrigatória"}), 400
        id_cliente = session.get("id_cliente")
        raw_vp = data.get("valor_pago_troco", None)
        valor_req = None
        if raw_vp is not None and str(raw_vp).strip() != "":
            try:
                valor_req = float(str(raw_vp).strip().replace(",", "."))
            except (TypeError, ValueError):
                return jsonify({"sucesso": False, "erro": "Valor pago inválido."}), 400
        conn = conectar()
        cur = conn.cursor()
        _ensure_pedido_diarios_valor_pago_troco()
        blocked = _assert_casa_editavel(cur, id_cliente, nropedido)
        if blocked:
            return blocked
        cur.execute(
            """
            SELECT COALESCE(SUM(COALESCE(preco, 0) * COALESCE(quantidade, 0)), 0) AS tot
            FROM pedido_diarios
            WHERE nropedido = %s AND id_cliente = %s AND origem IN ('DELIVERY','BALCAO')
              AND UPPER(TRIM(COALESCE(status_pedido, ''))) <> 'ITEM_REMOVIDO'
            """,
            (nropedido, id_cliente),
        )
        row_tot = cur.fetchone() or ()
        total_pedido = float((row_tot[0] if row_tot else 0) or 0)
        exige = _forma_pagamento_exige_troco(cur, id_cliente, forma)
        valor_para_delivery = None
        if exige:
            if valor_req is None:
                return jsonify(
                    {"sucesso": False, "erro": "Informe com quanto o cliente vai pagar (valor maior ou igual ao total)."}
                ), 400
            if valor_req + 1e-6 < total_pedido:
                return jsonify(
                    {"sucesso": False, "erro": "Valor pago deve ser maior ou igual ao total do pedido."}
                ), 400
            valor_para_delivery = valor_req
        wc_ativo = " AND UPPER(TRIM(COALESCE(status_pedido, ''))) <> 'ITEM_REMOVIDO' "
        cur.execute(
            f"""
            SELECT COUNT(*) FROM pedido_diarios
            WHERE nropedido = %s AND id_cliente = %s AND origem IN ('DELIVERY','BALCAO')
            {wc_ativo}
            """,
            (nropedido, id_cliente),
        )
        row_n = cur.fetchone() or (0,)
        n_ativos = int((row_n[0] if row_n else 0) or 0)
        if n_ativos <= 0:
            cur.execute(
                """
                SELECT COUNT(*) FROM pedido_diarios
                WHERE nropedido = %s AND id_cliente = %s AND origem IN ('DELIVERY','BALCAO')
                """,
                (nropedido, id_cliente),
            )
            row_g = cur.fetchone() or (0,)
            n_qualquer = int((row_g[0] if row_g else 0) or 0)
            if n_qualquer > 0:
                msg = "Não há itens ativos neste pedido (itens removidos). Adicione itens ou abra o pedido correto."
            else:
                cur.execute(
                    "SELECT COUNT(*) FROM pedido_diarios WHERE nropedido = %s AND id_cliente = %s",
                    (nropedido, id_cliente),
                )
                row_a = cur.fetchone() or (0,)
                n_outra_origem = int((row_a[0] if row_a else 0) or 0)
                if n_outra_origem > 0:
                    msg = (
                        "Pedido encontrado com outra origem (ex.: mesa). "
                        "Na /casa só é possível definir pagamento em pedidos delivery/balcão."
                    )
                else:
                    msg = (
                        f"Pedido #{nropedido} não encontrado para esta loja "
                        "ou ainda sem linhas em pedido_diarios. Recarregue a tela e confira o número."
                    )
            return jsonify({"sucesso": False, "erro": msg}), 404
        cur.execute(
            f"""
            UPDATE pedido_diarios
            SET formapagamento = %s,
                valor_pago_troco = CASE WHEN origem = 'DELIVERY' THEN %s ELSE NULL END
            WHERE nropedido = %s AND id_cliente = %s AND origem IN ('DELIVERY','BALCAO')
            {wc_ativo}
            """,
            (forma, valor_para_delivery, nropedido, id_cliente),
        )
        conn.commit()
        return jsonify({"sucesso": True, "mensagem": "Forma de pagamento atualizada"})
    except Exception as e:
        if conn:
            conn.rollback()
        print("[CASA FORMAPAGAMENTO ERRO]", e, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

@app.route("/api/casa/<int:nropedido>/ajuste-item", methods=["POST"])
@login_required
def api_casa_ajuste_item(nropedido):
    conn = None
    cur = None
    try:
        data = request.get_json(silent=True) or {}
        valor = float(data.get("valor") or 0)
        if valor == 0:
            return jsonify({"sucesso": False, "erro": "Valor do ajuste deve ser diferente de zero."}), 400
        id_cliente = session.get("id_cliente")
        conn = conectar()
        cur = conn.cursor(dictionary=True)
        blocked = _assert_casa_editavel(cur, id_cliente, nropedido)
        if blocked:
            return blocked
        cur.execute(
            """
            SELECT telefone, cep, nome, endereco, nrocasa, complemento, cliente, formapagamento,
                   cod_classe, entregador, origem,
                   UPPER(COALESCE(status_pedido,'')) AS status_pedido
            FROM pedido_diarios
            WHERE nropedido = %s AND id_cliente = %s AND origem IN ('DELIVERY','BALCAO')
              AND UPPER(COALESCE(status_pedido, '')) <> 'ITEM_REMOVIDO'
            ORDER BY chave DESC
            LIMIT 1
            """,
            (nropedido, id_cliente),
        )
        base = cur.fetchone()
        if not base:
            return jsonify({"sucesso": False, "erro": "Pedido sem itens para aplicar ajuste."}), 404

        cod_classe = None
        cod_classe = base.get("cod_classe")
        if cod_classe is None:
            return jsonify({"sucesso": False, "erro": "Não foi possível resolver cod_classe para ajuste técnico."}), 400

        cod_usuario = None
        id_usuario_sessao = session.get("id_usuario")
        if id_usuario_sessao is not None:
            try:
                cod_usuario = int(id_usuario_sessao)
            except Exception:
                cod_usuario = None
        if cod_usuario is None:
            usuario_logado = str(session.get("usuario_logado") or "").strip()
            if usuario_logado:
                cur.execute(
                    """
                    SELECT chave
                    FROM usuarios
                    WHERE usuario = %s AND id_cliente = %s
                    LIMIT 1
                    """,
                    (usuario_logado, id_cliente),
                )
                row_usr = cur.fetchone() or {}
                cod_usuario = row_usr.get("chave")
        if cod_usuario is None:
            return jsonify({"sucesso": False, "erro": "Não foi possível resolver cod_usuario do usuário logado."}), 400

        status_insert = "ABERTO" if str(base.get("status_pedido") or "").upper() == "ABERTO" else "AGUARDE"
        produto = "TAXA EXTRA" if valor > 0 else "DESCONTO"
        codigoproduto = "AJUSTE_TECNICO"

        # Mantém apenas um ajuste técnico por pedido para evitar duplicidade operacional.
        origem_pd = str(base.get("origem") or "").strip().upper() or ("BALCAO" if str(base.get("telefone") or "").upper().startswith("BALCAO") else "DELIVERY")
        cur.execute(
            """
            DELETE FROM pedido_diarios
            WHERE nropedido = %s AND id_cliente = %s AND codigoproduto = %s AND origem = %s
            """,
            (int(nropedido), id_cliente, codigoproduto, origem_pd),
        )

        cur.execute(
            """
            SELECT COALESCE(MAX(lancamento), 0) AS max_lancamento
            FROM pedido_diarios
            WHERE id_cliente = %s AND nropedido = %s AND origem = %s
            """,
            (id_cliente, int(nropedido), origem_pd),
        )
        row_max = cur.fetchone() or {}
        lancamento = int((row_max.get("max_lancamento") or 0)) + 1
        if lancamento > 2147483647:
            lancamento = 1
        _insert_pedido_diarios_from_casa(
            cur,
            origem=origem_pd,
            nropedido=nropedido,
            id_cliente=id_cliente,
            telefone=str(base.get("telefone") or ""),
            cep=str(base.get("cep") or ""),
            nome=str(base.get("nome") or ""),
            endereco=str(base.get("endereco") or ""),
            nrocasa=str(base.get("nrocasa") or ""),
            complemento=str(base.get("complemento") or ""),
            codigoproduto=codigoproduto,
            produto=produto,
            preco=float(valor),
            quantidade=1.0,
            classe="AJUSTE_TECNICO",
            obs_item=str(data.get("descricao") or "").strip(),
            dados_item="",
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
        conn.commit()
        return jsonify({"sucesso": True, "produto": produto, "valor": valor})
    except Exception as e:
        if conn:
            conn.rollback()
        print("[CASA AJUSTE ITEM ERRO]", e, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

@app.route("/api/casa/ddd-padrao", methods=["GET"])
@login_required
def api_casa_ddd_padrao():
    try:
        id_cliente = session.get("id_cliente")
        dados = obter_dados_loja(id_cliente)
        ddd = str((dados or {}).get("ddd") or "").strip()
        ddd = "".join(ch for ch in ddd if ch.isdigit())[:3]
        return jsonify({"sucesso": True, "ddd": ddd})
    except Exception as e:
        print("[CASA DDD PADRAO ERRO]", e, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(e)}), 500

# ===================== API WhatsApp (uazapi) =====================
def _whatsapp_id_cliente_ou_401():
    """Retorna (id_cliente, None) se ok; (None, resposta_json) se inválido/sem permissão."""
    if (str(session.get("funcao") or "").strip().lower()) != "gerente":
        return None, (jsonify({"sucesso": False, "erro": "Acesso restrito a gerentes."}), 403)
    id_cliente = session.get("id_cliente")
    if not id_cliente:
        return None, (jsonify({"sucesso": False, "erro": "Sessão inválida."}), 401)
    return id_cliente, None


def _whatsapp_ddd_loja(id_cliente):
    try:
        dados = obter_dados_loja(id_cliente)
        ddd = "".join(ch for ch in str((dados or {}).get("ddd") or "") if ch.isdigit())[:3]
        return ddd
    except Exception:
        return ""


def _wa_tel_loja_fmt(dados_loja):
    """Telefone da loja formatado como (DD) NNNNN-NNNN para a mensagem."""
    d = "".join(ch for ch in str((dados_loja or {}).get("telefone") or "") if ch.isdigit())
    ddd = "".join(ch for ch in str((dados_loja or {}).get("ddd") or "") if ch.isdigit())
    if d and ddd and len(d) <= 9:
        d = ddd + d
    if not d:
        return ""
    if len(d) == 11:
        return f"({d[:2]}) {d[2:7]}-{d[7:]}"
    if len(d) == 10:
        return f"({d[:2]}) {d[2:6]}-{d[6:]}"
    return d


def _wa_endereco_cliente(ped):
    """Monta a linha de endereço do cliente a partir da linha agregada do pedido."""
    rua = (str(ped.get("endereco") or "")).strip()
    nro = (str(ped.get("nrocasa") or "")).strip()
    bairro = (str(ped.get("bairro") or "")).strip()
    cidade = (str(ped.get("cidade") or "")).strip()
    base = (f"{rua}, {nro}".strip(", ").strip()) if (rua or nro) else ""
    partes = [p for p in [base, bairro, cidade] if p]
    return " - ".join(partes)


def _montar_msg_despacho_cliente(dados_loja, ped, ent, nropedido):
    nome_loja = (str((dados_loja or {}).get("nome") or "")).strip()
    cliente = (str(ped.get("nome") or ped.get("cliente") or "")).strip()
    entregador = (str(ent.get("nome") or "")).strip()
    tel_loja = _wa_tel_loja_fmt(dados_loja)
    linhas = []
    if nome_loja:
        linhas.append(f"🏍️ *{nome_loja}*")
    saud = f"Olá, {cliente}! " if cliente else ""
    linhas.append(f"{saud}Seu pedido *#{nropedido}* saiu para entrega 🚀")
    if entregador:
        linhas.append(f"O entregador *{entregador}* está a caminho 😊")
    else:
        linhas.append("Já está a caminho 😊")
    if tel_loja:
        linhas.append("")
        linhas.append(f"📞 Dúvidas? {tel_loja}")
    return "\n".join(linhas)


def _montar_msg_despacho_entregador(ped, itens, nropedido):
    cliente = (str(ped.get("nome") or ped.get("cliente") or "")).strip()
    tel = (str(ped.get("telefone") or "")).strip()
    compl = (str(ped.get("complemento") or "")).strip()
    ref = (str(ped.get("referencia") or "")).strip()
    forma = (str(ped.get("formapagamento") or "")).strip()
    try:
        total = float(ped.get("total") or 0)
    except (TypeError, ValueError):
        total = 0.0
    total_fmt = ("R$ " + f"{total:,.2f}").replace(",", "X").replace(".", ",").replace("X", ".")
    endereco = _wa_endereco_cliente(ped)

    linhas = [f"🛵 *Entrega - Pedido #{nropedido}*"]
    if cliente:
        linhas.append(f"👤 Cliente: {cliente}")
    if tel:
        linhas.append(f"📞 {tel}")
    if itens:
        linhas.append("")
        linhas.append("🛍️ *Itens*")
        for it in itens:
            qtd = it.get("quantidade") or 0
            try:
                qf = int(qtd) if float(qtd) == int(float(qtd)) else float(qtd)
            except (TypeError, ValueError):
                qf = qtd
            prod = (str(it.get("produto") or "")).strip()
            if prod:
                linhas.append(f"• {qf}x {prod}")
    linhas.append("")
    if endereco:
        linhas.append(f"📍 {endereco}")
    extra = []
    if compl:
        extra.append(f"Compl.: {compl}")
    if ref:
        extra.append(f"Ref.: {ref}")
    if extra:
        linhas.append("🏠 " + " / ".join(extra))
    pag_total = []
    if forma:
        pag_total.append(f"💳 {forma}")
    pag_total.append(f"💰 Total: {total_fmt}")
    linhas.append("  •  ".join(pag_total))
    if endereco:
        linhas.append(f"🗺️ Mapa: https://www.google.com/maps/search/?api=1&query={quote(endereco)}")
    return "\n".join(linhas)


def _telefone_whatsapp_valido(telefone):
    """True se telefone parece real (não placeholder BALCAO{n})."""
    t = str(telefone or "").strip()
    if not t or t.upper().startswith("BALCAO"):
        return False
    digits = "".join(ch for ch in t if ch.isdigit())
    return len(digits) >= 10


def _normalizar_telefone_balcao(telefone_raw, nropedido, id_cliente):
    """Placeholder BALCAO{n} ou celular normalizado com DDD da loja."""
    try:
        nro = int(nropedido or 0)
    except (TypeError, ValueError):
        nro = 0
    tel_payload = str(telefone_raw or "").strip()
    tel_upper = tel_payload.upper()
    tel_digits = "".join(ch for ch in tel_payload if ch.isdigit())
    if tel_upper in ("", "BALCAO") or (tel_upper.startswith("BALCAO") and len(tel_digits) < 8):
        return f"BALCAO{nro}" if nro > 0 else "BALCAO"
    if not tel_upper.startswith("BALCAO") and len(tel_digits) >= 8:
        dados_loja_b = obter_dados_loja(id_cliente) or {}
        ddd_b = "".join(ch for ch in str(dados_loja_b.get("ddd") or "") if ch.isdigit())[:3]
        if len(tel_digits) in (8, 9) and ddd_b:
            return ddd_b + tel_digits
        return tel_digits
    return f"BALCAO{nro}" if nro > 0 else "BALCAO"


def _propagar_telefone_balcao_pedido(cur, id_cliente, nropedido, telefone_raw, nome=None, cliente=None):
    """Atualiza telefone (e opcionalmente nome) em todas as linhas do pedido balcão."""
    try:
        nro = int(nropedido or 0)
    except (TypeError, ValueError):
        return False
    if nro <= 0:
        return False
    telefone = _normalizar_telefone_balcao(telefone_raw, nro, id_cliente)
    if not _telefone_whatsapp_valido(telefone):
        return False
    sets = ["telefone = %s"]
    params = [telefone]
    nome_limpo = str(nome or "").strip()
    if nome_limpo:
        sets.extend(["nome = %s", "cliente = %s"])
        params.extend([nome_limpo, str(cliente or nome_limpo).strip()])
    params.extend([id_cliente, nro])
    cur.execute(
        f"""
        UPDATE pedido_diarios
        SET {", ".join(sets)}
        WHERE id_cliente = %s AND origem = 'BALCAO' AND nropedido = %s
          AND UPPER(COALESCE(status_pedido, '')) <> 'ITEM_REMOVIDO'
        """,
        tuple(params),
    )
    return True


def _telefone_de_concat(telefones_concat):
    """Escolhe celular real entre vários telefones concatenados (GROUP_CONCAT)."""
    candidatos = []
    vistos = set()
    for parte in str(telefones_concat or "").split(","):
        t = parte.strip()
        if not t or t in vistos:
            continue
        vistos.add(t)
        candidatos.append(t)
    for t in candidatos:
        if _telefone_whatsapp_valido(t):
            return t
    return candidatos[0] if candidatos else ""


def _montar_msg_balcao_pronto(dados_loja, ped, nropedido, texto_custom=None):
    cliente = (str(ped.get("nome") or ped.get("cliente") or "")).strip()
    nome_loja = (str((dados_loja or {}).get("nome") or "")).strip()
    tel_loja = _wa_tel_loja_fmt(dados_loja)
    end_loja = ", ".join(
        p for p in [(str((dados_loja or {}).get("endereco") or "")).strip(),
                    (str((dados_loja or {}).get("cidade") or "")).strip()] if p
    )
    custom = (str(texto_custom or "")).strip()
    if custom:
        return (
            custom.replace("{nome}", cliente)
            .replace("{pedido}", str(nropedido))
            .replace("{loja}", nome_loja)
            .replace("{telefone}", tel_loja)
            .replace("{endereco}", end_loja)
        )
    linhas = []
    if nome_loja:
        linhas.append(f"🍽️ *{nome_loja}*")
    saud = f"Olá, {cliente}! " if cliente else ""
    linhas.append(f"{saud}Seu pedido *#{nropedido}* está pronto 🎉")
    linhas.append("Já pode retirar no balcão.")
    if tel_loja or end_loja:
        linhas.append("")
        if tel_loja:
            linhas.append(f"📞 *Fale com a loja:* {tel_loja}")
        if end_loja:
            linhas.append(f"📍 {end_loja}")
    linhas.append("")
    linhas.append("Obrigado pela preferência! 🙏")
    return "\n".join(linhas)


def _notificar_despacho_whatsapp(id_cliente, nropedido, codigo_entregador):
    """Dispara avisos de despacho (cliente + entregador). Não-bloqueante, isolado."""
    if is_retail():
        return
    cfg = uazapi_service.obter_config(id_cliente) or {}
    ativo = bool(int(cfg.get("ativo") or 0)) and bool(cfg.get("instancia_token"))
    if not (ativo and int(cfg.get("notif_despacho") or 0)):
        return

    conn = None
    cur = None
    try:
        conn = conectar()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT MAX(nome) AS nome, MAX(cliente) AS cliente, MAX(telefone) AS telefone,
                   MAX(endereco) AS endereco, MAX(nrocasa) AS nrocasa,
                   MAX(complemento) AS complemento, MAX(referencia) AS referencia,
                   MAX(bairro) AS bairro, MAX(cidade) AS cidade,
                   MAX(formapagamento) AS formapagamento,
                   SUM(COALESCE(preco,0)*COALESCE(quantidade,0)) AS total
            FROM pedido_diarios
            WHERE id_cliente=%s AND origem='DELIVERY' AND nropedido=%s
              AND UPPER(COALESCE(status_pedido,''))='ROTA'
            """,
            (id_cliente, nropedido),
        )
        ped = cur.fetchone() or {}
        cur.execute(
            """
            SELECT produto, quantidade
            FROM pedido_diarios
            WHERE id_cliente=%s AND origem='DELIVERY' AND nropedido=%s
              AND UPPER(COALESCE(status_pedido,''))='ROTA'
            ORDER BY chave
            """,
            (id_cliente, nropedido),
        )
        itens = cur.fetchall() or []
        cur.execute(
            "SELECT nome, telefone FROM entregador WHERE chave=%s AND id_cliente=%s LIMIT 1",
            (codigo_entregador, id_cliente),
        )
        ent = cur.fetchone() or {}
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

    dados_loja = obter_dados_loja(id_cliente) or {}
    ddd = _whatsapp_ddd_loja(id_cliente)

    tel_cli = (str(ped.get("telefone") or "")).strip()
    if tel_cli:
        msg_cli = _montar_msg_despacho_cliente(dados_loja, ped, ent, nropedido)
        uazapi_service.enviar_texto_async(
            id_cliente, tel_cli, msg_cli, evento="despacho_cliente", ddd_padrao=ddd
        )

    tel_ent = (str(ent.get("telefone") or "")).strip()
    if tel_ent:
        msg_ent = _montar_msg_despacho_entregador(ped, itens, nropedido)
        uazapi_service.enviar_texto_async(
            id_cliente, tel_ent, msg_ent, evento="despacho_entregador", ddd_padrao=ddd
        )


@app.route("/api/whatsapp/config", methods=["GET"])
@login_required
def api_whatsapp_config_get():
    id_cliente, err = _whatsapp_id_cliente_ou_401()
    if err:
        return err
    try:
        cfg = uazapi_service.obter_config(id_cliente) or {}
        return jsonify({
            "sucesso": True,
            "ativo": int(cfg.get("ativo") or 0),
            "instancia_nome": cfg.get("instancia_nome") or "",
            "tem_token": bool(cfg.get("instancia_token")),
            "notif_delivery_copia": int(cfg.get("notif_delivery_copia") or 0),
            "notif_despacho": int(cfg.get("notif_despacho") or 0),
            "notif_balcao_pronto": int(cfg.get("notif_balcao_pronto") or 0),
            "notif_mesa_conta": int(cfg.get("notif_mesa_conta") or 0),
            "texto_despacho_cliente": cfg.get("texto_despacho_cliente") or "",
            "texto_balcao_pronto": cfg.get("texto_balcao_pronto") or "",
        })
    except Exception as e:
        print("[WHATSAPP CONFIG GET ERRO]", e, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(e)}), 500


@app.route("/api/whatsapp/config", methods=["POST"])
@login_required
def api_whatsapp_config_post():
    id_cliente, err = _whatsapp_id_cliente_ou_401()
    if err:
        return err
    conn = None
    cur = None
    try:
        body = request.get_json(silent=True) or {}

        def _flag(nome):
            return 1 if str(body.get(nome)).strip().lower() in ("1", "true", "sim", "on", "yes") else 0

        conn = conectar()
        cur = conn.cursor()
        cur.execute("SELECT id FROM whatsapp_config WHERE id_cliente = %s LIMIT 1", (id_cliente,))
        existe = cur.fetchone()
        campos = (
            _flag("ativo"),
            _flag("notif_delivery_copia"),
            _flag("notif_despacho"),
            _flag("notif_balcao_pronto"),
            _flag("notif_mesa_conta"),
            (body.get("texto_despacho_cliente") or None),
            (body.get("texto_balcao_pronto") or None),
        )
        if existe:
            cur.execute(
                """
                UPDATE whatsapp_config
                   SET ativo = %s, notif_delivery_copia = %s, notif_despacho = %s,
                       notif_balcao_pronto = %s, notif_mesa_conta = %s,
                       texto_despacho_cliente = %s, texto_balcao_pronto = %s
                 WHERE id_cliente = %s
                """,
                campos + (id_cliente,),
            )
        else:
            cur.execute(
                """
                INSERT INTO whatsapp_config
                    (ativo, notif_delivery_copia, notif_despacho, notif_balcao_pronto,
                     notif_mesa_conta, texto_despacho_cliente, texto_balcao_pronto, id_cliente)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                campos + (id_cliente,),
            )
        conn.commit()
        return jsonify({"sucesso": True, "mensagem": "Configuração de WhatsApp salva."})
    except Exception as e:
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        print("[WHATSAPP CONFIG POST ERRO]", e, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route("/api/whatsapp/instancia/criar", methods=["POST"])
@login_required
def api_whatsapp_instancia_criar():
    id_cliente, err = _whatsapp_id_cliente_ou_401()
    if err:
        return err
    body = request.get_json(silent=True) or {}
    nome = (body.get("nome") or "").strip() or f"loja_{id_cliente}"
    res = uazapi_service.criar_instancia(id_cliente, nome)
    return jsonify({"sucesso": res.get("ok", False), "erro": res.get("erro")}), (200 if res.get("ok") else 400)


@app.route("/api/whatsapp/instancia/conectar", methods=["POST"])
@login_required
def api_whatsapp_instancia_conectar():
    id_cliente, err = _whatsapp_id_cliente_ou_401()
    if err:
        return err
    body = request.get_json(silent=True) or {}
    res = uazapi_service.conectar_instancia(id_cliente, phone=(body.get("phone") or None))
    return jsonify({
        "sucesso": res.get("ok", False),
        "qrcode": res.get("qrcode"),
        "paircode": res.get("paircode"),
        "status": res.get("status"),
        "erro": res.get("erro"),
    }), (200 if res.get("ok") else 400)


@app.route("/api/whatsapp/instancia/status", methods=["GET"])
@login_required
def api_whatsapp_instancia_status():
    id_cliente, err = _whatsapp_id_cliente_ou_401()
    if err:
        return err
    res = uazapi_service.status_instancia(id_cliente)
    return jsonify({
        "sucesso": res.get("ok", False),
        "status": res.get("status", "disconnected"),
        "configurado": res.get("configurado", False),
        "erro": res.get("erro"),
    })


@app.route("/api/whatsapp/instancia/desconectar", methods=["POST"])
@login_required
def api_whatsapp_instancia_desconectar():
    id_cliente, err = _whatsapp_id_cliente_ou_401()
    if err:
        return err
    res = uazapi_service.desconectar_instancia(id_cliente)
    return jsonify({"sucesso": res.get("ok", False), "erro": res.get("erro")}), (200 if res.get("ok") else 400)


@app.route("/api/whatsapp/enviar-teste", methods=["POST"])
@login_required
def api_whatsapp_enviar_teste():
    id_cliente, err = _whatsapp_id_cliente_ou_401()
    if err:
        return err
    body = request.get_json(silent=True) or {}
    telefone = (body.get("telefone") or "").strip()
    if not telefone:
        return jsonify({"sucesso": False, "erro": "Informe um telefone."}), 400
    mensagem = (body.get("mensagem") or "Mensagem de teste do sistema (LojaOnline).").strip()
    res = uazapi_service.enviar_texto(
        id_cliente, telefone, mensagem, evento="teste", ddd_padrao=_whatsapp_ddd_loja(id_cliente)
    )
    return jsonify({"sucesso": res.get("ok", False), "erro": res.get("erro")}), (200 if res.get("ok") else 400)


@app.route("/api/whatsapp/recursos", methods=["GET"])
@login_required
def api_whatsapp_recursos():
    """Informa ao PDV quais recursos de WhatsApp estão ligados (sem expor token).

    Disponível para qualquer usuário logado (o atendente do /casa pode não ser gerente).
    """
    try:
        id_cliente = session.get("id_cliente")
        if not id_cliente:
            return jsonify({"sucesso": False, "erro": "Sessão inválida."}), 401
        cfg = uazapi_service.obter_config(id_cliente) or {}
        ativo = bool(int(cfg.get("ativo") or 0)) and bool(cfg.get("instancia_token"))
        dados = obter_dados_loja(id_cliente) or {}
        loja = {
            "nome": (dados.get("nome") or "").strip(),
            "telefone": (str(dados.get("telefone") or "")).strip(),
            "ddd": (str(dados.get("ddd") or "")).strip(),
            "endereco": (dados.get("endereco") or "").strip(),
            "bairro": (dados.get("bairro") or "").strip(),
            "cidade": (dados.get("cidade") or "").strip(),
        }
        return jsonify({
            "sucesso": True,
            "ativo": ativo,
            "notif_delivery_copia": bool(int(cfg.get("notif_delivery_copia") or 0)),
            "notif_despacho": bool(int(cfg.get("notif_despacho") or 0)),
            "notif_balcao_pronto": bool(int(cfg.get("notif_balcao_pronto") or 0)),
            "notif_mesa_conta": bool(int(cfg.get("notif_mesa_conta") or 0)),
            "loja": loja,
        })
    except Exception as e:
        print("[WHATSAPP RECURSOS ERRO]", e, flush=True)
        return jsonify({"sucesso": False, "erro": str(e)}), 500


@app.route("/api/whatsapp/enviar-pedido", methods=["POST"])
@login_required
def api_whatsapp_enviar_pedido():
    """Envia a cópia do pedido (texto) ao cliente. Manual, não bloqueia o fluxo do PDV."""
    try:
        id_cliente = session.get("id_cliente")
        if not id_cliente:
            return jsonify({"sucesso": False, "erro": "Sessão inválida."}), 401
        body = request.get_json(silent=True) or {}
        telefone = (body.get("telefone") or "").strip()
        conteudo = (body.get("conteudo") or "").strip()
        if not telefone:
            return jsonify({"sucesso": False, "erro": "Telefone do cliente não informado."}), 400
        if not conteudo:
            return jsonify({"sucesso": False, "erro": "Conteúdo do pedido vazio."}), 400

        cfg = uazapi_service.obter_config(id_cliente) or {}
        if not (bool(int(cfg.get("ativo") or 0)) and bool(cfg.get("instancia_token"))):
            return jsonify({"sucesso": False, "erro": "WhatsApp não está ativo para esta loja."}), 400
        if not bool(int(cfg.get("notif_delivery_copia") or 0)):
            return jsonify({"sucesso": False, "erro": "Envio de cópia (delivery) está desligado nas configurações."}), 400

        res = uazapi_service.enviar_texto(
            id_cliente, telefone, conteudo, evento="delivery_copia",
            ddd_padrao=_whatsapp_ddd_loja(id_cliente),
        )
        return jsonify({"sucesso": res.get("ok", False), "erro": res.get("erro")}), (200 if res.get("ok") else 400)
    except Exception as e:
        print("[WHATSAPP ENVIAR PEDIDO ERRO]", e, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(e)}), 500


@app.route("/api/whatsapp/avisar-pronto", methods=["POST"])
@login_required
def api_whatsapp_avisar_pronto():
    """Avisa cliente balcão que o pedido está pronto (manual pelo dashboard)."""
    conn = None
    cur = None
    try:
        id_cliente = session.get("id_cliente")
        if not id_cliente:
            return jsonify({"sucesso": False, "erro": "Sessão inválida."}), 401
        body = request.get_json(silent=True) or {}
        origem = str(body.get("origem") or "BALCAO").strip().upper()
        if origem != "BALCAO":
            return jsonify({"sucesso": False, "erro": "Aviso pronto disponível apenas para BALCAO."}), 400
        try:
            nropedido = int(body.get("nropedido") or 0)
        except (TypeError, ValueError):
            nropedido = 0
        if nropedido <= 0:
            return jsonify({"sucesso": False, "erro": "Informe nropedido válido."}), 400

        cfg = uazapi_service.obter_config(id_cliente) or {}
        if not (bool(int(cfg.get("ativo") or 0)) and bool(cfg.get("instancia_token"))):
            return jsonify({"sucesso": False, "erro": "WhatsApp não está ativo para esta loja."}), 400
        if not bool(int(cfg.get("notif_balcao_pronto") or 0)):
            return jsonify({"sucesso": False, "erro": "Aviso de pedido pronto (balcão) está desligado nas configurações."}), 400

        conn = conectar()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT MAX(nome) AS nome, MAX(cliente) AS cliente,
                   GROUP_CONCAT(DISTINCT telefone SEPARATOR ',') AS telefones_concat,
                   MAX(UPPER(COALESCE(status_pedido, ''))) AS status_pedido,
                   MAX(UPPER(COALESCE(status_comanda, 'NORMAL'))) AS status_comanda
            FROM pedido_diarios
            WHERE id_cliente = %s AND origem = 'BALCAO' AND nropedido = %s
              AND UPPER(COALESCE(status_pedido, '')) <> 'ITEM_REMOVIDO'
            """,
            (id_cliente, nropedido),
        )
        ped = cur.fetchone() or {}
        if not ped.get("telefones_concat"):
            return jsonify({"sucesso": False, "erro": "Pedido não encontrado."}), 404

        st = str(ped.get("status_pedido") or "").upper()
        st_com = str(ped.get("status_comanda") or "NORMAL").upper()
        if st_com == "CANCELADA":
            return jsonify({"sucesso": False, "erro": "Comanda cancelada."}), 400
        if st not in ("ABERTO", "ABERTA"):
            return jsonify({"sucesso": False, "erro": "Pedido não está em ABERTO (não é possível avisar pronto)."}), 400

        telefone = _telefone_de_concat(ped.get("telefones_concat"))
        if not _telefone_whatsapp_valido(telefone):
            return jsonify({"sucesso": False, "erro": "Cliente sem celular válido (informe telefone no balcão)."}), 400

        dados_loja = obter_dados_loja(id_cliente) or {}
        msg = _montar_msg_balcao_pronto(
            dados_loja, ped, nropedido, texto_custom=cfg.get("texto_balcao_pronto")
        )
        res = uazapi_service.enviar_texto(
            id_cliente, telefone, msg, evento="balcao_pronto",
            ddd_padrao=_whatsapp_ddd_loja(id_cliente),
        )
        return jsonify({
            "sucesso": res.get("ok", False),
            "erro": res.get("erro"),
            "mensagem": "Cliente avisado no WhatsApp." if res.get("ok") else None,
        }), (200 if res.get("ok") else 400)
    except Exception as e:
        print("[WHATSAPP AVISAR PRONTO ERRO]", e, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route("/api/casa/historico-cliente", methods=["GET"])
@login_required
def api_casa_historico_cliente():
    conn = None
    cur = None
    try:
        id_cliente = session.get("id_cliente")
        if not id_cliente:
            return jsonify({"sucesso": False, "erro": "Sessão inválida."}), 401
        telefone = "".join(ch for ch in str(request.args.get("telefone") or "") if ch.isdigit())
        if not telefone:
            return jsonify({"sucesso": False, "erro": "Telefone é obrigatório"}), 400
        conn = conectar()
        cur = conn.cursor(dictionary=True)
        ordered = _historico_cliente_from_pedido_tabelas(cur, int(id_cliente), telefone)
        if not ordered:
            ordered = _historico_cliente_from_liquidada(cur, int(id_cliente), telefone)
        return jsonify({"sucesso": True, "total_pedidos": len(ordered), "pedidos": ordered[:3]})
    except Exception as e:
        print("[CASA HISTORICO CLIENTE ERRO]", e, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

def _dir_pedidos_salvos_configurado():
    """Pasta base dos .txt do /casa (override: variável de ambiente LOJA_PEDIDOS_SALVOS_DIR)."""
    d = (os.environ.get("LOJA_PEDIDOS_SALVOS_DIR") or "").strip()
    return d if d else r"C:\Geral\Pedidos_Salvos"


def _uniq_base_dirs_candidates():
    primary = os.path.abspath(_dir_pedidos_salvos_configurado())
    here = os.path.dirname(os.path.abspath(__file__))
    fallback_proj = os.path.abspath(os.path.join(here, "pedidos_salvos_export"))
    fallback_temp = os.path.abspath(
        os.path.join(tempfile.gettempdir(), "LojaOnline_Pedidos_Salvos")
    )
    seen = set()
    out = []
    for p in (primary, fallback_proj, fallback_temp):
        k = os.path.normcase(os.path.normpath(p))
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out


def _salvar_txt_pedido_casa(conteudo, nropedido, forma_pagamento):
    """
    Grava o .txt do pedido. Tenta em ordem: pasta configurada, projeto, %TEMP%.
    Qualquer OSError em uma pasta tenta a seguinte (ex.: C:\\Geral sem permissão).
    Retorna (caminho_completo, nome_arquivo, usou_fallback).
    """
    data_dir = time.strftime("%Y-%m-%d")
    sufixo = time.strftime("%H%M%S")
    nome_arquivo = f"pedido_{nropedido or 'sem_numero'}_{sufixo}.txt"
    corpo = str(conteudo or "").strip()
    if forma_pagamento:
        corpo += f"\nFORMA DE PAGAMENTO: {forma_pagamento}\n"

    candidatos = _uniq_base_dirs_candidates()
    ultimo = None
    for idx, base_dir in enumerate(candidatos):
        try:
            pasta = os.path.join(base_dir, data_dir)
            os.makedirs(pasta, exist_ok=True)
            caminho = os.path.join(pasta, nome_arquivo)
            with open(caminho, "w", encoding="utf-8") as f:
                f.write(corpo)
            return caminho, nome_arquivo, idx > 0
        except OSError as e:
            ultimo = e
            continue
    if ultimo:
        raise ultimo
    raise OSError("Não foi possível gravar o arquivo do pedido.")


@app.route("/api/casa/salvar-txt", methods=["POST"])
@login_required
def api_casa_salvar_txt():
    try:
        dados = request.get_json(silent=True) or {}
        conteudo = str(dados.get("conteudo", "") or "").strip()
        nropedido = int(dados.get("nropedido") or 0)
        forma_pagamento = str(dados.get("forma_pagamento", "") or "").strip()
        if not conteudo:
            return jsonify({"sucesso": False, "erro": "Conteúdo vazio para salvar"}), 400
        caminho, nome_arquivo, usou_fallback = _salvar_txt_pedido_casa(
            conteudo, nropedido, forma_pagamento
        )
        out = {"sucesso": True, "caminho": caminho, "arquivo": nome_arquivo}
        if usou_fallback:
            out["aviso"] = (
                "Não foi possível gravar em C:\\Geral\\Pedidos_Salvos (permissão negada ou pasta bloqueada). "
                "O arquivo foi salvo em pasta alternativa (projeto ou %TEMP%\\LojaOnline_Pedidos_Salvos). "
                "Defina LOJA_PEDIDOS_SALVOS_DIR com um caminho gravável ou dê permissão de escrita em C:\\Geral\\Pedidos_Salvos "
                "(utilizador do serviço / Python)."
            )
        return jsonify(out)
    except Exception as e:
        print("[CASA SALVAR TXT ERRO]", e, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(e)}), 500


@app.route("/api/casa/confirmar-impressao", methods=["POST"])
@login_required
def api_casa_confirmar_impressao():
    """Confirma pedido após impressão no Print Bridge (PC local)."""
    dados = request.get_json(silent=True) or {}
    origem = (dados.get("origem") or "").strip().lower()
    origem_fc = origem in ("fechamento_caixa", "fechamento")
    try:
        nropedido = int(dados.get("nropedido", 0) or 0)
    except (TypeError, ValueError):
        nropedido = 0
    printer = str(dados.get("printer", "") or "").strip() or "bridge-local"
    if origem == "casa" and nropedido > 0 and not origem_fc:
        conn_status = None
        cur_status = None
        try:
            conn_status = conectar()
            cur_status = conn_status.cursor()
            id_cliente = session.get("id_cliente")
            blocked = _assert_casa_editavel(cur_status, id_cliente, nropedido)
            if blocked:
                return blocked
            cur_status.execute(
                "SELECT UPPER(COALESCE(MAX(origem), '')) AS origem FROM pedido_diarios WHERE nropedido = %s AND id_cliente = %s",
                (nropedido, id_cliente),
            )
            row_orig = cur_status.fetchone() or {}
            origem_ped = str(row_orig[0] if isinstance(row_orig, (tuple, list)) else row_orig.get("origem") or "").upper()
            tel_payload = dados.get("telefone")
            if origem_ped == "BALCAO" and tel_payload is not None:
                _propagar_telefone_balcao_pedido(
                    cur_status,
                    id_cliente,
                    nropedido,
                    tel_payload,
                    nome=(dados.get("nome") or dados.get("cliente") or "").strip(),
                    cliente=(dados.get("cliente") or dados.get("nome") or "").strip(),
                )
            cur_status.execute(
                f"""
                UPDATE pedido_diarios
                SET status_pedido = 'ABERTO'
                WHERE nropedido = %s
                  AND id_cliente = %s
                  AND origem IN ('DELIVERY','BALCAO')
                  AND UPPER(COALESCE(status_pedido, '')) = 'AGUARDE'
                  AND NOT ({_sql_comanda_cancelada('pedido_diarios')})
                """,
                (nropedido, id_cliente),
            )
            conn_status.commit()
        except Exception as e:
            if conn_status:
                conn_status.rollback()
            return jsonify({"sucesso": False, "erro": str(e)}), 500
        finally:
            if cur_status:
                cur_status.close()
            if conn_status:
                conn_status.close()
    return jsonify({
        "sucesso": True,
        "printer": printer,
        "via": "confirmar",
        "copias": int(dados.get("copias", 1) or 1),
    })


@app.route("/api/preparo/marcar", methods=["POST"])
@login_required
def api_preparo_marcar():
    conn = None
    cur = None
    try:
        _ensure_pedido_diarios_preparo_columns()
        id_cliente = session.get("id_cliente")
        if not id_cliente:
            return jsonify({"sucesso": False, "erro": "Sessão inválida."}), 401
        data = request.get_json(silent=True) or {}
        ids = data.get("ids") or []
        if not isinstance(ids, list):
            return jsonify({"sucesso": False, "erro": "ids deve ser uma lista."}), 400
        ids_ok = []
        seen = set()
        for v in ids:
            try:
                n = int(str(v).strip())
            except Exception:
                continue
            if n <= 0 or n in seen:
                continue
            seen.add(n)
            ids_ok.append(n)
        if not ids_ok:
            return jsonify({"sucesso": False, "erro": "Nenhum id válido para marcar."}), 400
        if len(ids_ok) > 300:
            return jsonify({"sucesso": False, "erro": "Muitos ids em uma única solicitação."}), 400

        conn = conectar()
        conn.start_transaction()
        cur = conn.cursor()
        ph = ",".join(["%s"] * len(ids_ok))
        cur.execute(
            f"""
            SELECT chave, UPPER(COALESCE(imp_preparo,'N')) AS imp_preparo
            FROM pedido_diarios
            WHERE id_cliente = %s
              AND chave IN ({ph})
            """,
            tuple([int(id_cliente)] + ids_ok),
        )
        rows_pre = cur.fetchall() or []
        total_match = 0
        ja_marcados = 0
        try:
            for r in rows_pre:
                total_match += 1
                try:
                    flag = (r[1] if not isinstance(r, dict) else r.get("imp_preparo")) or "N"
                except Exception:
                    flag = "N"
                if str(flag).strip().upper() == "S":
                    ja_marcados += 1
        except Exception:
            total_match = 0
            ja_marcados = 0

        cur.execute(
            f"""
            UPDATE pedido_diarios
            SET imp_preparo = 'S', imp_preparo_em = NOW()
            WHERE id_cliente = %s
              AND chave IN ({ph})
              AND UPPER(COALESCE(imp_preparo,'N')) <> 'S'
            """,
            tuple([int(id_cliente)] + ids_ok),
        )
        updated = int(cur.rowcount or 0)
        conn.commit()
        return jsonify(
            {
                "sucesso": True,
                "total": int(total_match),
                "ja_marcados": int(ja_marcados),
                "atualizados": int(updated),
            }
        )
    except Exception as e:
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        print("[PREPARO MARCAR ERRO]", e, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route("/api/baixa/pedidos", methods=["GET"])
@login_required
def api_baixa_pedidos():
    conn = None
    cur = None
    try:
        id_cliente = session.get("id_cliente")
        conn = conectar()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT
                pd.origem,
                pd.nropedido,
                MAX(pd.chave) AS last_id,
                SUM(COALESCE(pd.preco, 0) * COALESCE(pd.quantidade, 0)) AS total,
                SUM(CASE WHEN UPPER(TRIM(COALESCE(pd.status_pedido, ''))) IN ('ABERTO','ABERTA') THEN 1 ELSE 0 END) AS aberto_count,
                SUM(CASE WHEN UPPER(TRIM(COALESCE(pd.status_pedido, ''))) = 'ROTA' THEN 1 ELSE 0 END) AS rota_count,
                SUM(CASE WHEN UPPER(TRIM(COALESCE(pd.status_pedido, ''))) = 'AGUARDE' THEN 1 ELSE 0 END) AS aguarde_count,
                MAX(COALESCE(pd.cliente, pd.nome, '')) AS cliente,
                MAX(COALESCE(pd.telefone, '')) AS telefone,
                MAX(COALESCE(pd.endereco, '')) AS endereco,
                MAX(COALESCE(pd.nrocasa, '')) AS nrocasa,
                MAX(COALESCE(pd.complemento, '')) AS complemento,
                MAX(COALESCE(pd.formapagamento, '')) AS formapagamento,
                MAX(pd.valor_pago_troco) AS valor_pago_troco,
                MAX(COALESCE(pd.entregador, '')) AS entregador_codigo,
                MAX(UPPER(TRIM(COALESCE(pd.status_pedido, '')))) AS status_pedido,
                MAX(UPPER(TRIM(COALESCE(pd.status_comanda, '')))) AS status_comanda,
                MAX(e.nome) AS entregador_nome
            FROM pedido_diarios pd
            LEFT JOIN entregador e
              ON e.id_cliente = pd.id_cliente
             AND (
                  BINARY CAST(e.chave AS CHAR) = BINARY TRIM(COALESCE(pd.entregador, ''))
                  OR e.chave = CAST(NULLIF(TRIM(pd.entregador), '') AS UNSIGNED)
                 )
            WHERE pd.id_cliente = %s
              AND pd.origem IN ('DELIVERY','BALCAO')
              AND UPPER(TRIM(COALESCE(pd.status_pedido, ''))) <> 'ITEM_REMOVIDO'
            GROUP BY pd.origem, pd.nropedido
            ORDER BY last_id DESC
            LIMIT 250
            """,
            (id_cliente,),
        )
        rows = cur.fetchall() or []
        out = []
        for r in rows:
            if str(r.get("status_comanda") or "").strip().upper() == STATUS_COMANDA_CANCELADA:
                continue
            if int(r.get("aguarde_count") or 0) > 0:
                continue
            aberto_count = int(r.get("aberto_count") or 0)
            rota_count = int(r.get("rota_count") or 0)
            if aberto_count <= 0 and rota_count <= 0:
                continue
            end_parts = [str(r.get("endereco") or "").strip(), str(r.get("nrocasa") or "").strip()]
            end = ", ".join([p for p in end_parts if p])
            comp = str(r.get("complemento") or "").strip()
            if comp:
                end = (end + " - " + comp) if end else comp
            if aberto_count > 0:
                status_ui = "ABERTO"
            elif rota_count > 0:
                status_ui = "ROTA"
            else:
                status_ui = str(r.get("status_pedido") or "ABERTO").strip().upper() or "ABERTO"
            cod_ent = str(r.get("entregador_codigo") or "").strip()
            nome_ent = str(r.get("entregador_nome") or "").strip()
            out.append(
                {
                    "origem": str(r.get("origem") or "").upper(),
                    "nropedido": int(r.get("nropedido") or 0),
                    "total": float(r.get("total") or 0),
                    "cliente": str(r.get("cliente") or "").strip(),
                    "telefone": str(r.get("telefone") or "").strip(),
                    "endereco": end,
                    "formapagamento": str(r.get("formapagamento") or "").strip(),
                    "valor_pago_troco": float(r.get("valor_pago_troco") or 0)
                    if r.get("valor_pago_troco") is not None
                    else None,
                    "status_pedido": status_ui,
                    "entregador_codigo": cod_ent,
                    "entregador_nome": nome_ent,
                }
            )
        return jsonify({"sucesso": True, "pedidos": out})
    except Exception as e:
        print("[BAIXA PEDIDOS ERRO]", e, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route("/api/pedido/cancelar-comanda", methods=["POST"])
@login_required
def api_pedido_cancelar_comanda():
    conn = None
    cur = None
    try:
        data = request.get_json(silent=True) or {}
        origem = str(data.get("origem") or "").strip().upper()
        try:
            nropedido = int(data.get("nropedido") or 0)
        except (TypeError, ValueError):
            nropedido = 0
        confirmacao = str(data.get("confirmacao") or "").strip().upper()
        if confirmacao != "CANCELAR":
            return jsonify({"sucesso": False, "erro": "Confirmação obrigatória (confirmacao=CANCELAR)."}), 400
        if not _origem_delivery_balcao_valida(origem):
            return jsonify({"sucesso": False, "erro": "Origem inválida. Use DELIVERY ou BALCAO."}), 400
        if nropedido <= 0:
            return jsonify({"sucesso": False, "erro": "Número do pedido inválido."}), 400
        id_cliente = session.get("id_cliente")
        if not id_cliente:
            return jsonify({"sucesso": False, "erro": "Sessão inválida."}), 401
        conn = conectar()
        cur = conn.cursor()
        pode, motivo = _comanda_pode_cancelar(cur, id_cliente, origem, nropedido)
        if not pode:
            code = 404 if motivo == "Pedido não encontrado." else 409
            return jsonify({"sucesso": False, "erro": motivo}), code
        cur.execute(
            """
            UPDATE pedido_diarios
            SET status_comanda = %s
            WHERE id_cliente = %s AND origem = %s AND nropedido = %s
            """,
            (STATUS_COMANDA_CANCELADA, int(id_cliente), origem, int(nropedido)),
        )
        linhas = int(cur.rowcount or 0)
        conn.commit()
        return jsonify(
            {
                "sucesso": True,
                "mensagem": f"Comanda #{nropedido} ({origem}) cancelada.",
                "origem": origem,
                "nropedido": int(nropedido),
                "linhas_afetadas": linhas,
            }
        )
    except Exception as e:
        if conn:
            conn.rollback()
        print("[CANCELAR COMANDA ERRO]", e, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route("/api/dashboard/delivery-balcao", methods=["GET"])
@login_required
def api_dashboard_delivery_balcao():
    conn = None
    cur = None
    try:
        id_cliente = session.get("id_cliente")
        status = str(request.args.get("status") or "").strip().lower()
        if status not in ("", "aberto", "recebido", "todos", "cancelado"):
            status = ""
        conn = conectar()
        cur = conn.cursor(dictionary=True)
        status_filter_sql = ""
        cancelada_sql = _sql_comanda_cancelada("pd")
        if status == "cancelado":
            status_filter_sql = f"AND {cancelada_sql}"
        elif status == "" or status == "aberto":
            status_filter_sql = (
                "AND UPPER(TRIM(COALESCE(pd.status_pedido, ''))) IN ('ABERTO','ABERTA','ROTA') "
                f"AND NOT ({cancelada_sql})"
            )
        elif status == "recebido":
            status_filter_sql = (
                "AND UPPER(TRIM(COALESCE(pd.status_pedido, ''))) = 'RECEBIDO' "
                f"AND NOT ({cancelada_sql})"
            )
        else:
            status_filter_sql = "AND UPPER(TRIM(COALESCE(pd.status_pedido, ''))) IN ('ABERTO','ABERTA','RECEBIDO','ROTA')"
        origem_filter_sql = "AND pd.origem = 'BALCAO'" if is_retail() else "AND pd.origem IN ('DELIVERY','BALCAO')"
        cur.execute(
            f"""
            SELECT
                pd.origem,
                pd.nropedido,
                MAX(pd.chave) AS last_id,
                SUM(COALESCE(pd.preco, 0) * COALESCE(pd.quantidade, 0)) AS total,
                SUM(COALESCE(pd.quantidade, 0)) AS total_itens,
                SUM(CASE WHEN UPPER(TRIM(COALESCE(pd.status_pedido, ''))) IN ('ABERTO','ABERTA') THEN 1 ELSE 0 END) AS aberto_count,
                SUM(CASE WHEN UPPER(TRIM(COALESCE(pd.status_pedido, ''))) = 'ROTA' THEN 1 ELSE 0 END) AS rota_count,
                SUM(CASE WHEN UPPER(TRIM(COALESCE(pd.status_pedido, ''))) = 'RECEBIDO' THEN 1 ELSE 0 END) AS recebido_count,
                SUM(CASE WHEN UPPER(TRIM(COALESCE(pd.status_pedido, ''))) = 'AGUARDE' THEN 1 ELSE 0 END) AS aguarde_count,
                GROUP_CONCAT(DISTINCT pd.telefone SEPARATOR ',') AS telefones_concat,
                MAX(COALESCE(pd.nome, '')) AS nome,
                MAX(COALESCE(pd.endereco, '')) AS endereco,
                MAX(COALESCE(pd.nrocasa, '')) AS nrocasa,
                MAX(COALESCE(pd.complemento, '')) AS complemento,
                MAX(COALESCE(pd.entregador, '')) AS entregador,
                MAX(en.nome) AS entregador_nome,
                MAX(COALESCE(pd.formapagamento, '')) AS formapagamento,
                MAX(pd.valor_pago_troco) AS valor_pago_troco,
                MAX(UPPER(TRIM(COALESCE(pd.status_pedido, '')))) AS status_pedido,
                MAX(UPPER(TRIM(COALESCE(pd.status_comanda, 'NORMAL')))) AS status_comanda,
                MAX(COALESCE(pd.data_criacao, CURRENT_TIMESTAMP)) AS data_criacao
            FROM pedido_diarios pd
            LEFT JOIN entregador en
              ON en.id_cliente = pd.id_cliente
             AND (
                  BINARY CAST(en.chave AS CHAR) = BINARY TRIM(COALESCE(pd.entregador, ''))
                  OR en.chave = CAST(NULLIF(TRIM(pd.entregador), '') AS UNSIGNED)
                 )
            WHERE pd.id_cliente = %s
              {origem_filter_sql}
              AND UPPER(TRIM(COALESCE(pd.status_pedido, ''))) <> 'ITEM_REMOVIDO'
              {status_filter_sql}
            GROUP BY pd.origem, pd.nropedido
            ORDER BY last_id DESC
            LIMIT 250
            """,
            (id_cliente,),
        )
        rows = cur.fetchall() or []
        out = []
        for r in rows:
            aberto_count = int(r.get("aberto_count") or 0)
            rota_count = int(r.get("rota_count") or 0)
            recebido_count = int(r.get("recebido_count") or 0)
            aguarde_count = int(r.get("aguarde_count") or 0)
            status_comanda = str(r.get("status_comanda") or "NORMAL").strip().upper() or "NORMAL"
            comanda_cancelada = status_comanda == STATUS_COMANDA_CANCELADA
            orig_r = str(r.get("origem") or "").strip().upper()
            nro_r = int(r.get("nropedido") or 0)
            pode_cancelar, motivo_nao_cancelar = _comanda_pode_cancelar(cur, id_cliente, orig_r, nro_r)
            if comanda_cancelada:
                st_calc = STATUS_COMANDA_CANCELADA
            elif recebido_count > 0 and aberto_count <= 0 and rota_count <= 0 and aguarde_count <= 0:
                st_calc = "RECEBIDO"
            elif rota_count > 0 and aberto_count <= 0:
                st_calc = "ROTA"
            elif aberto_count > 0:
                st_calc = "ABERTO"
            elif aguarde_count > 0:
                st_calc = "AGUARDE"
            else:
                st_calc = str(r.get("status_pedido") or "ABERTO").strip().upper() or "ABERTO"
            out.append(
                {
                    "origem": orig_r,
                    "nropedido": nro_r,
                    "telefone": _telefone_de_concat(r.get("telefones_concat")),
                    "nome": str(r.get("nome") or "").strip(),
                    "endereco": str(r.get("endereco") or "").strip(),
                    "nrocasa": str(r.get("nrocasa") or "").strip(),
                    "complemento": str(r.get("complemento") or "").strip(),
                    "entregador": str(r.get("entregador") or "").strip(),
                    "entregador_nome": str(r.get("entregador_nome") or "").strip(),
                    "formapagamento": str(r.get("formapagamento") or "").strip(),
                    "valor_pago_troco": float(r.get("valor_pago_troco") or 0)
                    if r.get("valor_pago_troco") is not None
                    else None,
                    "status_pedido": st_calc,
                    "status_comanda": status_comanda,
                    "comanda_cancelada": comanda_cancelada,
                    "pode_cancelar_comanda": pode_cancelar,
                    "motivo_nao_cancelar": motivo_nao_cancelar,
                    "total": float(r.get("total") or 0),
                    "total_itens": float(r.get("total_itens") or 0),
                    "data_criacao": (r.get("data_criacao").isoformat() if getattr(r.get("data_criacao"), "isoformat", None) else str(r.get("data_criacao") or "")),
                }
            )
        return jsonify({"sucesso": True, "pedidos": out})
    except Exception as e:
        print("[DASH DELIVERY/BALCAO ERRO]", e, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route("/api/dashboard/pedido/<string:origem>/<int:nropedido>", methods=["GET"])
@login_required
def api_dashboard_pedido_detalhe(origem, nropedido):
    conn = None
    cur = None
    try:
        id_cliente = session.get("id_cliente")
        orig = str(origem or "").strip().upper()
        if orig not in ("DELIVERY", "BALCAO"):
            return jsonify({"sucesso": False, "erro": "Origem inválida"}), 400
        if int(nropedido or 0) <= 0:
            return jsonify({"sucesso": False, "erro": "Pedido inválido"}), 400

        conn = conectar()
        cur = conn.cursor(dictionary=True)

        cur.execute("SHOW COLUMNS FROM pedido_diarios LIKE 'baixa_pagamento'")
        has_baixa = cur.fetchone() is not None

        select_baixa = ", MAX(COALESCE(baixa_pagamento,'')) AS baixa_pagamento" if has_baixa else ", '' AS baixa_pagamento"
        cur.execute(
            f"""
            SELECT
              MAX(COALESCE(pd.telefone,'')) AS telefone,
              MAX(COALESCE(pd.nome,'')) AS nome,
              MAX(COALESCE(pd.endereco,'')) AS endereco,
              MAX(COALESCE(pd.nrocasa,'')) AS nrocasa,
              MAX(COALESCE(pd.complemento,'')) AS complemento,
              MAX(COALESCE(pd.entregador,'')) AS entregador,
              MAX(en.nome) AS entregador_nome,
              MAX(COALESCE(pd.formapagamento,'')) AS formapagamento,
              MAX(pd.valor_pago_troco) AS valor_pago_troco,
              MAX(UPPER(TRIM(COALESCE(pd.status_pedido,'')))) AS status_pedido,
              MAX(UPPER(TRIM(COALESCE(pd.status_comanda,'NORMAL')))) AS status_comanda,
              SUM(COALESCE(pd.preco,0) * COALESCE(pd.quantidade,0)) AS total
              {select_baixa}
            FROM pedido_diarios pd
            LEFT JOIN entregador en
              ON en.id_cliente = pd.id_cliente
             AND (
                  BINARY CAST(en.chave AS CHAR) = BINARY TRIM(COALESCE(pd.entregador, ''))
                  OR en.chave = CAST(NULLIF(TRIM(pd.entregador), '') AS UNSIGNED)
                 )
            WHERE pd.id_cliente = %s
              AND pd.origem = %s
              AND pd.nropedido = %s
              AND UPPER(TRIM(COALESCE(pd.status_pedido,''))) <> 'ITEM_REMOVIDO'
            """,
            (id_cliente, orig, int(nropedido)),
        )
        head = cur.fetchone() or {}
        total = float(head.get("total") or 0)
        if total <= 0:
            return jsonify({"sucesso": False, "erro": "Pedido não encontrado"}), 404

        cur.execute(
            """
            SELECT
              chave,
              produto,
              COALESCE(quantidade,0) AS quantidade,
              COALESCE(preco,0) AS preco,
              obs_item,
              dados_item
            FROM pedido_diarios
            WHERE id_cliente = %s
              AND origem = %s
              AND nropedido = %s
              AND UPPER(COALESCE(status_pedido,'')) <> 'ITEM_REMOVIDO'
            ORDER BY chave ASC
            """,
            (id_cliente, orig, int(nropedido)),
        )
        itens = cur.fetchall() or []
        status_comanda = str(head.get("status_comanda") or "NORMAL").strip().upper() or "NORMAL"
        comanda_cancelada = status_comanda == STATUS_COMANDA_CANCELADA
        pode_cancelar, motivo_nao_cancelar = _comanda_pode_cancelar(cur, id_cliente, orig, int(nropedido))
        return jsonify(
            {
                "sucesso": True,
                "pedido": {
                    "origem": orig,
                    "nropedido": int(nropedido),
                    "telefone": str(head.get("telefone") or "").strip(),
                    "nome": str(head.get("nome") or "").strip(),
                    "endereco": str(head.get("endereco") or "").strip(),
                    "nrocasa": str(head.get("nrocasa") or "").strip(),
                    "complemento": str(head.get("complemento") or "").strip(),
                    "entregador": str(head.get("entregador") or "").strip(),
                    "entregador_nome": str(head.get("entregador_nome") or "").strip(),
                    "formapagamento": str(head.get("formapagamento") or "").strip(),
                    "valor_pago_troco": float(head.get("valor_pago_troco") or 0)
                    if head.get("valor_pago_troco") is not None
                    else None,
                    "status_pedido": str(head.get("status_pedido") or "").strip().upper(),
                    "status_comanda": status_comanda,
                    "comanda_cancelada": comanda_cancelada,
                    "pode_cancelar_comanda": pode_cancelar,
                    "motivo_nao_cancelar": motivo_nao_cancelar,
                    "total": total,
                    "baixa_pagamento": str(head.get("baixa_pagamento") or "").strip(),
                },
                "itens": [convert_types(i) for i in itens],
            }
        )
    except Exception as e:
        print("[DASH PEDIDO DETALHE ERRO]", e, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route("/api/dashboard/mesa/<int:mesanro>", methods=["GET"])
@login_required
@restaurant_only
def api_dashboard_mesa_detalhe(mesanro):
    conn = None
    cur = None
    try:
        id_cliente = session.get("id_cliente")
        if int(mesanro or 0) <= 0:
            return jsonify({"sucesso": False, "erro": "Mesa inválida"}), 400

        conn = conectar()
        cur = conn.cursor(dictionary=True)

        cur.execute("SHOW COLUMNS FROM pedido_diarios LIKE 'status_mesa'")
        if cur.fetchone() is None:
            cur.execute("ALTER TABLE pedido_diarios ADD COLUMN status_mesa VARCHAR(20) NULL AFTER nropedido")
        cur.execute("SHOW COLUMNS FROM pedido_diarios LIKE 'pessoas_mesa'")
        if cur.fetchone() is None:
            cur.execute("ALTER TABLE pedido_diarios ADD COLUMN pessoas_mesa INT NULL AFTER status_mesa")
        cur.execute("SHOW COLUMNS FROM pedido_diarios LIKE 'baixa_pagamento'")
        has_baixa = cur.fetchone() is not None

        cur.execute(
            """
            SELECT
              SUM(CASE WHEN UPPER(COALESCE(status_pedido,'')) <> 'ITEM_REMOVIDO' THEN COALESCE(preco,0) * COALESCE(quantidade,0) ELSE 0 END) AS subtotal,
              MAX(UPPER(COALESCE(status_mesa,''))) AS status_mesa,
              MAX(COALESCE(pessoas_mesa, 0)) AS pessoas_mesa
            FROM pedido_diarios
            WHERE id_cliente = %s
              AND origem = 'MESA'
              AND nropedido = %s
            """,
            (id_cliente, int(mesanro)),
        )
        head = cur.fetchone() or {}
        subtotal = float(head.get("subtotal") or 0)
        if subtotal <= 0:
            return jsonify({"sucesso": False, "erro": "Mesa não encontrada"}), 404
        try:
            pessoas_mesa = int(head.get("pessoas_mesa") or 0)
        except Exception:
            pessoas_mesa = 0
        if pessoas_mesa <= 0:
            pessoas_mesa = 1

        cur.execute(
            "SELECT servicomesa FROM configuracao WHERE id_cliente = %s ORDER BY chave DESC LIMIT 1",
            (id_cliente,),
        )
        cfg = cur.fetchone() or {}
        try:
            pct = float(cfg.get("servicomesa") or 0)
        except Exception:
            pct = 0.0
        if pct < 0:
            pct = 0.0
        servico = round(float(subtotal) * (float(pct) / 100.0), 2) if pct else 0.0
        total = round(float(subtotal) + float(servico), 2)
        por_pessoa = round(float(total) / float(pessoas_mesa), 2) if pessoas_mesa > 0 else float(total)

        baixa_txt = ""
        if has_baixa:
            cur.execute(
                """
                SELECT MAX(COALESCE(baixa_pagamento,'')) AS baixa_pagamento
                FROM pedido_diarios
                WHERE id_cliente = %s AND origem = 'MESA' AND nropedido = %s
                """,
                (id_cliente, int(mesanro)),
            )
            row_b = cur.fetchone() or {}
            baixa_txt = str(row_b.get("baixa_pagamento") or "").strip()

        cur.execute(
            """
            SELECT
              chave,
              produto,
              COALESCE(quantidade,0) AS quantidade,
              COALESCE(preco,0) AS preco,
              obs_item,
              dados_item
            FROM pedido_diarios
            WHERE id_cliente = %s
              AND origem = 'MESA'
              AND nropedido = %s
              AND UPPER(COALESCE(status_pedido,'')) <> 'ITEM_REMOVIDO'
            ORDER BY chave ASC
            """,
            (id_cliente, int(mesanro)),
        )
        itens = cur.fetchall() or []
        return jsonify(
            {
                "sucesso": True,
                "mesa": {
                    "origem": "MESA",
                    "mesanro": int(mesanro),
                    "status_mesa": str(head.get("status_mesa") or "").strip().upper(),
                    "pessoas_mesa": pessoas_mesa,
                    "subtotal": subtotal,
                    "servico": servico,
                    "total": total,
                    "por_pessoa": por_pessoa,
                    "baixa_pagamento": baixa_txt,
                },
                "itens": [convert_types(i) for i in itens],
            }
        )
    except Exception as e:
        print("[DASH MESA DETALHE ERRO]", e, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route("/api/baixa/receber", methods=["POST"])
@login_required
def api_baixa_receber():
    conn = None
    cur = None
    try:
        data = request.get_json(silent=True) or {}
        nropedido = int(data.get("nropedido") or 0)
        origem = str(data.get("origem") or "").strip().upper()
        if origem not in ("DELIVERY", "BALCAO"):
            return jsonify({"sucesso": False, "erro": "Origem inválida"}), 400
        if nropedido <= 0:
            return jsonify({"sucesso": False, "erro": "nropedido inválido"}), 400
        pagamentos = data.get("pagamentos") if isinstance(data.get("pagamentos"), list) else []
        pagos = []
        soma = 0.0
        for p in pagamentos:
            if not isinstance(p, dict):
                continue
            forma = str(p.get("forma") or "").strip()
            try:
                valor = float(str(p.get("valor") or 0).replace(",", "."))
            except Exception:
                valor = 0.0
            if not forma or valor <= 0:
                continue
            valor = round(float(valor), 2)
            soma += valor
            pagos.append({"forma": forma, "valor": valor})
        if not pagos:
            return jsonify({"sucesso": False, "erro": "Informe pelo menos uma forma de pagamento com valor."}), 400

        id_cliente = session.get("id_cliente")
        conn = conectar()
        conn.start_transaction()
        cur = conn.cursor(dictionary=True)
        cur.execute("SHOW COLUMNS FROM pedido_diarios LIKE 'baixa_pagamento'")
        if cur.fetchone() is None:
            cur.execute("ALTER TABLE pedido_diarios ADD COLUMN baixa_pagamento TEXT NULL AFTER formapagamento")

        cur.execute(
            """
            SELECT
                SUM(COALESCE(preco, 0) * COALESCE(quantidade, 0)) AS total,
                SUM(CASE WHEN UPPER(TRIM(COALESCE(status_pedido, ''))) IN ('ABERTO','ABERTA') THEN 1 ELSE 0 END) AS aberto_count,
                SUM(CASE WHEN UPPER(TRIM(COALESCE(status_pedido, ''))) = 'ROTA' THEN 1 ELSE 0 END) AS rota_count,
                SUM(CASE WHEN UPPER(TRIM(COALESCE(status_pedido, ''))) = 'AGUARDE' THEN 1 ELSE 0 END) AS aguarde_count
            FROM pedido_diarios
            WHERE nropedido = %s AND id_cliente = %s AND origem = %s
              AND UPPER(TRIM(COALESCE(status_pedido, ''))) <> 'ITEM_REMOVIDO'
            """,
            (nropedido, id_cliente, origem),
        )
        row = cur.fetchone() or {}
        total = float(row.get("total") or 0)
        aberto_count = int(row.get("aberto_count") or 0)
        rota_count = int(row.get("rota_count") or 0)
        aguarde_count = int(row.get("aguarde_count") or 0)
        if total <= 0:
            conn.rollback()
            return jsonify({"sucesso": False, "erro": "Pedido não encontrado ou sem itens."}), 404
        if aberto_count <= 0 and rota_count <= 0:
            conn.rollback()
            return jsonify({"sucesso": False, "erro": "Pedido precisa estar ABERTO ou em ROTA para dar baixa."}), 409
        if aguarde_count > 0:
            conn.rollback()
            return jsonify({"sucesso": False, "erro": "Pedido ainda está em AGUARDE e não pode dar baixa."}), 409

        soma = round(float(soma), 2)
        total = round(float(total), 2)
        diff = round(total - soma, 2)
        if diff > 0.01:
            conn.rollback()
            return jsonify({"sucesso": False, "erro": "Valores não fecham com o total do pedido.", "total": total, "somado": soma, "restante": diff}), 400

        troco_pay_sum = 0.0
        troco_pay_names = []
        non_troco_sum = 0.0
        for p in pagos:
            forma_nome = str(p.get("forma") or "").strip()
            valor_pago = float(p.get("valor") or 0)
            permite_troco = _forma_pagamento_exige_troco(cur, id_cliente, forma_nome)
            if permite_troco:
                troco_pay_sum = round(float(troco_pay_sum) + float(valor_pago), 2)
                troco_pay_names.append(forma_nome)
            else:
                non_troco_sum = round(float(non_troco_sum) + float(valor_pago), 2)
                if valor_pago > (total + 0.01):
                    conn.rollback()
                    return (
                        jsonify(
                            {
                                "sucesso": False,
                                "erro": f"A forma '{forma_nome}' não permite troco e não pode receber valor maior que o total do pedido.",
                                "total": total,
                                "valor": round(float(valor_pago), 2),
                            }
                        ),
                        400,
                    )

        if (float(non_troco_sum) - float(total)) > 0.01:
            conn.rollback()
            return (
                jsonify(
                    {
                        "sucesso": False,
                        "erro": "A soma das formas sem troco não pode ultrapassar o total do pedido.",
                        "total": total,
                        "sem_troco": round(float(non_troco_sum), 2),
                    }
                ),
                400,
            )

        troco_val = round(max(0.0, float(soma) - float(total)), 2)
        if troco_val > 0.01:
            if troco_pay_sum <= 0:
                conn.rollback()
                return (
                    jsonify(
                        {
                            "sucesso": False,
                            "erro": "Nenhuma forma selecionada permite troco. Ajuste os valores para fechar o total sem excedente.",
                            "total": total,
                            "somado": soma,
                            "troco": troco_val,
                        }
                    ),
                    400,
                )
            if (troco_val - troco_pay_sum) > 0.01:
                conn.rollback()
                return (
                    jsonify(
                        {
                            "sucesso": False,
                            "erro": "O troco excede o valor pago em formas que permitem troco. Atribua o excedente a uma forma com troco.",
                            "total": total,
                            "somado": soma,
                            "troco": troco_val,
                            "formas_com_troco": troco_pay_names,
                        }
                    ),
                    400,
                )

        usuario = str(session.get("usuario_logado") or "").strip()
        troco = troco_val
        baixa_obj = {
            "v": 1,
            "nropedido": nropedido,
            "origem": origem,
            "total": total,
            "pagamentos": pagos,
            "troco": troco,
            "usuario": usuario,
            "ts": int(time.time()),
        }
        baixa_txt = json.dumps(baixa_obj, ensure_ascii=False)
        if len(pagos) == 1:
            forma_final = str(pagos[0].get("forma") or "").strip()
        else:
            forma_final = "MISTO"

        cur.execute(
            """
            UPDATE pedido_diarios
            SET status_pedido = 'RECEBIDO',
                baixa_pagamento = %s,
                formapagamento = %s
            WHERE nropedido = %s AND id_cliente = %s AND origem = %s
              AND UPPER(TRIM(COALESCE(status_pedido, ''))) <> 'ITEM_REMOVIDO'
              AND UPPER(TRIM(COALESCE(status_pedido, ''))) IN ('ABERTO','ABERTA','ROTA')
            """,
            (baixa_txt, forma_final, nropedido, id_cliente, origem),
        )
        if cur.rowcount <= 0:
            conn.rollback()
            return jsonify({"sucesso": False, "erro": "Não foi possível atualizar o pedido."}), 500
        conn.commit()
        return jsonify({"sucesso": True})
    except Exception as e:
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        print("[BAIXA RECEBER ERRO]", e, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

# LOG GLOBAL DE SESSÃO PARA DEPURAÇÃO (forçando log no stderr)
@app.before_request
def log_id_cliente_global():
    if not Config.LOG_SESSION_DEBUG:
        return
    sys.stderr.write(f"[LOG][before_request] Sessão id_cliente: {session.get('id_cliente')}\n")
    sys.stderr.flush()
    sys.stderr.write(f"[LOG][before_request] Sessão usuario_logado: {session.get('usuario_logado')}\n")
    sys.stderr.flush()

# ROTA DE PING PARA TESTE DE DISPONIBILIDADE
@app.route('/ping')
def ping():
    return 'pong', 200

# ROTA DE TESTE SIMPLES PARA DEBUG
@app.route('/rota_teste')
def rota_teste():
    return 'Rota de teste OK!'

# Endpoint para salvar forma de pagamento (deve vir após login_required)
@app.route("/api/salvar-forma-pagamento", methods=["POST"])
@login_required
def salvar_forma_pagamento():
    data = request.get_json()
    forma = data.get("forma", "").strip()
    troco_raw = str(data.get("troco", "") or "").strip().upper()
    troco = "S" if troco_raw in ("S", "SIM", "1", "Y", "TRUE") else "N"
    id_cliente = session.get("id_cliente")
    if not forma:
        return jsonify({"sucesso": False, "mensagem": "Forma de pagamento não informada"}), 400
    try:
        _ensure_formapagamento_troco_column()
        conn = conectar()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO formapagamento (forma, troco, id_cliente) VALUES (%s, %s, %s)",
            (forma, troco, id_cliente),
        )
        conn.commit()
        return jsonify({"sucesso": True, "mensagem": "Forma de pagamento adicionada com sucesso"})
    except Exception as e:
        return jsonify({"sucesso": False, "mensagem": str(e)}), 500
    finally:
        if 'cursor' in locals() and cursor: cursor.close()
        if 'conn' in locals() and conn: conn.close()


@app.route("/api/editar-forma-pagamento/<int:chave>", methods=["PUT"])
@login_required
def editar_forma_pagamento(chave):
    data = request.get_json()
    forma = str(data.get("forma", "") or "").strip()
    troco_raw = str(data.get("troco", "") or "").strip().upper()
    troco = "S" if troco_raw in ("S", "SIM", "1", "Y", "TRUE") else "N"
    id_cliente = session.get("id_cliente")
    if not forma:
        return jsonify({"sucesso": False, "mensagem": "Forma de pagamento não informada"}), 400
    try:
        _ensure_formapagamento_troco_column()
        conn = conectar()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE formapagamento
            SET forma = %s, troco = %s
            WHERE chave = %s AND id_cliente = %s
            """,
            (forma, troco, chave, id_cliente),
        )
        if cursor.rowcount <= 0:
            conn.rollback()
            return jsonify({"sucesso": False, "mensagem": "Registro não encontrado"}), 404
        conn.commit()
        return jsonify({"sucesso": True, "mensagem": "Forma de pagamento atualizada com sucesso"})
    except Exception as e:
        return jsonify({"sucesso": False, "mensagem": str(e)}), 500
    finally:
        if 'cursor' in locals() and cursor: cursor.close()
        if 'conn' in locals() and conn: conn.close()


@app.route("/api/excluir-forma-pagamento/<int:chave>", methods=["DELETE"])
@login_required
def excluir_forma_pagamento(chave):
    id_cliente = session.get("id_cliente")
    try:
        conn = conectar()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM formapagamento WHERE chave = %s AND id_cliente = %s",
            (chave, id_cliente),
        )
        if cursor.rowcount <= 0:
            conn.rollback()
            return jsonify({"sucesso": False, "mensagem": "Registro não encontrado"}), 404
        conn.commit()
        return jsonify({"sucesso": True, "mensagem": "Forma de pagamento excluída com sucesso"})
    except Exception as e:
        return jsonify({"sucesso": False, "mensagem": str(e)}), 500
    finally:
        if 'cursor' in locals() and cursor: cursor.close()
        if 'conn' in locals() and conn: conn.close()

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(R * c, 2)

def geocodificar(endereco):
    if not endereco or len(endereco.strip()) < 5:
        return None, None
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": endereco, "format": "json", "limit": 1}
    headers = {"User-Agent": "novaloja-geocoder/1.0"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=8)
        if r.status_code != 200:
            return None, None
        data = r.json()
        if not data:
            return None, None
        return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception as e:
        print("[GEOCODE ERRO]", e)
        return None, None

def distancia_osrm_km(lat_loja, lon_loja, lat_cli, lon_cli):
    try:
        base = "http://router.project-osrm.org/route/v1/driving"
        # OSRM usa ordem lon,lat
        url = f"{base}/{lon_loja},{lat_loja};{lon_cli},{lat_cli}?overview=false&alternatives=false&steps=false"
        r = requests.get(url, timeout=8, headers={"User-Agent": "novaloja-osrm/1.0"})
        if r.status_code != 200:
            return None
        data = r.json()
        if not data or data.get("code") != "Ok":
            return None
        routes = data.get("routes") or []
        if not routes:
            return None
        # distance vem em metros
        dist_m = routes[0].get("distance")
        if dist_m is None:
            return None
        return round(dist_m / 1000.0, 2)
    except Exception as e:
        print("[OSRM ERRO]", e)
        return None

def calcular_distancia_cliente(dados):
    """Calcula distância entre a loja e o cliente usando dados cadastrados"""
    # Obtém coordenadas da loja cadastradas
    id_cliente = session.get("id_cliente")
    loja = obter_dados_loja(id_cliente)
    loja_lat = loja['latitude']
    loja_lon = loja['longitude']
    
    partes = [
        dados.get("endereco", ""),
        dados.get("nrocasa", ""),
        dados.get("bairro", ""),
        dados.get("cidade", ""),
        dados.get("estado", ""),
        "Brasil"
    ]
    endereco_str = ", ".join([p for p in partes if p])
    lat_cli, lon_cli = geocodificar(endereco_str)
    if lat_cli is not None and lon_cli is not None:
        # Primeiro tenta percurso via OSRM
        dist_osrm = distancia_osrm_km(loja_lat, loja_lon, lat_cli, lon_cli)
        if dist_osrm is not None:
            return dist_osrm, lat_cli, lon_cli
        # Fallback para Haversine (linha reta)
        try:
            dist_hav = haversine_km(loja_lat, loja_lon, lat_cli, lon_cli)
            return dist_hav, lat_cli, lon_cli
        except Exception as e:
            print("[HAVERSINE ERRO]", e)
            return 0, lat_cli, lon_cli
    return 0, None, None

def calcular_taxa_entrega(distancia, id_cliente):
    """Calcula taxa de entrega baseado na distância usando tabela txentrega.
    Se distância for menor que faixa1_d, utiliza faixa1_v (taxa mínima).
    Retorna o valor da taxa ou 0.0 se erro."""
    conn = None
    cursor = None
    try:
        conn = conectar()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM txentrega WHERE chave = 1 AND id_cliente = %s", (id_cliente,))
        faixa = cursor.fetchone()
        
        if not faixa:
            print("[TAXA ENTREGA] Nenhuma faixa configurada em txentrega")
            return 0.0
        
        # Se distância for menor que faixa1_d, retorna faixa1_v
        faixa_1_d = faixa.get("faixa1_d")
        faixa_1_v = faixa.get("faixa1_v")
        
        if faixa_1_d is not None and distancia < faixa_1_d:
            taxa = float(faixa_1_v) if faixa_1_v is not None else 0.0
            print(f"[TAXA ENTREGA] Distância {distancia}km é menor que faixa1_d ({faixa_1_d}km), retornando taxa mínima: R$ {taxa}")
            return taxa
        
        # Testa cada faixa (1 a 10)
        for i in range(1, 11):
            faixa_d = faixa.get(f"faixa{i}_d")
            faixa_v = faixa.get(f"faixa{i}_v")
            
            if faixa_d is not None and distancia <= faixa_d:
                taxa = float(faixa_v) if faixa_v is not None else 0.0
                print(f"[TAXA ENTREGA] Distância {distancia}km cai na faixa {i}: R$ {taxa}")
                return taxa
        
        # Se ultrapassar todas as faixas, retorna a taxa da faixa 10
        faixa_10_v = faixa.get("faixa10_v")
        taxa_final = float(faixa_10_v) if faixa_10_v is not None else 0.0
        print(f"[TAXA ENTREGA] Distância {distancia}km ultrapassa todas as faixas: R$ {taxa_final}")
        return taxa_final
        
    except Exception as e:
        print("[TAXA ENTREGA ERRO]", e)
        return 0.0
    finally:
        try:
            if cursor:
                cursor.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass

def convert_types(row):
    """Converte tipos não-JSON (Decimal, datetime, bytes) para jsonify."""
    if not row:
        return row
    out = {}
    for k, v in row.items():
        if isinstance(v, decimal.Decimal):
            out[k] = float(v)
        elif isinstance(v, datetime):
            out[k] = v.isoformat(sep=" ", timespec="seconds")
        elif isinstance(v, date):
            out[k] = v.isoformat()
        elif isinstance(v, dt_time):
            out[k] = v.isoformat(timespec="seconds")
        elif isinstance(v, (bytes, bytearray)):
            out[k] = bytes(v).decode("utf-8", errors="replace")
        else:
            out[k] = v
    return out

# ===================== Impressão =====================

_SQL_FLAG_SIM = (
    "UPPER(TRIM(COALESCE({col},''))) IN ('S','SIM','1','Y','YES','T','TRUE')"
)


def _printer_select_sql(has_caminho):
    if has_caminho:
        return """
          CASE
            WHEN COALESCE(TRIM(caminho),'') <> '' THEN TRIM(caminho)
            ELSE TRIM(nomedaimpressora)
          END AS printer
        """
    return "TRIM(nomedaimpressora) AS printer"


def _printer_name_where(has_caminho):
    if has_caminho:
        return (
            "(COALESCE(TRIM(nomedaimpressora),'') <> '' "
            "OR COALESCE(TRIM(caminho),'') <> '')"
        )
    return "COALESCE(TRIM(nomedaimpressora),'') <> ''"


def _impressoras_has_id_cliente(cursor):
    cursor.execute("SHOW COLUMNS FROM impressoras LIKE 'id_cliente'")
    return cursor.fetchone() is not None


def _cliente_sql(cursor, id_cliente):
    if id_cliente is None:
        return "", ()
    if not _impressoras_has_id_cliente(cursor):
        return "", ()
    return " AND id_cliente = %s", (int(id_cliente),)


def _fetch_printer_row(cursor, has_caminho, flag_column=None, id_cliente=None):
    sel = _printer_select_sql(has_caminho)
    where_name = _printer_name_where(has_caminho)
    cli_sql, cli_params = _cliente_sql(cursor, id_cliente)
    if flag_column:
        flag_sql = _SQL_FLAG_SIM.format(col=flag_column)
        cursor.execute(
            f"""
            SELECT {sel}
            FROM impressoras
            WHERE {flag_sql}
              AND {where_name}{cli_sql}
            ORDER BY COALESCE(imprenro,0) DESC, id DESC
            LIMIT 1
            """,
            cli_params,
        )
    else:
        cursor.execute(
            f"""
            SELECT {sel}
            FROM impressoras
            WHERE {where_name}{cli_sql}
            ORDER BY COALESCE(imprenro,0) DESC, id ASC
            LIMIT 1
            """,
            cli_params,
        )
    row = cursor.fetchone()
    return row[0] if row and row[0] else None


def _fetch_printer_fallback(cursor, has_caminho, id_cliente=None):
    sel = _printer_select_sql(has_caminho)
    where_name = _printer_name_where(has_caminho)
    cli_sql, cli_params = _cliente_sql(cursor, id_cliente)
    for extra in ("imprenro = 1", "1=1"):
        cursor.execute(
            f"""
            SELECT {sel}
            FROM impressoras
            WHERE ({extra}) AND {where_name}{cli_sql}
            ORDER BY COALESCE(imprenro,0) DESC, id ASC
            LIMIT 1
            """,
            cli_params,
        )
        row = cursor.fetchone()
        if row and row[0]:
            return row[0]
    return None


def get_printer_from_db(purpose=None, id_cliente=None):
    """Obtém caminho ou nome da impressora conforme flags na tabela impressoras."""
    conn = None
    cursor = None
    try:
        conn = conectar()
        cursor = conn.cursor()
        cursor.execute("SHOW COLUMNS FROM impressoras LIKE 'caminho'")
        has_caminho = cursor.fetchone() is not None
        if id_cliente is None:
            try:
                from flask import session as _sess
                id_cliente = _sess.get("id_cliente")
            except Exception:
                id_cliente = None
        purpose_l = str(purpose or "").strip().lower()
        def _resolve(flag_col=None):
            p = None
            if flag_col:
                cursor.execute(f"SHOW COLUMNS FROM impressoras LIKE '{flag_col}'")
                if cursor.fetchone():
                    p = _fetch_printer_row(cursor, has_caminho, flag_col, id_cliente)
            if not p:
                p = _fetch_printer_fallback(cursor, has_caminho, id_cliente)
            if not p and id_cliente is not None:
                if flag_col:
                    p = _fetch_printer_row(cursor, has_caminho, flag_col, None)
                if not p:
                    p = _fetch_printer_fallback(cursor, has_caminho, None)
            return p

        if purpose_l in {"comanda_delivery", "delivery", "casa", "balcao", "balcão"}:
            return _resolve("comanda_delivery")
        if purpose_l in {"mesa", "conta_mesa", "conta"}:
            return _resolve("conta_mesa")
        return _fetch_printer_fallback(cursor, has_caminho, id_cliente) or _fetch_printer_fallback(
            cursor, has_caminho, None
        )
    except mysql.connector.Error as db_err:
        try:
            if getattr(db_err, "errno", None) == 1146:
                return None
        except Exception:
            pass
        print("[IMPRESSORA DB ERRO]", db_err)
        return None
    except Exception as e:
        print("[IMPRESSORA DB ERRO]", e)
        return None
    finally:
        try:
            if cursor:
                cursor.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass


def _fetch_impressora_id_row(cursor, flag_column=None, id_cliente=None):
    """Retorna id da impressora lógica conforme flags (mesma ordem de get_printer_from_db)."""
    where_name = _printer_name_where(True)
    cli_sql, cli_params = _cliente_sql(cursor, id_cliente)

    def _query(flag_col=None):
        if flag_col:
            flag_sql = _SQL_FLAG_SIM.format(col=flag_col)
            cursor.execute(
                f"""
                SELECT id
                FROM impressoras
                WHERE {flag_sql}
                  AND {where_name}{cli_sql}
                ORDER BY COALESCE(imprenro,0) DESC, id DESC
                LIMIT 1
                """,
                cli_params,
            )
        else:
            cursor.execute(
                f"""
                SELECT id
                FROM impressoras
                WHERE {where_name}{cli_sql}
                ORDER BY COALESCE(imprenro,0) DESC, id ASC
                LIMIT 1
                """,
                cli_params,
            )
        row = cursor.fetchone()
        return int(row[0]) if row and row[0] else None

    if flag_column:
        iid = _query(flag_column)
        if iid:
            return iid
    for extra in ("imprenro = 1", "1=1"):
        cursor.execute(
            f"""
            SELECT id
            FROM impressoras
            WHERE ({extra}) AND {where_name}{cli_sql}
            ORDER BY COALESCE(imprenro,0) DESC, id ASC
            LIMIT 1
            """,
            cli_params,
        )
        row = cursor.fetchone()
        if row and row[0]:
            return int(row[0])
    return None


def get_impressora_id_from_db(purpose=None, id_cliente=None):
    """Id da impressora lógica para origem/purpose."""
    conn = None
    cursor = None
    try:
        conn = conectar()
        cursor = conn.cursor()
        if id_cliente is None:
            try:
                from flask import session as _sess
                id_cliente = _sess.get("id_cliente")
            except Exception:
                id_cliente = None
        purpose_l = str(purpose or "").strip().lower()

        def _resolve(flag_col=None):
            iid = None
            if flag_col:
                iid = _fetch_impressora_id_row(cursor, flag_col, id_cliente)
            if not iid:
                iid = _fetch_impressora_id_row(cursor, None, id_cliente)
            if not iid and id_cliente is not None:
                if flag_col:
                    iid = _fetch_impressora_id_row(cursor, flag_col, None)
                if not iid:
                    iid = _fetch_impressora_id_row(cursor, None, None)
            return iid

        if purpose_l in {"comanda_delivery", "delivery", "casa", "balcao", "balcão"}:
            return _resolve("comanda_delivery")
        if purpose_l in {"mesa", "conta_mesa", "conta"}:
            return _resolve("conta_mesa")
        return _fetch_impressora_id_row(cursor, None, id_cliente) or _fetch_impressora_id_row(
            cursor, None, None
        )
    except Exception as e:
        print("[IMPRESSORA ID DB ERRO]", e, flush=True)
        return None
    finally:
        try:
            if cursor:
                cursor.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass


def _resolve_printer_path_for_terminal(id_cliente, terminal_id, purpose=None, impressora_id=None):
    """Resolve caminho_local do terminal. Bloqueia se não configurado."""
    tid = terminal_impressao_service.normalize_terminal_id(terminal_id)
    if not tid:
        return None, "terminal_id inválido."
    if not terminal_impressao_service.terminal_is_configured(id_cliente, tid):
        return None, (
            "Este terminal não está configurado. "
            "Acesse Configurações > Impressão deste terminal."
        )
    try:
        iid = int(impressora_id) if impressora_id is not None and str(impressora_id).strip() != "" else 0
    except (TypeError, ValueError):
        iid = 0
    if iid <= 0:
        iid = get_impressora_id_from_db(purpose=purpose, id_cliente=id_cliente)
    if not iid:
        return None, "Nenhuma impressora habilitada no cadastro para esta origem."
    caminho = terminal_impressao_service.get_printer_path(id_cliente, tid, iid)
    if not caminho:
        return None, (
            "Caminho local não configurado para esta impressora neste terminal. "
            "Acesse Configurações > Impressão deste terminal."
        )
    return caminho, None


def list_installed_printers():
    """Lista impressoras visíveis para o processo Python atual."""
    global win32print
    if sys.platform != "win32":
        return []
    if win32print is None:
        try:
            import win32print as _win32print
            win32print = _win32print
        except Exception:
            return []
    nomes = []
    try:
        flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
        for p in win32print.EnumPrinters(flags):
            # Retorno comum no pywin32: (flags, desc, name, comment)
            if len(p) >= 3 and p[2]:
                nomes.append(str(p[2]).strip())
        # Remove duplicados preservando ordem
        vistos = set()
        unicos = []
        for n in nomes:
            lk = n.lower()
            if lk not in vistos:
                vistos.add(lk)
                unicos.append(n)
        return unicos
    except Exception:
        return []

def send_to_printer(conteudo, printer_name=None, marca_impressora=None):
    """Envia texto RAW para impressora no Windows. Retorna (True, None) em sucesso, (False, erro) em falha."""
    global win32print
    if sys.platform != "win32":
        return False, f"Sistema atual sem suporte para impressão silenciosa: {sys.platform}"
    if win32print is None:
        try:
            import win32print as _win32print
            win32print = _win32print
        except Exception as e:
            return False, f"pywin32 não carregado: {e}"
    try:
        nome_pedido = str(printer_name or win32print.GetDefaultPrinter() or "").strip()
        if not nome_pedido:
            return False, "Nenhuma impressora disponível no Windows."
        disponiveis = list_installed_printers()
        nome = nome_pedido
        if disponiveis and nome_pedido.lower() not in {x.lower() for x in disponiveis}:
            melhor = None
            if _resolve_windows_printer:
                melhor, _m = _resolve_windows_printer(nome_pedido, disponiveis)
            if not melhor and _find_best_printer_match:
                melhor = _find_best_printer_match(nome_pedido, disponiveis)
            if not melhor:
                return False, f"Impressora não encontrada no Windows: {nome_pedido}"
            nome = melhor
        # Abre job de impressão RAW
        hPrinter = win32print.OpenPrinter(nome)
        try:
            hJob = win32print.StartDocPrinter(hPrinter, 1, ("Pedido", None, "RAW"))
            try:
                win32print.StartPagePrinter(hPrinter)
                # Garantir que conteudo seja string simples
                if isinstance(conteudo, bytes):
                    data = conteudo
                else:
                    data = str(conteudo).encode("cp1252", errors="replace")
                    # Avanço de papel padrão
                    data += b"\x1B\x64\x03"  # ESC d 3 = avança 3 linhas
                    # Comando de corte conforme marca
                    if marca_impressora:
                        marca = marca_impressora.strip().lower()
                        if "bematech" in marca or "daruma" in marca:
                            data += b"\x1B\x6D"  # ESC m = corte parcial
                        elif "epson" in marca:
                            data += b"\x1B\x69"  # ESC i = corte total
                        elif "elgin" in marca or "tanca" in marca or "diebold" in marca:
                            data += b"\x1D\x56\x00"  # GS V 0 = corte total
                        else:
                            # Padrão: corte parcial Bematech
                            data += b"\x1B\x6D"
                    else:
                        # Se não informado, usa Bematech
                        data += b"\x1B\x6D"
                win32print.WritePrinter(hPrinter, data)
                win32print.EndPagePrinter(hPrinter)
            finally:
                win32print.EndDocPrinter(hPrinter)
        finally:
            win32print.ClosePrinter(hPrinter)
        return True, None
    except Exception as e:
        return False, str(e)

def gravar_delivery_pendente(conteudo, produtos, forma_pagamento=None):
    """Grava dados do pedido na tabela pedido_diarios (origem DELIVERY), incluindo a forma de pagamento se fornecida."""
    conn = None
    cursor = None
    try:
        # Extrai dados do cliente do conteúdo
        linhas = conteudo.split('\n')
        cliente_data = {
            'telefone': '',
            'cep': '',
            'nome': '',
            'endereco': '',
            'nrocasa': '',
            'complemento': '',
            'nropedido': 0
        }
        for linha in linhas:
            if linha.startswith('Tel:'):
                cliente_data['telefone'] = linha.replace('Tel:', '').strip()
            elif linha.startswith('CEP:'):
                cliente_data['cep'] = linha.replace('CEP:', '').strip()
            elif linha.startswith('Nome:'):
                cliente_data['nome'] = linha.replace('Nome:', '').strip()
            elif linha.startswith('Compl:'):
                cliente_data['complemento'] = linha.replace('Compl:', '').strip()
            elif linha.startswith('End:'):
                end_info = linha.replace('End:', '').strip()
                partes = end_info.split(',')
                if len(partes) >= 1:
                    cliente_data['endereco'] = partes[0].strip()
                if len(partes) >= 2:
                    cliente_data['nrocasa'] = partes[1].strip()
            elif 'PEDIDO NRO:' in linha:
                nro_str = linha.replace('PEDIDO NRO:', '').strip()
                try:
                    cliente_data['nropedido'] = int(nro_str)
                except:
                    cliente_data['nropedido'] = 0
        # Se não temos telefone, não grava
        if not cliente_data['telefone']:
            print("[DELIVERY PENDENTE] Sem telefone, não gravando")
            return
        conn = conectar()
        cursor = conn.cursor(dictionary=True)
        id_cliente = session.get('id_cliente')
        # Define um lancamento único para este bloco (facilita rastreio e remoções em conjunto)
        cursor.execute(
            """
            SELECT COALESCE(MAX(lancamento), 0) AS max_lancamento
            FROM pedido_diarios
            WHERE id_cliente = %s AND nropedido = %s AND origem = 'DELIVERY'
            """,
            (id_cliente, int(cliente_data['nropedido'] or 0)),
        )
        row_max = cursor.fetchone() or {}
        lancamento_bloco = int((row_max.get("max_lancamento") or 0)) + 1
        if lancamento_bloco > 2147483647:
            lancamento_bloco = 1

        cod_usuario = None
        id_usuario_sessao = session.get("id_usuario")
        if id_usuario_sessao is not None:
            try:
                cod_usuario = int(id_usuario_sessao)
            except Exception:
                cod_usuario = None
        # Grava um registro por produto
        for prod in produtos:
            prod_nome = prod.get("nome", "")
            prod_preco = float(prod.get("preco", 0) or 0)
            prod_qtd = float(prod.get("qtd", 1) or 1)
            prod_chave = prod.get("chave", "")
            prod_classe = prod.get("classe", "")
            # Se for taxa de entrega
            if "TAXA ENTREGA" in prod_nome:
                prod_chave = "TXENTREGA"
                prod_classe = "TXENTREGA"
            _insert_pedido_diarios_from_casa(
                cursor,
                origem="DELIVERY",
                nropedido=int(cliente_data['nropedido'] or 0),
                id_cliente=id_cliente,
                telefone=cliente_data['telefone'],
                cep=cliente_data['cep'],
                nome=cliente_data['nome'],
                endereco=cliente_data['endereco'],
                nrocasa=cliente_data['nrocasa'],
                complemento=cliente_data['complemento'],
                codigoproduto=str(prod_chave or ""),
                produto=str(prod_nome or ""),
                preco=float(prod_preco or 0),
                quantidade=float(prod_qtd or 1),
                classe=str(prod_classe or ""),
                obs_item="",
                dados_item="",
                obs_geral="",
                cliente=cliente_data.get('cliente', cliente_data['nome']),
                cod_classe=None,
                cod_usuario=cod_usuario,
                status_pedido="AGUARDE",
                status_comanda="NORMAL",
                lancamento=lancamento_bloco,
                nrolancamento=None,
                formapagamento=(forma_pagamento or ""),
                entregador="",
            )
            print(f"[PEDIDO_DIARIOS] {prod_nome} (cod: {prod_chave}, classe: {prod_classe}) gravado para {cliente_data['telefone']} | Forma: {forma_pagamento}")
        conn.commit()
    except Exception as e:
        print(f"[DELIVERY PENDENTE ERRO] {e}")
        raise
    finally:
        if cursor:
            try:
                cursor.close()
            except:
                pass
        if conn:
            try:
                conn.close()
            except:
                pass


def _loja_diagnostico_texto():
    """Texto único usado em /onde-esta-o-servidor e /loja-build (pasta real do processo)."""
    _pm = os.path.join(_BASE_DIR, "templates", "painel_menu.html")
    return "\n".join(
        [
            f"APP_VERSION={get_app_version()}",
            "rotas_diagnostico=/onde-esta-o-servidor /loja-build /__loja_build",
            f"app_py={os.path.abspath(__file__)}",
            f"app_mtime={int(os.path.getmtime(os.path.abspath(__file__)))}",
            f"cwd={os.getcwd()}",
            f"BASE_DIR={_BASE_DIR}",
            f"template_folder={os.path.abspath(app.template_folder)}",
            f"painel_menu={os.path.abspath(_pm)}",
            f"existe_painel={os.path.isfile(_pm)}",
        ]
    )


def _loja_diagnostico_response():
    resp = Response(_loja_diagnostico_texto(), mimetype="text/plain; charset=utf-8")
    resp.headers["X-App-Version"] = get_app_version()
    return resp


@app.route("/onde-esta-o-servidor", methods=["GET"])
def onde_esta_o_servidor():
    """Confirma em texto plano qual app.py está a servir a porta (alinhar com a pasta que o Cursor abre)."""
    return _loja_diagnostico_response()


@app.route("/loja-build", methods=["GET"])
@app.route("/__loja_build", methods=["GET"])
def loja_build_info():
    """Diagnóstico: mesmo conteúdo que /onde-esta-o-servidor (/loja-build evita bloqueios a URLs com __)."""
    return _loja_diagnostico_response()


@app.route("/")
@login_required
def index():
    id_cliente = session.get('id_cliente')
    dados_loja = obter_dados_loja(id_cliente)
    nome_fantasia = dados_loja.get('nome', 'Minha Loja')
    _pm = os.path.join(_BASE_DIR, "templates", "painel_menu.html")
    html = render_template(
        "painel_menu.html",
        id_cliente=id_cliente,
        nome_fantasia=nome_fantasia,
        _painel_template=os.path.abspath(_pm),
    )
    resp = make_response(html)
    resp.headers["X-App-Version"] = get_app_version()
    return resp

@app.route("/logout")
def logout():
    """Desloga o usuário"""
    session.pop('usuario_logado', None)
    session.pop('id_cliente', None)
    session.pop('funcao', None)
    return redirect(url_for('auth.login_page'))

@app.route("/casa")
@login_required
def casa():
    """Página de pedidos (carrossel) / PDV balcão no modo varejo."""
    if is_retail():
        modo = str(request.args.get("modo") or "").strip().lower()
        if modo in ("delivery", "mesa"):
            return redirect(url_for("casa") + "?modo=balcao")
    id_cliente = session.get("id_cliente")
    dados_loja = obter_dados_loja(id_cliente) or {}
    nome_fantasia = dados_loja.get("nome", "Minha Loja")
    return render_template("index.html", nome_fantasia=nome_fantasia)

@app.route("/delivery-pendente-view")
@login_required
@restaurant_only
def delivery_pendente_view():
    """Página para visualizar pedidos pendentes de entrega"""
    id_cliente = session.get('id_cliente')
    dados_loja = obter_dados_loja(id_cliente)
    nome_fantasia = dados_loja.get('nome', 'Minha Loja')
    return render_template("delivery_pendente.html", id_cliente=id_cliente, nome_fantasia=nome_fantasia)

@app.route("/canceladas")
@login_required
def canceladas_view():
    """Página para visualizar pedidos cancelados"""
    id_cliente = session.get('id_cliente')
    dados_loja = obter_dados_loja(id_cliente)
    nome_fantasia = dados_loja.get('nome', 'Minha Loja')
    return render_template("canceladas.html", id_cliente=id_cliente, nome_fantasia=nome_fantasia)

@app.route("/comandas")
@login_required
@restaurant_only
def comandas_view():
    """Página para visualizar comandas fechadas"""
    id_cliente = session.get('id_cliente')
    dados_loja = obter_dados_loja(id_cliente)
    nome_fantasia = dados_loja.get('nome', 'Minha Loja')
    return render_template("comandas.html", id_cliente=id_cliente, nome_fantasia=nome_fantasia)

# ========== ENDPOINTS DE ENTREGADOR ==========

@app.route("/cadastrar-entregador")
@login_required
@restaurant_only
def cadastrar_entregador():
    """Página de cadastro de entregadores"""
    id_cliente = session.get('id_cliente')
    dados_loja = obter_dados_loja(id_cliente)
    nome_fantasia = dados_loja.get('nome', 'Minha Loja')
    return render_template("cadastrar_entregador.html", id_cliente=id_cliente, nome_fantasia=nome_fantasia)

@app.route("/api/salvar-entregador", methods=["POST"])
@login_required
@restaurant_only
def salvar_entregador():
    """Salva um novo entregador na tabela de entregadores"""
    conn = None
    cursor = None
    try:
        dados = request.json or {}
        nome = dados.get("nome", "").strip()
        telefone = dados.get("telefone", "").strip()
        endereco = dados.get("endereco", "").strip()
        
        if not nome:
            return jsonify({"sucesso": False, "erro": "Nome é obrigatório"}), 400
        
        conn = conectar()
        cursor = conn.cursor()
        
        # Insere o entregador (chave é auto_increment)
        id_cliente = session.get('id_cliente')
        cursor.execute("""
            INSERT INTO entregador (nome, telefone, endereco, id_cliente)
            VALUES (%s, %s, %s, %s)
        """, (nome, telefone, endereco, id_cliente))
        
        conn.commit()
        chave_gerada = cursor.lastrowid
        
        print(f"[ENTREGADOR CADASTRADO] {nome} (código: {chave_gerada}, telefone: {telefone})")
        return jsonify({
            "sucesso": True,
            "mensagem": f"Entregador '{nome}' cadastrado com sucesso! (Código: {chave_gerada})"
        })
    
    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        return jsonify({"sucesso": False, "erro": "Erro ao salvar entregador no banco de dados"}), 500
    
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@app.route("/api/listar-entregadores", methods=["GET"])
@login_required
@restaurant_only
def listar_entregadores():
    """Lista todos os entregadores cadastrados"""
    conn = None
    cursor = None
    try:
        conn = conectar()
        cursor = conn.cursor(dictionary=True)
        
        id_cliente = session.get('id_cliente')
        cursor.execute("""
            SELECT chave, nome, telefone, endereco
            FROM entregador
            WHERE id_cliente = %s
            ORDER BY nome
        """, (id_cliente,))
        
        entregadores = cursor.fetchall()
        
        return jsonify({
            "sucesso": True,
            "entregadores": entregadores
        })
    
    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        return jsonify({"sucesso": False, "erro": "Erro ao listar entregadores"}), 500
    
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@app.route("/api/delivery-pedidos-despacho", methods=["GET"])
@login_required
@restaurant_only
def api_delivery_pedidos_despacho():
    """Lista pedidos DELIVERY cujas linhas ativas estão todas em ABERTO (elegíveis para despacho → ROTA)."""
    id_cliente = session.get("id_cliente")
    if not id_cliente:
        return jsonify({"sucesso": False, "erro": "Sessão inválida."}), 401
    conn = None
    cur = None
    try:
        _ensure_pedido_diarios_table()
        conn = conectar()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT
                d.nropedido,
                MAX(NULLIF(TRIM(COALESCE(d.telefone, '')), '')) AS telefone,
                MAX(NULLIF(TRIM(COALESCE(d.cliente, '')), '')) AS cliente,
                MAX(NULLIF(TRIM(COALESCE(d.nome, '')), '')) AS nome,
                COALESCE(SUM(d.preco * d.quantidade), 0) AS total_valor,
                COUNT(*) AS linhas
            FROM pedido_diarios d
            WHERE d.id_cliente = %s
              AND d.origem = 'DELIVERY'
            GROUP BY d.nropedido
            HAVING SUM(CASE WHEN UPPER(COALESCE(d.status_pedido, '')) <> 'ITEM_REMOVIDO' THEN 1 ELSE 0 END) > 0
               AND SUM(
                    CASE
                      WHEN UPPER(COALESCE(d.status_pedido, '')) = 'ITEM_REMOVIDO' THEN 0
                      WHEN UPPER(COALESCE(d.status_pedido, '')) = 'ABERTO' THEN 0
                      ELSE 1
                    END
                ) = 0
            ORDER BY d.nropedido DESC
            """,
            (id_cliente,),
        )
        pedidos = cur.fetchall() or []
        for p in pedidos:
            if p.get("total_valor") is not None:
                try:
                    p["total_valor"] = float(p["total_valor"])
                except (TypeError, ValueError):
                    p["total_valor"] = 0.0
        return jsonify({"sucesso": True, "pedidos": pedidos})
    except mysql.connector.Error as e:
        print("[DELIVERY_DESPACHO LIST]", e, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route("/api/despachar-delivery", methods=["POST"])
@login_required
@restaurant_only
def api_despachar_delivery():
    """Grava código do entregador (chave) e altera status_pedido para ROTA nas linhas DELIVERY em ABERTO."""
    id_cliente = session.get("id_cliente")
    if not id_cliente:
        return jsonify({"sucesso": False, "erro": "Sessão inválida."}), 401
    body = request.get_json(silent=True) or {}
    try:
        nropedido = int(body.get("nropedido") or 0)
    except (TypeError, ValueError):
        nropedido = 0
    try:
        codigo_entregador = int(body.get("codigo_entregador") or 0)
    except (TypeError, ValueError):
        codigo_entregador = 0
    if nropedido <= 0 or codigo_entregador <= 0:
        return jsonify({"sucesso": False, "erro": "Informe nropedido e codigo_entregador válidos."}), 400

    conn = None
    cur = None
    try:
        _ensure_pedido_diarios_table()
        conn = conectar()
        conn.start_transaction()
        cur = conn.cursor(dictionary=True)

        cur.execute(
            "SELECT 1 FROM entregador WHERE chave = %s AND id_cliente = %s LIMIT 1",
            (codigo_entregador, id_cliente),
        )
        if cur.fetchone() is None:
            conn.rollback()
            return jsonify({"sucesso": False, "erro": "Entregador não encontrado para este cliente."}), 404

        cur.execute(
            """
            SELECT COUNT(*) AS bad
            FROM pedido_diarios
            WHERE id_cliente = %s
              AND origem = 'DELIVERY'
              AND nropedido = %s
              AND UPPER(COALESCE(status_pedido, '')) <> 'ITEM_REMOVIDO'
              AND UPPER(COALESCE(status_pedido, '')) <> 'ABERTO'
            """,
            (id_cliente, nropedido),
        )
        row_bad = cur.fetchone() or {}
        if int(row_bad.get("bad") or 0) > 0:
            conn.rollback()
            return jsonify(
                {
                    "sucesso": False,
                    "erro": "Pedido não está elegível (existem linhas que não estão em ABERTO).",
                }
            ), 400

        cur.execute(
            """
            SELECT COUNT(*) AS ok
            FROM pedido_diarios
            WHERE id_cliente = %s
              AND origem = 'DELIVERY'
              AND nropedido = %s
              AND UPPER(COALESCE(status_pedido, '')) = 'ABERTO'
            """,
            (id_cliente, nropedido),
        )
        row_ok = cur.fetchone() or {}
        if int(row_ok.get("ok") or 0) <= 0:
            conn.rollback()
            return jsonify({"sucesso": False, "erro": "Nenhuma linha ABERTO para este pedido."}), 400

        codigo_str = str(codigo_entregador)
        cur.execute(
            """
            UPDATE pedido_diarios
            SET entregador = %s,
                status_pedido = 'ROTA'
            WHERE id_cliente = %s
              AND origem = 'DELIVERY'
              AND nropedido = %s
              AND UPPER(COALESCE(status_pedido, '')) = 'ABERTO'
            """,
            (codigo_str, id_cliente, nropedido),
        )
        aff = cur.rowcount if hasattr(cur, "rowcount") else 0
        conn.commit()
        try:
            _notificar_despacho_whatsapp(id_cliente, nropedido, codigo_entregador)
        except Exception as _wae:
            print("[DESPACHO WHATSAPP]", _wae, flush=True)
        return jsonify(
            {
                "sucesso": True,
                "mensagem": "Pedido despachado (ROTA) e entregador atribuído.",
                "linhas_atualizadas": aff,
            }
        )
    except mysql.connector.Error as e:
        if conn:
            conn.rollback()
        print("[DESPACHAR_DELIVERY]", e, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route("/api/obter-entregador/<int:chave>", methods=["GET"])
@login_required
@restaurant_only
def obter_entregador(chave):
    """Obtém dados de um entregador específico"""
    conn = None
    cursor = None
    try:
        conn = conectar()
        cursor = conn.cursor(dictionary=True)
        
        id_cliente = session.get('id_cliente')
        cursor.execute("""
            SELECT chave, nome, telefone, endereco
            FROM entregador
            WHERE chave = %s AND id_cliente = %s
        """, (chave, id_cliente))
        
        entregador = cursor.fetchone()
        
        if entregador:
            return jsonify({
                "sucesso": True,
                "entregador": entregador
            })
        else:
            return jsonify({"sucesso": False, "erro": "Entregador não encontrado"}), 404
    
    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        return jsonify({"sucesso": False, "erro": "Erro ao obter entregador"}), 500
    
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@app.route("/api/editar-entregador/<int:chave>", methods=["PUT"])
@login_required
@restaurant_only
def editar_entregador(chave):
    """Edita um entregador existente"""
    conn = None
    cursor = None
    try:
        dados = request.json or {}
        nome = dados.get("nome", "").strip()
        telefone = dados.get("telefone", "").strip()
        endereco = dados.get("endereco", "").strip()
        
        if not nome:
            return jsonify({"sucesso": False, "erro": "Nome é obrigatório"}), 400
        
        conn = conectar()
        cursor = conn.cursor()
        
        id_cliente = session.get('id_cliente')
        cursor.execute("""
            UPDATE entregador 
            SET nome = %s, telefone = %s, endereco = %s
            WHERE chave = %s AND id_cliente = %s
        """, (nome, telefone, endereco, chave, id_cliente))
        
        conn.commit()
        
        if cursor.rowcount > 0:
            print(f"[ENTREGADOR ATUALIZADO] {nome} (código: {chave})")
            return jsonify({
                "sucesso": True,
                "mensagem": f"Entregador '{nome}' atualizado com sucesso!"
            })
        else:
            return jsonify({"sucesso": False, "erro": "Entregador não encontrado"}), 404
    
    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        return jsonify({"sucesso": False, "erro": "Erro ao editar entregador"}), 500
    
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@app.route("/api/excluir-entregador/<int:chave>", methods=["DELETE"])
@login_required
@restaurant_only
def excluir_entregador(chave):
    """Exclui um entregador"""
    conn = None
    cursor = None
    try:
        conn = conectar()
        cursor = conn.cursor(dictionary=True)
        
        # Primeiro busca o nome do entregador
        id_cliente = session.get('id_cliente')
        cursor.execute("SELECT nome FROM entregador WHERE chave = %s AND id_cliente = %s", (chave, id_cliente))
        entregador = cursor.fetchone()
        
        if not entregador:
            return jsonify({"sucesso": False, "erro": "Entregador não encontrado"}), 404
        
        # Exclui o entregador
        cursor.execute("DELETE FROM entregador WHERE chave = %s AND id_cliente = %s", (chave, id_cliente))
        conn.commit()
        
        print(f"[ENTREGADOR EXCLUÍDO] {entregador['nome']} (código: {chave})")
        return jsonify({
            "sucesso": True,
            "mensagem": f"Entregador '{entregador['nome']}' excluído com sucesso!"
        })
    
    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        return jsonify({"sucesso": False, "erro": "Erro ao excluir entregador"}), 500
    
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

# ========== ENDPOINTS DE CLASSIFICAÇÃO ==========

@app.route("/cadastrar-classificacao")
@login_required
def cadastrar_classificacao():
    """Página de cadastro de classificações"""
    id_cliente = session.get('id_cliente')
    dados_loja = obter_dados_loja(id_cliente)
    nome_fantasia = dados_loja.get('nome', 'Minha Loja')
    return render_template("cadastrar_classificacao.html", id_cliente=id_cliente, nome_fantasia=nome_fantasia)

@app.route("/api/salvar-classificacao", methods=["POST"])
@login_required
def salvar_classificacao():
    """Salva uma nova classificação"""
    conn = None
    cursor = None
    try:
        dados = request.json or {}
        nomeclassificacao = dados.get("nomeclassificacao", "").strip()
        quantidadepartes = dados.get("quantidadepartes")
        nrofoto = dados.get("nrofoto")
        formadecobrar = dados.get("formadecobrar")
        op_tamanhos = dados.get("op_tamanhos")
        op_massas = dados.get("op_massas")
        op_bordas = dados.get("op_bordas")
        op_coberturas = dados.get("op_coberturas")
        op_adicionais = dados.get("op_adicionais")
        
        if not nomeclassificacao:
            return jsonify({"sucesso": False, "mensagem": "Nome da classificação é obrigatório"}), 400
        
        conn = conectar()
        cursor = conn.cursor()
        
        id_cliente = session.get('id_cliente')
        cursor.execute("""
            INSERT INTO classificacao (nomeclassificacao, quantidadepartes, nrofoto, formadecobrar, op_tamanhos, op_massas, op_bordas, op_coberturas, op_adicionais, id_cliente)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            nomeclassificacao,
            quantidadepartes,
            nrofoto,
            (str(formadecobrar).strip().upper() if formadecobrar is not None else None),
            op_tamanhos,
            op_massas,
            op_bordas,
            op_coberturas,
            op_adicionais,
            id_cliente,
        ))
        
        conn.commit()
        chave_gerada = cursor.lastrowid
        
        print(f"[CLASSIFICAÇÃO CADASTRADA] {nomeclassificacao} (código: {chave_gerada})")
        return jsonify({
            "sucesso": True,
            "mensagem": f"Classificação '{nomeclassificacao}' cadastrada com sucesso!"
        })
    
    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        return jsonify({"sucesso": False, "mensagem": "Erro ao salvar classificação no banco de dados"}), 500
    
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@app.route("/api/listar-classificacoes", methods=["GET"])
@login_required
def listar_classificacoes():
    """Lista todas as classificações cadastradas"""
    conn = None
    cursor = None
    try:
        conn = conectar()
        cursor = conn.cursor(dictionary=True)
        id_cliente = session.get('id_cliente')
        cursor.execute("""
            SELECT chave, nomeclassificacao, quantidadepartes, nrofoto, formadecobrar,
                   op_tamanhos, op_massas, op_bordas, op_coberturas, op_adicionais
            FROM classificacao
            WHERE id_cliente = %s
            ORDER BY nomeclassificacao
        """, (id_cliente,))
        classificacoes = cursor.fetchall()
        # Para cada classificação, buscar os produtos
        for classif in classificacoes:
            cursor.execute("SELECT produto AS nome, preco FROM produtos WHERE classe = %s AND id_cliente = %s", (classif['nomeclassificacao'], id_cliente))
            produtos = cursor.fetchall()
            classif['produtos'] = produtos
        return jsonify(classificacoes)
    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        return jsonify({"sucesso": False, "mensagem": "Erro ao listar classificações"}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@app.route("/api/obter-classificacao/<int:chave>", methods=["GET"])
@login_required
def obter_classificacao(chave):
    """Obtém dados de uma classificação específica"""
    conn = None
    cursor = None
    try:
        conn = conectar()
        cursor = conn.cursor(dictionary=True)
        
        id_cliente = session.get('id_cliente')
        cursor.execute("""
            SELECT chave, nomeclassificacao, quantidadepartes, nrofoto, formadecobrar,
                   op_tamanhos, op_massas, op_bordas, op_coberturas, op_adicionais
            FROM classificacao
            WHERE chave = %s AND id_cliente = %s
        """, (chave, id_cliente))
        
        classificacao = cursor.fetchone()
        
        if classificacao:
            return jsonify(classificacao)
        else:
            return jsonify({"sucesso": False, "mensagem": "Classificação não encontrada"}), 404
    
    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        return jsonify({"sucesso": False, "mensagem": "Erro ao obter classificação"}), 500
    
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@app.route("/api/editar-classificacao/<int:chave>", methods=["PUT"])
@login_required
def editar_classificacao(chave):
    """Edita uma classificação existente"""
    conn = None
    cursor = None
    try:
        dados = request.json or {}
        nomeclassificacao = dados.get("nomeclassificacao", "").strip()
        quantidadepartes = dados.get("quantidadepartes")
        nrofoto = dados.get("nrofoto")
        formadecobrar = dados.get("formadecobrar")
        op_tamanhos = dados.get("op_tamanhos")
        op_massas = dados.get("op_massas")
        op_bordas = dados.get("op_bordas")
        op_coberturas = dados.get("op_coberturas")
        op_adicionais = dados.get("op_adicionais")
        
        if not nomeclassificacao:
            return jsonify({"sucesso": False, "mensagem": "Nome da classificação é obrigatório"}), 400
        
        conn = conectar()
        cursor = conn.cursor()
        
        id_cliente = session.get('id_cliente')
        cursor.execute("""
            UPDATE classificacao 
            SET nomeclassificacao = %s,
                quantidadepartes = %s,
                nrofoto = %s,
                formadecobrar = %s,
                op_tamanhos = %s,
                op_massas = %s,
                op_bordas = %s,
                op_coberturas = %s,
                op_adicionais = %s
            WHERE chave = %s AND id_cliente = %s
        """, (
            nomeclassificacao,
            quantidadepartes,
            nrofoto,
            (str(formadecobrar).strip().upper() if formadecobrar is not None else None),
            op_tamanhos,
            op_massas,
            op_bordas,
            op_coberturas,
            op_adicionais,
            chave,
            id_cliente,
        ))
        
        conn.commit()
        
        if cursor.rowcount > 0:
            print(f"[CLASSIFICAÇÃO ATUALIZADA] {nomeclassificacao} (código: {chave})")
            return jsonify({
                "sucesso": True,
                "mensagem": f"Classificação '{nomeclassificacao}' atualizada com sucesso!"
            })
        else:
            return jsonify({"sucesso": False, "mensagem": "Classificação não encontrada"}), 404
    
    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        return jsonify({"sucesso": False, "mensagem": "Erro ao editar classificação"}), 500
    
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@app.route("/api/excluir-classificacao/<int:chave>", methods=["DELETE"])
@login_required
def excluir_classificacao(chave):
    """Exclui uma classificação"""
    conn = None
    cursor = None
    try:
        conn = conectar()
        cursor = conn.cursor(dictionary=True)
        
        # Primeiro busca o nome da classificação
        id_cliente = session.get('id_cliente')
        cursor.execute("SELECT nomeclassificacao FROM classificacao WHERE chave = %s AND id_cliente = %s", (chave, id_cliente))
        classificacao = cursor.fetchone()
        
        if not classificacao:
            return jsonify({"sucesso": False, "mensagem": "Classificação não encontrada"}), 404
        
        # Exclui a classificação
        cursor.execute("DELETE FROM classificacao WHERE chave = %s AND id_cliente = %s", (chave, id_cliente))
        conn.commit()
        
        print(f"[CLASSIFICAÇÃO EXCLUÍDA] {classificacao['nomeclassificacao']} (código: {chave})")
        return jsonify({
            "sucesso": True,
            "mensagem": f"Classificação '{classificacao['nomeclassificacao']}' excluída com sucesso!"
        })
    
    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        return jsonify({"sucesso": False, "erro": "Erro ao excluir classificação"}), 500
    
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

# ========== ENDPOINTS DE DADOS DA LOJA ==========

@app.route("/dados-loja")
@login_required
def dados_loja():
    """Página de cadastro dos dados da loja"""
    id_cliente = session.get('id_cliente')
    dados_loja = obter_dados_loja(id_cliente)
    nome_fantasia = dados_loja.get('nome', 'Minha Loja')
    return render_template("dados_loja.html", id_cliente=id_cliente, nome_fantasia=nome_fantasia)

@app.route("/api/salvar-dados-loja", methods=["POST"])
@login_required
def salvar_dados_loja():
    """Salva os dados da loja"""
    conn = None
    cursor = None
    try:
        dados = request.json or {}
        nome = dados.get("nome", "")
        endereco = dados.get("endereco", "")
        bairro = dados.get("bairro", "")
        cidade = dados.get("cidade", "")
        cep = dados.get("cep", "")
        telefone = dados.get("telefone", "")
        cnpj = dados.get("cnpj", "")
        latitude = dados.get("latitude", "")
        longitude = dados.get("longitude", "")
        ddd = dados.get("ddd", "")

        id_cliente = session.get('id_cliente')
        if not id_cliente:
            return jsonify({"sucesso": False, "erro": "id_cliente não encontrado na sessão"}), 400

        conn = conectar()
        cursor = conn.cursor()

        # Verifica se já existe registro para este id_cliente
        cursor.execute("SELECT id_cliente FROM dadosloja WHERE id_cliente = %s", (id_cliente,))
        existe = cursor.fetchone()

        if existe:
            # Atualiza
            cursor.execute("""
                UPDATE dadosloja 
                SET nome = %s, endereco = %s, bairro = %s, cidade = %s, cep = %s, telefone = %s, cnpj = %s, latitude = %s, longitude = %s, ddd = %s
                WHERE id_cliente = %s
            """, (nome, endereco, bairro, cidade, cep, telefone, cnpj, latitude, longitude, ddd, id_cliente))
        else:
            # Insere
            cursor.execute("""
                INSERT INTO dadosloja (id_cliente, nome, endereco, bairro, cidade, cep, telefone, cnpj, latitude, longitude, ddd)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (id_cliente, nome, endereco, bairro, cidade, cep, telefone, cnpj, latitude, longitude, ddd))

            # Cria registro na tabela contadorpedido para este id_cliente, se não existir
            cursor.execute("SELECT id_cliente FROM contadorpedido WHERE id_cliente = %s", (id_cliente,))
            existe_contador = cursor.fetchone()
            if not existe_contador:
                # Cria novo registro: chave (auto increment), contador=1, id_cliente=valor do topo
                cursor.execute("INSERT INTO contadorpedido (contador, id_cliente) VALUES (1, %s)", (id_cliente,))

        conn.commit()
        return jsonify({"sucesso": True, "mensagem": "Dados da loja salvos com sucesso"})
    
    except mysql.connector.Error as e:
        print(f"[ERRO DB] {e}")
        return jsonify({"sucesso": False, "erro": str(e)}), 500
    except Exception as e:
        print(f"[ERRO] {e}")
        return jsonify({"sucesso": False, "erro": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@app.route("/api/buscar-dados-loja")
@login_required
def buscar_dados_loja():
    """Busca os dados da loja"""
    conn = None
    cursor = None
    try:
        conn = conectar()
        cursor = conn.cursor(dictionary=True)
        id_cliente = session.get("id_cliente")
        cursor.execute("SELECT * FROM dadosloja WHERE id_cliente = %s LIMIT 1", (id_cliente,))
        dados = cursor.fetchone()
        
        if dados:
            return jsonify({"sucesso": True, "dados": dados})
        else:
            return jsonify({"sucesso": True, "dados": None})
    
    except mysql.connector.Error as e:
        print(f"[ERRO DB] {e}")
        return jsonify({"sucesso": False, "erro": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

# ========== ENDPOINTS DE TAXA DE ENTREGA ==========

@app.route("/cadastrar-taxa")
@login_required
@restaurant_only
def cadastrar_taxa():
    """Página de cadastro de taxas de entrega"""
    id_cliente = session.get('id_cliente')
    dados_loja = obter_dados_loja(id_cliente)
    nome_fantasia = dados_loja.get('nome', 'Minha Loja')
    return render_template("cadastrar_taxa.html", id_cliente=id_cliente, nome_fantasia=nome_fantasia)

@app.route("/api/dados-loja-info")
@login_required
def dados_loja_info():
    """Retorna informações da loja para exibição"""
    try:
        id_cliente = session.get("id_cliente")
        dados = obter_dados_loja(id_cliente)
        return jsonify({"sucesso": True, "dados": dados})
    except Exception as e:
        print(f"[ERRO] {e}")
        return jsonify({"sucesso": False, "erro": str(e)}), 500

@app.route("/api/salvar-taxa", methods=["POST"])
@login_required
@restaurant_only
def salvar_taxa():
    """Salva ou atualiza as taxas de entrega"""
    conn = None
    cursor = None
    try:
        dados = request.json or {}
        chave = dados.get("chave", 1)
        id_cliente = session.get('id_cliente')
        
        # Monta os valores das 10 faixas
        campos = []
        valores = []
        
        for i in range(1, 11):
            faixa_d = dados.get(f"faixa{i}_d")
            faixa_v = dados.get(f"faixa{i}_v")
            
            campos.append(f"faixa{i}_d = %s")
            campos.append(f"faixa{i}_v = %s")
            valores.append(faixa_d)
            valores.append(faixa_v)
        
        conn = conectar()
        cursor = conn.cursor()
        
        # Verifica se já existe registro com chave = 1 para este id_cliente
        cursor.execute("SELECT chave FROM txentrega WHERE chave = %s AND id_cliente = %s", (chave, id_cliente))
        existe = cursor.fetchone()
        
        if existe:
            # Atualiza registro existente
            sql = f"UPDATE txentrega SET {', '.join(campos)} WHERE chave = %s AND id_cliente = %s"
            valores.append(chave)
            valores.append(id_cliente)
            cursor.execute(sql, tuple(valores))
            print(f"[TAXA ENTREGA ATUALIZADA] chave {chave}, id_cliente {id_cliente}")
        else:
            # Insere novo registro
            campos_insert = ["chave", "id_cliente"] + [f"faixa{i}_d" for i in range(1, 11)] + [f"faixa{i}_v" for i in range(1, 11)]
            placeholders = ["%s"] * len(campos_insert)
            valores_insert = [chave, id_cliente]
            
            for i in range(1, 11):
                valores_insert.append(dados.get(f"faixa{i}_d"))
            for i in range(1, 11):
                valores_insert.append(dados.get(f"faixa{i}_v"))
            
            sql = f"INSERT INTO txentrega ({', '.join(campos_insert)}) VALUES ({', '.join(placeholders)})"
            cursor.execute(sql, tuple(valores_insert))
            print(f"[TAXA ENTREGA CRIADA] chave {chave}, id_cliente {id_cliente}")
        
        conn.commit()
        
        return jsonify({
            "sucesso": True,
            "mensagem": "Taxas de entrega salvas com sucesso!"
        })
    
    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        return jsonify({"sucesso": False, "erro": str(db_err)}), 500
    
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@app.route("/api/obter-taxa", methods=["GET"])
@login_required
@restaurant_only
def obter_taxa():
    """Obtém as taxas de entrega configuradas"""
    conn = None
    cursor = None
    try:
        conn = conectar()
        cursor = conn.cursor(dictionary=True)
        id_cliente = session.get('id_cliente')
        
        cursor.execute("SELECT * FROM txentrega WHERE chave = 1 AND id_cliente = %s", (id_cliente,))
        taxa = cursor.fetchone()
        
        if taxa:
            return jsonify({"sucesso": True, "taxa": taxa})
        else:
            # Retorna estrutura vazia se não existir
            return jsonify({"sucesso": True, "taxa": None})
    
    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        return jsonify({"sucesso": False, "erro": str(db_err)}), 500
    
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@app.route("/api/buscar-taxa-padrao", methods=["GET"])
@login_required
@restaurant_only
def buscar_taxa_padrao():
    """Busca o valor da primeira faixa de entrega (taxa padrão)"""
    conn = None
    cursor = None
    try:
        conn = conectar()
        cursor = conn.cursor(dictionary=True)
        id_cliente = session.get('id_cliente')
        cursor.execute("SELECT faixa1_v FROM txentrega WHERE id_cliente = %s LIMIT 1", (id_cliente,))
        taxa = cursor.fetchone()
        
        if taxa and taxa.get('faixa1_v'):
            return jsonify({"sucesso": True, "taxa_padrao": float(taxa['faixa1_v'])})
        else:
            return jsonify({"sucesso": True, "taxa_padrao": 0})
    
    except mysql.connector.Error as e:
        print(f"[ERRO DB] {e}")
        return jsonify({"sucesso": False, "erro": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@app.route("/api/buscar-configuracao", methods=["GET"])
def buscar_configuracao():
    """Busca as configurações do sistema"""
    conn = None
    cursor = None
    try:
        conn = conectar()
        cursor = conn.cursor(dictionary=True)
        id_cliente = session.get('id_cliente')
        if not id_cliente:
            return jsonify({"sucesso": False, "erro": "Sessão inválida."}), 401
        
        cursor.execute("SELECT * FROM configuracao WHERE id_cliente = %s ORDER BY chave DESC LIMIT 1", (id_cliente,))
        config = cursor.fetchone()
        
        if config:
            return jsonify({"sucesso": True, "config": config})
        else:
            return jsonify({"sucesso": True, "config": None})
    
    except mysql.connector.Error as e:
        print(f"[ERRO DB] {e}")
        return jsonify({"sucesso": False, "erro": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def _get_table_columns(cur, table_name: str):
    cur.execute(f"SHOW COLUMNS FROM {table_name}")
    rows = cur.fetchall() or []
    cols = set()
    for r in rows:
        try:
            cols.add(str(r[0]))
        except Exception:
            pass
    return cols


@app.route("/api/configuracao-sistema", methods=["GET"])
def api_configuracao_sistema():
    conn = None
    cur = None
    try:
        id_cliente = session.get("id_cliente")
        if not id_cliente:
            return jsonify({"sucesso": False, "erro": "Sessão inválida."}), 401

        conn = conectar()
        cur = conn.cursor(dictionary=True)
        cur_plain = conn.cursor()
        cols = _get_table_columns(cur_plain, "configuracao")
        cur_plain.close()

        wanted = ["nromesa", "servicomesa", "calculodistancia"]
        available = [c for c in wanted if c in cols]

        if not available:
            return jsonify({"sucesso": False, "erro": "Tabela configuracao sem colunas compatíveis."}), 500

        sel = ", ".join(["chave"] + available)
        cur.execute(
            f"SELECT {sel} FROM configuracao WHERE id_cliente = %s ORDER BY chave DESC LIMIT 1",
            (id_cliente,),
        )
        row = cur.fetchone()

        defaults = {"nromesa": 100, "servicomesa": 0, "calculodistancia": "Sim"}
        dados = {}
        for k in available:
            if row and k in row and row[k] is not None:
                v = row[k]
                if isinstance(v, decimal.Decimal):
                    dados[k] = float(v)
                else:
                    dados[k] = v
            else:
                dados[k] = defaults.get(k)

        return jsonify({"sucesso": True, "dados": dados, "campos": available, "existe": bool(row)})
    except Exception as e:
        print("[CONFIG SISTEMA GET ERRO]", e, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route("/api/configuracao-sistema", methods=["POST"])
def api_salvar_configuracao_sistema():
    conn = None
    cur = None
    try:
        id_cliente = session.get("id_cliente")
        if not id_cliente:
            return jsonify({"sucesso": False, "erro": "Sessão inválida."}), 401

        payload = request.json or {}
        data_in = payload.get("dados") if isinstance(payload.get("dados"), dict) else payload

        conn = conectar()
        cur = conn.cursor()
        cols = _get_table_columns(cur, "configuracao")
        wanted = ["nromesa", "servicomesa", "calculodistancia"]
        allowed = [c for c in wanted if c in cols]

        if not allowed:
            return jsonify({"sucesso": False, "erro": "Tabela configuracao sem colunas compatíveis."}), 500

        updates = {}
        if "nromesa" in allowed and "nromesa" in data_in:
            try:
                updates["nromesa"] = int(float(data_in.get("nromesa")))
            except Exception:
                return jsonify({"sucesso": False, "erro": "nromesa inválido."}), 400

        if "servicomesa" in allowed and "servicomesa" in data_in:
            try:
                updates["servicomesa"] = float(data_in.get("servicomesa"))
            except Exception:
                return jsonify({"sucesso": False, "erro": "servicomesa inválido."}), 400

        if "calculodistancia" in allowed and "calculodistancia" in data_in:
            raw = str(data_in.get("calculodistancia") or "").strip().lower()
            updates["calculodistancia"] = "Sim" if raw in ("sim", "s", "1", "true", "y", "yes") else "Nao"

        if not updates:
            return jsonify({"sucesso": False, "erro": "Nenhum campo para salvar."}), 400

        cur_sel = conn.cursor(dictionary=True)
        cur_sel.execute(
            "SELECT chave FROM configuracao WHERE id_cliente = %s ORDER BY chave DESC LIMIT 1",
            (id_cliente,),
        )
        row = cur_sel.fetchone()
        cur_sel.close()

        if row and row.get("chave"):
            sets = ", ".join([f"{k} = %s" for k in updates.keys()])
            params = list(updates.values()) + [row["chave"], id_cliente]
            cur.execute(
                f"UPDATE configuracao SET {sets} WHERE chave = %s AND id_cliente = %s",
                tuple(params),
            )
        else:
            cols_ins = ["id_cliente"] + list(updates.keys())
            placeholders = ", ".join(["%s"] * len(cols_ins))
            params = [id_cliente] + list(updates.values())
            cur.execute(
                f"INSERT INTO configuracao ({', '.join(cols_ins)}) VALUES ({placeholders})",
                tuple(params),
            )

        conn.commit()
        return jsonify({"sucesso": True, "mensagem": "Configuração do sistema salva com sucesso."})
    except mysql.connector.Error as db_err:
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        print("[CONFIG SISTEMA POST ERRO]", db_err, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(db_err)}), 500
    except Exception as e:
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        print("[CONFIG SISTEMA POST ERRO]", e, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def _impressao_http_caminho(url: str, conteudo: str, copias: int, origem_tag: str):
    """Envia conteúdo ao serviço de impressão em URL (bridge)."""
    body = {"conteudo": conteudo, "texto": conteudo, "origem": origem_tag or "print", "copias": 1}
    for _i in range(max(1, int(copias or 1))):
        try:
            resp = requests.post(url.strip(), json=body, timeout=35)
        except requests.RequestException as exc:
            return False, str(exc)
        if resp.status_code >= 400:
            return False, f"HTTP {resp.status_code}: {(resp.text or '')[:400]}"
    return True, None


@app.route("/imprimir", methods=["POST"])
@login_required
def imprimir():
    """Endpoint de impressão silenciosa. Resolve nome da impressora pela ordem: parâmetro -> DB -> padrão do Windows.
    Retorna JSON com sucesso/erro e o nome da impressora utilizado.
    """
    dados = request.json or {}
    conteudo = str(dados.get("conteudo", "") or "").strip()
    printer_param = str(dados.get("printer", "") or "").strip()
    produtos = dados.get("produtos", [])
    origem = (dados.get("origem") or "").strip().lower()
    origem_fc = origem in ("fechamento_caixa", "fechamento")
    forma_pagamento = dados.get("forma_pagamento", "")
    try:
        nropedido = int(dados.get("nropedido", 0) or 0)
    except (TypeError, ValueError):
        nropedido = 0
    try:
        copias = int(dados.get("copias", 1))
    except (TypeError, ValueError):
        return jsonify({"sucesso": False, "erro": "Número de cópias inválido."}), 400
    if copias < 1 or copias > 5:
        return jsonify({"sucesso": False, "erro": "Número de cópias deve estar entre 1 e 5."}), 400
    if not conteudo:
        return jsonify({"sucesso": False, "erro": "Conteúdo de impressão vazio."}), 400
    if produtos is None:
        produtos = []
    if not isinstance(produtos, list):
        return jsonify({"sucesso": False, "erro": "Lista de produtos inválida."}), 400

    apenas_confirmar = dados.get("apenas_confirmar") in (True, 1, "1", "true", "yes")

    skip_printer_enum_check = False
    terminal_id_raw = str(dados.get("terminal_id") or "").strip()
    if terminal_id_raw:
        id_cli_imp = session.get("id_cliente")
        purpose_term = _impressora_purpose_from_origem(origem, dados)
        caminho_term, err_term = _resolve_printer_path_for_terminal(
            id_cli_imp,
            terminal_id_raw,
            purpose=purpose_term,
            impressora_id=dados.get("impressora_id"),
        )
        if err_term:
            return jsonify({"sucesso": False, "erro": err_term}), 403
        cl_term = caminho_term.lower()
        if cl_term.startswith("http://") or cl_term.startswith("https://"):
            conteudo_http = conteudo + "\n"
            ok_http, err_http = _impressao_http_caminho(caminho_term, conteudo_http, copias, origem or "print")
            if not ok_http:
                return jsonify({"sucesso": False, "erro": err_http, "printer": caminho_term}), 502
            if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json:
                return jsonify({"sucesso": True, "printer": caminho_term, "copias": copias, "via": "http_caminho"})
            return redirect(url_for("index"))
        printer_param = caminho_term
        skip_printer_enum_check = True
    impressora_id_raw = dados.get("impressora_id")
    if not terminal_id_raw and impressora_id_raw is not None and str(impressora_id_raw).strip() != "":
        try:
            iid = int(impressora_id_raw)
        except (TypeError, ValueError):
            return jsonify({"sucesso": False, "erro": "impressora_id inválido."}), 400
        conn_imp = conectar()
        cur_imp = conn_imp.cursor(dictionary=True)
        cur_imp.execute("SHOW COLUMNS FROM impressoras LIKE 'caminho'")
        has_caminho_col = cur_imp.fetchone() is not None
        if has_caminho_col:
            cur_imp.execute(
                "SELECT id, nomedaimpressora, TRIM(COALESCE(caminho,'')) AS caminho FROM impressoras WHERE id=%s LIMIT 1",
                (iid,),
            )
        else:
            cur_imp.execute(
                "SELECT id, nomedaimpressora, '' AS caminho FROM impressoras WHERE id=%s LIMIT 1",
                (iid,),
            )
        row_imp = cur_imp.fetchone()
        cur_imp.close()
        conn_imp.close()
        if not row_imp:
            return jsonify({"sucesso": False, "erro": "Impressora cadastrada não encontrada."}), 400
        caminho_v = (row_imp.get("caminho") or "").strip()
        nome_v = (row_imp.get("nomedaimpressora") or "").strip()
        if not caminho_v and not nome_v:
            return jsonify({"sucesso": False, "erro": "Cadastro da impressora sem nome e sem caminho."}), 400
        cl = caminho_v.lower()
        if cl.startswith("http://") or cl.startswith("https://"):
            conteudo_http = conteudo + "\n"
            ok_http, err_http = _impressao_http_caminho(caminho_v, conteudo_http, copias, origem or "print")
            if not ok_http:
                return jsonify({"sucesso": False, "erro": err_http, "printer": nome_v or caminho_v}), 502
            if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json:
                return jsonify({"sucesso": True, "printer": nome_v or caminho_v, "copias": copias, "via": "http_caminho"})
            return redirect(url_for("index"))
        printer_param = (caminho_v or nome_v).strip()
        skip_printer_enum_check = True

    print(f"[IMPRESSAO DEBUG] Dados recebidos:")
    print(f"  - copias (raw): {dados.get('copias')}")
    print(f"  - copias (type): {type(dados.get('copias'))}")
    print(f"  - copias (convertido): {copias}")

    # Adiciona forma de pagamento ao conteudo se existir (fluxo de pedido; não no fechamento de caixa)
    if forma_pagamento and not origem_fc:
        conteudo += f"FORMA DE PAGAMENTO: {forma_pagamento}\n"

    # Adiciona apenas 1 linha em branco para adiantar o papel
    conteudo += "\n"

    if apenas_confirmar:
        if terminal_id_raw and printer_param:
            printer_resolved = printer_param
        else:
            printer_resolved = printer_param or str(
                get_printer_from_db(purpose=_impressora_purpose_from_origem(origem, dados)) or ""
            ).strip() or "bridge-local"
        erros = []
    else:
        erros = None

    # Comando de corte será adicionado na função send_to_printer como bytes puros

    # Extrai dados do cliente do conteúdo para gravar em deliverypendente
    if not apenas_confirmar and produtos and origem != "casa" and not origem_fc:
        try:
            gravar_delivery_pendente(conteudo, produtos, forma_pagamento)
        except Exception as e:
            print(f"[DELIVERY PENDENTE ERRO] {e}")
            traceback.print_exc()
            return jsonify({"sucesso": False, "erro": "Falha ao gravar delivery pendente."}), 500

    if not apenas_confirmar:
        purpose = _impressora_purpose_from_origem(origem, dados)
        printer_db = str(get_printer_from_db(purpose=purpose) or "").strip()
        if skip_printer_enum_check and printer_param:
            printer_resolved = printer_param
        else:
            printer_resolved = printer_param or printer_db or (win32print.GetDefaultPrinter() if (sys.platform == "win32" and win32print) else None)
            if printer_param:
                disponiveis = list_installed_printers()
                if disponiveis and printer_param.lower() not in {x.lower() for x in disponiveis}:
                    melhor = _find_best_printer_match(printer_param, disponiveis)
                    if not melhor:
                        return jsonify({
                            "sucesso": False,
                            "erro": f"Impressora informada não foi encontrada: {printer_param}",
                            "impressoras_disponiveis": disponiveis,
                        }), 400
                    printer_resolved = melhor
            else:
                disponiveis = list_installed_printers()
                if disponiveis and printer_resolved and str(printer_resolved).lower() not in {x.lower() for x in disponiveis}:
                    melhor = _find_best_printer_match(printer_resolved, disponiveis)
                    if melhor:
                        printer_resolved = melhor

        # Buscar marca da impressora na configuração
        conn = conectar()
        cursor = conn.cursor(dictionary=True)
        id_cliente = session.get('id_cliente')
        cursor.execute("SELECT * FROM configuracao WHERE id_cliente = %s ORDER BY chave DESC LIMIT 1", (id_cliente,))
        config = cursor.fetchone()
        marca_impressora = None
        if config:
            nro_imp = config.get('imp_comandadelivery')
            if nro_imp:
                campo_marca = f"marca_imp{nro_imp}"
                marca_impressora = config.get(campo_marca)
        if cursor:
            cursor.close()
        if conn:
            conn.close()

        # Imprime múltiplas cópias
        print(f"[IMPRESSAO] Imprimindo {copias} cópia(s)...")
        erros = []
        for i in range(copias):
            ok, err = send_to_printer(conteudo, printer_resolved, marca_impressora)
            if not ok:
                erros.append(f"Cópia {i+1}: {err}")
                print(f"[IMPRESSAO ERRO] Cópia {i+1} falhou: {err}")
    
    if erros:
        return jsonify({"sucesso": False, "erro": "; ".join(erros), "printer": printer_resolved}), 500
    else:
        # Fluxo /casa: após impressão bem-sucedida, muda status_pedido AGUARDE -> ABERTO.
        if origem == "casa" and nropedido > 0 and not origem_fc:
            conn_status = None
            cur_status = None
            try:
                conn_status = conectar()
                cur_status = conn_status.cursor()
                id_cliente = session.get("id_cliente")
                cur_status.execute(
                    """
                    UPDATE pedido_diarios
                    SET status_pedido = 'ABERTO'
                    WHERE nropedido = %s
                      AND id_cliente = %s
                      AND origem IN ('DELIVERY','BALCAO')
                      AND UPPER(COALESCE(status_pedido, '')) = 'AGUARDE'
                    """,
                    (nropedido, id_cliente),
                )
                conn_status.commit()
            except Exception as e:
                if conn_status:
                    conn_status.rollback()
                print(f"[IMPRESSAO STATUS_PEDIDO ERRO] {e}", flush=True)
                traceback.print_exc()
            finally:
                if cur_status:
                    cur_status.close()
                if conn_status:
                    conn_status.close()

        # Se for requisição AJAX/fetch, retorna JSON normalmente
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
            resp = {"sucesso": True, "printer": printer_resolved, "copias": copias}
            if apenas_confirmar:
                resp["via"] = "confirmar"
            return jsonify(resp)
        # Se for requisição normal (form), faz redirect
        return redirect(url_for("index"))

@app.route("/testar-impressora", methods=["GET"])
def testar_impressora():
    """Envia uma linha de teste para a impressora configurada."""
    printer_param = str(request.args.get("printer", "") or "").strip()
    printer_db = str(get_printer_from_db() or "").strip()
    printer_resolved = printer_param or printer_db or (win32print.GetDefaultPrinter() if (sys.platform == "win32" and win32print) else None)
    teste = "*** TESTE DE IMPRESSÃO - NOVALOJA ***\r\n"
    ok, err = send_to_printer(teste, printer_resolved)
    if ok:
        return jsonify({"sucesso": True, "printer": printer_resolved})
    else:
        return jsonify({"sucesso": False, "erro": err, "printer": printer_resolved}), 500

@app.route("/api/impressoras-disponiveis", methods=["GET"])
def impressoras_disponiveis():
    """Retorna impressoras disponíveis para diagnóstico no frontend."""
    try:
        if not session.get("id_cliente"):
            return jsonify({"sucesso": False, "erro": "Sessão inválida."}), 401
        nomes = list_installed_printers()
        default_name = None
        if sys.platform == "win32" and win32print:
            try:
                default_name = win32print.GetDefaultPrinter()
            except Exception:
                default_name = None
        return jsonify({"sucesso": True, "impressoras": nomes, "padrao": default_name})
    except Exception as e:
        print("[IMPRESSORAS DISPONIVEIS ERRO]", e, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(e)}), 500


@app.route("/api/impressora-para-origem", methods=["GET"])
def api_impressora_para_origem():
    """Impressora habilitada: casa/delivery (comanda_delivery) ou mesa (conta_mesa)."""
    try:
        id_cli = session.get("id_cliente")
        if not id_cli:
            return jsonify({"sucesso": False, "erro": "Sessão inválida."}), 401
        origem = request.args.get("origem", "casa")
        purpose = _impressora_purpose_from_origem(origem)
        terminal_id = request.args.get("terminal_id")
        impressora_id = request.args.get("impressora_id")
        if terminal_id:
            printer, err = _resolve_printer_path_for_terminal(
                id_cli,
                terminal_id,
                purpose=purpose,
                impressora_id=impressora_id,
            )
            if err:
                return jsonify({
                    "sucesso": False,
                    "erro": err,
                    "origem": origem,
                    "purpose": purpose,
                    "terminal_id": terminal_impressao_service.normalize_terminal_id(terminal_id),
                }), 403
            return jsonify({
                "sucesso": True,
                "printer": printer,
                "origem": origem,
                "purpose": purpose,
                "terminal_id": terminal_impressao_service.normalize_terminal_id(terminal_id),
            })
        printer = str(get_printer_from_db(purpose=purpose, id_cliente=id_cli) or "").strip()
        if not printer:
            return jsonify({
                "sucesso": False,
                "erro": "Nenhuma impressora habilitada no cadastro para esta origem.",
                "origem": origem,
                "purpose": purpose,
            }), 404
        return jsonify({
            "sucesso": True,
            "printer": printer,
            "origem": origem,
            "purpose": purpose,
        })
    except Exception as e:
        print("[IMPRESSORA ORIGEM ERRO]", e, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(e)}), 500


@app.route("/api/terminal-impressoras", methods=["GET"])
@login_required
def api_terminal_impressoras_get():
    """Lista impressoras lógicas + caminhos do terminal."""
    try:
        _ensure_terminal_impressora_table()
        _ensure_impressoras_table()
        id_cli = session.get("id_cliente")
        if not id_cli:
            return jsonify({"sucesso": False, "erro": "Sessão inválida."}), 401
        terminal_id = terminal_impressao_service.normalize_terminal_id(
            request.args.get("terminal_id") or ""
        )
        if not terminal_id:
            return jsonify({"sucesso": False, "erro": "Informe terminal_id."}), 400

        cfg_map = {}
        for row in terminal_impressao_service.load_terminal_config(id_cli, terminal_id):
            cfg_map[int(row.get("impressora_id") or 0)] = str(row.get("caminho_local") or "").strip()

        conn = conectar()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute("SHOW COLUMNS FROM impressoras LIKE 'id_cliente'")
            has_id_cli = cur.fetchone() is not None
            where_cli = ""
            params = ()
            if has_id_cli:
                where_cli = " WHERE (id_cliente = %s OR id_cliente IS NULL)"
                params = (int(id_cli),)
            cur.execute(
                f"""
                SELECT id, nomedaimpressora,
                       UPPER(COALESCE(conta_mesa,'')) AS conta_mesa,
                       UPPER(COALESCE(comanda_delivery,'')) AS comanda_delivery
                FROM impressoras{where_cli}
                ORDER BY COALESCE(imprenro,0) DESC, nomedaimpressora
                """,
                params,
            )
            rows = cur.fetchall() or []
        finally:
            cur.close()
            conn.close()

        impressoras = []
        for r in rows:
            iid = int(r.get("id") or 0)
            impressoras.append({
                "impressora_id": iid,
                "nomedaimpressora": str(r.get("nomedaimpressora") or "").strip(),
                "conta_mesa": str(r.get("conta_mesa") or "").strip(),
                "comanda_delivery": str(r.get("comanda_delivery") or "").strip(),
                "caminho_local": cfg_map.get(iid, ""),
            })
        return jsonify({
            "sucesso": True,
            "terminal_id": terminal_id,
            "configurado": terminal_impressao_service.terminal_is_configured(id_cli, terminal_id),
            "impressoras": impressoras,
        })
    except Exception as e:
        print("[TERMINAL IMPRESSORAS GET ERRO]", e, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(e)}), 500


@app.route("/api/terminal-impressoras", methods=["POST"])
@login_required
def api_terminal_impressoras_post():
    """Salva caminhos locais do terminal."""
    try:
        _ensure_terminal_impressora_table()
        _ensure_impressoras_table()
        id_cli = session.get("id_cliente")
        if not id_cli:
            return jsonify({"sucesso": False, "erro": "Sessão inválida."}), 401
        body = request.get_json(silent=True) or {}
        terminal_id = terminal_impressao_service.normalize_terminal_id(body.get("terminal_id") or "")
        if not terminal_id:
            return jsonify({"sucesso": False, "erro": "Informe terminal_id."}), 400
        itens = body.get("itens") or []
        if not isinstance(itens, list):
            return jsonify({"sucesso": False, "erro": "itens deve ser uma lista."}), 400
        ok, err = terminal_impressao_service.save_terminal_config(id_cli, terminal_id, itens)
        if not ok:
            return jsonify({"sucesso": False, "erro": err or "Falha ao salvar."}), 400
        return jsonify({
            "sucesso": True,
            "mensagem": "Configuração do terminal salva.",
            "terminal_id": terminal_id,
            "configurado": terminal_impressao_service.terminal_is_configured(id_cli, terminal_id),
        })
    except Exception as e:
        print("[TERMINAL IMPRESSORAS POST ERRO]", e, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(e)}), 500


@app.route("/api/impressoras-cadastro", methods=["GET"])
def api_impressoras_cadastro():
    """Impressoras cadastradas na tabela impressoras (nome + caminho quando existir)."""
    conn = None
    cur = None
    try:
        _ensure_impressoras_table()
        id_cli_guard = session.get("id_cliente")
        if not id_cli_guard:
            return jsonify({"sucesso": False, "erro": "Sessão inválida."}), 401
        conn = conectar()
        cur = conn.cursor(dictionary=True)
        cur.execute("SHOW COLUMNS FROM impressoras LIKE 'caminho'")
        has_caminho = cur.fetchone() is not None
        cur.execute("SHOW COLUMNS FROM impressoras LIKE 'conta_mesa'")
        has_cm = cur.fetchone() is not None
        cur.execute("SHOW COLUMNS FROM impressoras LIKE 'comanda_delivery'")
        has_cd = cur.fetchone() is not None
        cur.execute("SHOW COLUMNS FROM impressoras LIKE 'feed_final_linhas'")
        has_feed = cur.fetchone() is not None
        cols = ["id", "nomedaimpressora", "COALESCE(imprenro,0) AS imprenro"]
        cols.append(
            "TRIM(COALESCE(caminho,'')) AS caminho" if has_caminho else "'' AS caminho"
        )
        cols.append(
            "UPPER(COALESCE(conta_mesa,'')) AS conta_mesa" if has_cm else "'' AS conta_mesa"
        )
        cols.append(
            "UPPER(COALESCE(comanda_delivery,'')) AS comanda_delivery"
            if has_cd
            else "'' AS comanda_delivery"
        )
        cols.append(
            "LEAST(GREATEST(COALESCE(feed_final_linhas, 6), 0), 20) AS feed_final_linhas"
            if has_feed
            else "6 AS feed_final_linhas"
        )
        id_cli = id_cli_guard
        cur.execute("SHOW COLUMNS FROM impressoras LIKE 'id_cliente'")
        has_id_cli = cur.fetchone() is not None
        where_cli = ""
        order_clause = "ORDER BY COALESCE(imprenro,0) DESC, nomedaimpressora"
        params: tuple = ()
        if has_id_cli and id_cli is not None:
            where_cli = " WHERE (id_cliente = %s OR id_cliente IS NULL)"
            params = (int(id_cli),)
            order_clause = "ORDER BY (id_cliente IS NULL) ASC, COALESCE(imprenro,0) DESC, nomedaimpressora"
        cur.execute(
            f"""
            SELECT {', '.join(cols)}
            FROM impressoras{where_cli}
            {order_clause}
            """,
            params,
        )
        rows = cur.fetchall() or []
        if rows and isinstance(rows[0], dict) and "imprenro" not in rows[0]:
            cur_chk = None
            try:
                cur_chk = conn.cursor()
                cur_chk.execute("SHOW COLUMNS FROM impressoras LIKE 'imprenro'")
                if cur_chk.fetchone() is not None:
                    ids = [int(r.get("id")) for r in rows if r.get("id") is not None]
                    if ids:
                        placeholders = ", ".join(["%s"] * len(ids))
                        cur_chk.execute(
                            f"SELECT id, imprenro FROM impressoras WHERE id IN ({placeholders})",
                            tuple(ids),
                        )
                        mapa = {int(rid): int(nro or 0) for (rid, nro) in (cur_chk.fetchall() or [])}
                        for r in rows:
                            rid = r.get("id")
                            if rid is not None:
                                r["imprenro"] = mapa.get(int(rid), 0)
            finally:
                try:
                    if cur_chk:
                        cur_chk.close()
                except Exception:
                    pass
        return jsonify({"sucesso": True, "impressoras": rows})
    except Exception as e:
        print("[IMPRESSORAS CADASTRO]", e, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def _sn_flag(value):
    raw = str(value or "").strip().upper()
    return "S" if raw in ("S", "SIM", "1", "Y", "YES", "TRUE") else "N"


@app.route("/api/impressoras-cadastro", methods=["POST"])
def api_criar_impressora_cadastro():
    conn = None
    cur = None
    try:
        _ensure_impressoras_table()
        id_cli = session.get("id_cliente")
        if not id_cli:
            return jsonify({"sucesso": False, "erro": "Sessão inválida."}), 401

        payload = request.json or {}
        nome = str(payload.get("nomedaimpressora") or "").strip()
        caminho = str(payload.get("caminho") or "").strip()
        try:
            imprenro = int(payload.get("imprenro") or 0)
        except Exception:
            return jsonify({"sucesso": False, "erro": "imprenro inválido."}), 400
        conta_mesa = _sn_flag(payload.get("conta_mesa"))
        comanda_delivery = _sn_flag(payload.get("comanda_delivery"))
        try:
            feed_final_linhas = int(payload.get("feed_final_linhas") if payload.get("feed_final_linhas") is not None else 6)
        except Exception:
            return jsonify({"sucesso": False, "erro": "feed_final_linhas inválido."}), 400
        feed_final_linhas = max(0, min(20, feed_final_linhas))

        conn = conectar()
        cur = conn.cursor()
        cur.execute("SHOW COLUMNS FROM impressoras LIKE 'id_cliente'")
        has_id_cli = cur.fetchone() is not None
        cur.execute("SHOW COLUMNS FROM impressoras LIKE 'caminho'")
        has_caminho = cur.fetchone() is not None
        cur.execute("SHOW COLUMNS FROM impressoras LIKE 'conta_mesa'")
        has_cm = cur.fetchone() is not None
        cur.execute("SHOW COLUMNS FROM impressoras LIKE 'comanda_delivery'")
        has_cd = cur.fetchone() is not None
        cur.execute("SHOW COLUMNS FROM impressoras LIKE 'feed_final_linhas'")
        has_feed = cur.fetchone() is not None

        if has_caminho and not caminho:
            return jsonify({"sucesso": False, "erro": "Informe o caminho (nome do Windows) da impressora."}), 400

        if not nome:
            nome = caminho or "IMPRESSORA"

        cols = ["nomedaimpressora", "imprenro"]
        vals = [nome, imprenro]
        if has_caminho:
            cols.append("caminho")
            vals.append(caminho)
        if has_cm:
            cols.append("conta_mesa")
            vals.append(conta_mesa)
        if has_cd:
            cols.append("comanda_delivery")
            vals.append(comanda_delivery)
        if has_feed:
            cols.append("feed_final_linhas")
            vals.append(feed_final_linhas)
        if has_id_cli:
            cols.append("id_cliente")
            vals.append(int(id_cli))

        cur.execute(
            f"INSERT INTO impressoras ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
            tuple(vals),
        )
        new_id = cur.lastrowid

        if has_id_cli:
            where_cli = "id_cliente = %s AND id <> %s"
            params_cli = (int(id_cli), int(new_id))
        else:
            where_cli = "id <> %s"
            params_cli = (int(new_id),)

        if has_cm and conta_mesa == "S":
            cur.execute(f"UPDATE impressoras SET conta_mesa = 'N' WHERE {where_cli}", params_cli)

        conn.commit()
        return jsonify({"sucesso": True, "mensagem": "Impressora cadastrada com sucesso.", "id": new_id})
    except Exception as e:
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        print("[IMPRESSORAS CADASTRO POST ERRO]", e, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route("/api/impressoras-cadastro/<int:pid>", methods=["PUT"])
def api_editar_impressora_cadastro(pid: int):
    conn = None
    cur = None
    try:
        _ensure_impressoras_table()
        id_cli = session.get("id_cliente")
        if not id_cli:
            return jsonify({"sucesso": False, "erro": "Sessão inválida."}), 401

        payload = request.json or {}
        nome = str(payload.get("nomedaimpressora") or "").strip()
        caminho = str(payload.get("caminho") or "").strip()
        try:
            imprenro = int(payload.get("imprenro") or 0)
        except Exception:
            return jsonify({"sucesso": False, "erro": "imprenro inválido."}), 400
        conta_mesa = _sn_flag(payload.get("conta_mesa"))
        comanda_delivery = _sn_flag(payload.get("comanda_delivery"))
        try:
            feed_final_linhas = int(payload.get("feed_final_linhas") if payload.get("feed_final_linhas") is not None else 6)
        except Exception:
            return jsonify({"sucesso": False, "erro": "feed_final_linhas inválido."}), 400
        feed_final_linhas = max(0, min(20, feed_final_linhas))

        conn = conectar()
        cur = conn.cursor()
        cur.execute("SHOW COLUMNS FROM impressoras LIKE 'id_cliente'")
        has_id_cli = cur.fetchone() is not None
        cur.execute("SHOW COLUMNS FROM impressoras LIKE 'caminho'")
        has_caminho = cur.fetchone() is not None
        cur.execute("SHOW COLUMNS FROM impressoras LIKE 'conta_mesa'")
        has_cm = cur.fetchone() is not None
        cur.execute("SHOW COLUMNS FROM impressoras LIKE 'comanda_delivery'")
        has_cd = cur.fetchone() is not None
        cur.execute("SHOW COLUMNS FROM impressoras LIKE 'feed_final_linhas'")
        has_feed = cur.fetchone() is not None

        if has_caminho and not caminho:
            return jsonify({"sucesso": False, "erro": "Informe o caminho (nome do Windows) da impressora."}), 400

        if not nome:
            nome = caminho or "IMPRESSORA"

        where = "id = %s"
        params_where = [int(pid)]
        if has_id_cli:
            where += " AND id_cliente = %s"
            params_where.append(int(id_cli))

        sets = ["nomedaimpressora = %s", "imprenro = %s"]
        params = [nome, imprenro]
        if has_caminho:
            sets.append("caminho = %s")
            params.append(caminho)
        if has_cm:
            sets.append("conta_mesa = %s")
            params.append(conta_mesa)
        if has_cd:
            sets.append("comanda_delivery = %s")
            params.append(comanda_delivery)
        if has_feed:
            sets.append("feed_final_linhas = %s")
            params.append(feed_final_linhas)
        if has_id_cli:
            sets.append("id_cliente = %s")
            params.append(int(id_cli))

        cur.execute(f"UPDATE impressoras SET {', '.join(sets)} WHERE {where}", tuple(params + params_where))
        if cur.rowcount == 0:
            return jsonify({"sucesso": False, "erro": "Impressora não encontrada."}), 404

        if has_id_cli:
            where_cli = "id_cliente = %s AND id <> %s"
            params_cli = (int(id_cli), int(pid))
        else:
            where_cli = "id <> %s"
            params_cli = (int(pid),)

        if has_cm and conta_mesa == "S":
            cur.execute(f"UPDATE impressoras SET conta_mesa = 'N' WHERE {where_cli}", params_cli)

        conn.commit()
        return jsonify({"sucesso": True, "mensagem": "Impressora atualizada com sucesso."})
    except Exception as e:
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        print("[IMPRESSORAS CADASTRO PUT ERRO]", e, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route("/api/impressoras-cadastro/<int:pid>", methods=["DELETE"])
def api_excluir_impressora_cadastro(pid: int):
    conn = None
    cur = None
    try:
        _ensure_impressoras_table()
        id_cli = session.get("id_cliente")
        if not id_cli:
            return jsonify({"sucesso": False, "erro": "Sessão inválida."}), 401

        conn = conectar()
        cur = conn.cursor()
        cur.execute("SHOW COLUMNS FROM impressoras LIKE 'id_cliente'")
        has_id_cli = cur.fetchone() is not None

        if has_id_cli:
            cur.execute("DELETE FROM impressoras WHERE id = %s AND id_cliente = %s", (int(pid), int(id_cli)))
        else:
            cur.execute("DELETE FROM impressoras WHERE id = %s", (int(pid),))
        if cur.rowcount == 0:
            return jsonify({"sucesso": False, "erro": "Impressora não encontrada."}), 404
        conn.commit()
        return jsonify({"sucesso": True, "mensagem": "Impressora removida com sucesso."})
    except Exception as e:
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        print("[IMPRESSORAS CADASTRO DELETE ERRO]", e, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route("/api/salvar-impressoras-origem", methods=["POST"])
@login_required
def api_salvar_impressoras_origem():
    conn = None
    cur = None
    try:
        _ensure_impressoras_table()
        id_cli = session.get("id_cliente")
        if not id_cli:
            return jsonify({"sucesso": False, "erro": "Sessão inválida."}), 401

        payload = request.json or {}
        mesa_name = str(payload.get("mesa") or "").strip()
        delivery_name = str(payload.get("delivery") or "").strip()

        conn = conectar()
        cur = conn.cursor()

        cur.execute("SHOW COLUMNS FROM impressoras LIKE 'id_cliente'")
        has_id_cli = cur.fetchone() is not None

        def _where_cli():
            if has_id_cli:
                return " WHERE id_cliente = %s", (int(id_cli),)
            return "", ()

        def _clear_flag(flag_col: str):
            where, params = _where_cli()
            cur.execute(f"SHOW COLUMNS FROM impressoras LIKE '{flag_col}'")
            if not cur.fetchone():
                return
            cur.execute(f"UPDATE impressoras SET {flag_col} = 'N'{where}", params)

        def _set_flag(flag_col: str, printer_name: str):
            if not printer_name:
                _clear_flag(flag_col)
                return
            _clear_flag(flag_col)

            where_cli = ""
            params = [printer_name]
            if has_id_cli:
                where_cli = " AND id_cliente = %s"
                params.append(int(id_cli))

            cur.execute(
                f"SELECT id FROM impressoras WHERE TRIM(nomedaimpressora) = TRIM(%s){where_cli} LIMIT 1",
                tuple(params),
            )
            row = cur.fetchone()
            if row and row[0]:
                upd_params = []
                set_bits = [f"{flag_col} = 'S'"]
                if has_id_cli:
                    set_bits.append("id_cliente = %s")
                    upd_params.append(int(id_cli))
                upd_params.append(int(row[0]))
                cur.execute(
                    f"UPDATE impressoras SET {', '.join(set_bits)} WHERE id = %s",
                    tuple(upd_params),
                )
                return

            cols = ["nomedaimpressora", flag_col]
            vals = [printer_name, "S"]
            if has_id_cli:
                cols.append("id_cliente")
                vals.append(int(id_cli))
            cur.execute(
                f"INSERT INTO impressoras ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
                tuple(vals),
            )

        _set_flag("conta_mesa", mesa_name)
        _set_flag("comanda_delivery", delivery_name)
        conn.commit()
        return jsonify({"sucesso": True, "mensagem": "Impressoras salvas com sucesso."})
    except Exception as e:
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        print("[IMPRESSORAS SALVAR ORIGEM ERRO]", e, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route("/preparar-impressao", methods=["POST"])
@login_required
def preparar_impressao():
    """Prepara o pedido para impressão e grava em deliverypendente"""
    try:
        dados = request.json or {}
        conteudo = dados.get("conteudo", "")
        produtos = dados.get("produtos", [])
        
        if not conteudo:
            return jsonify({"sucesso": False, "erro": "Conteúdo vazio"}), 400
        
        # Armazena o conteúdo na sessão para exibição posterior
        session['pedido_impressao'] = conteudo
        
        # Extrai dados do cliente do conteúdo para gravar em deliverypendente
        if produtos:
            try:
                gravar_delivery_pendente(conteudo, produtos)
            except Exception as e:
                print(f"[DELIVERY PENDENTE ERRO] {e}")
                traceback.print_exc()
        
        return jsonify({"sucesso": True})
        
    except Exception as e:
        print("[PREPARAR IMPRESSÃO ERRO]", e)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(e)}), 500

@app.route("/visualizar-pedido")
@login_required
def visualizar_pedido():
    """Exibe página HTML com o pedido formatado e botão de impressão"""
    conteudo = session.get('pedido_impressao', '')
    if not conteudo:
        conteudo = "Nenhum pedido disponível para visualização."
    id_cliente = session.get('id_cliente')
    dados_loja = obter_dados_loja(id_cliente)
    nome_fantasia = dados_loja.get('nome', 'Minha Loja')
    return render_template("visualizar_pedido.html", conteudo=conteudo, id_cliente=id_cliente, nome_fantasia=nome_fantasia)

@app.route("/gerar-pdf", methods=["POST"])
@login_required
def gerar_pdf():
    """Gera PDF do pedido e salva em c:\\novaloja1\\pedidos\\. Retorna o caminho relativo para download."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        from reportlab.lib.units import mm
        import os
        from datetime import datetime
        
        dados = request.json or {}
        conteudo = str(dados.get("conteudo", "") or "").strip()
        produtos = dados.get("produtos", [])
        if produtos is None:
            produtos = []
        if not isinstance(produtos, list):
            return jsonify({"sucesso": False, "erro": "Lista de produtos inválida"}), 400
        
        if not conteudo:
            return jsonify({"sucesso": False, "erro": "Conteúdo vazio"}), 400
        
        # Extrai dados do cliente do conteúdo para gravar em deliverypendente
        if produtos:
            try:
                gravar_delivery_pendente(conteudo, produtos)
            except Exception as e:
                print(f"[DELIVERY PENDENTE ERRO] {e}")
                traceback.print_exc()
        
        # Nome do arquivo com timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        nome_arquivo = f"pedido_{timestamp}.pdf"
        caminho_completo = os.path.join("c:\\novaloja1\\pedidos", nome_arquivo)
        
        # Criar PDF
        c = canvas.Canvas(caminho_completo, pagesize=A4)
        largura, altura = A4
        
        # Fonte monoespaçada para manter formatação
        c.setFont("Courier", 10)
        
        # Processar linhas
        linhas = conteudo.split('\n')
        y = altura - 40  # Margem superior
        for linha in linhas:
            if y < 40:  # Nova página se acabar espaço
                c.showPage()
                c.setFont("Courier", 10)
                y = altura - 40
            c.drawString(40, y, linha)
            y -= 14  # Espaçamento entre linhas
        
        c.save()
        
        # Retorna caminho relativo para servir via Flask
        return jsonify({
            "sucesso": True, 
            "arquivo": f"/pedidos/{nome_arquivo}",
            "caminho_completo": caminho_completo
        })
        
    except Exception as e:
        print("[GERAR PDF ERRO]", e)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(e)}), 500

@app.route("/carrossel-imagens")
@login_required
def carrossel_imagens():
    conn = None
    cursor = None
    try:
        conn = conectar()
        cursor = conn.cursor(dictionary=True)
        id_cliente = session.get('id_cliente')
        cursor.execute("SELECT chave, nomeclassificacao, quantidadepartes, nrofoto AS nro_da_foto FROM classificacao WHERE id_cliente = %s", (id_cliente,))
        linhas = cursor.fetchall() or []

        imagens = []
        for row in linhas:
            classe = row.get("chave")
            nomeclassificacao = row.get("nomeclassificacao")
            nro = row.get("nro_da_foto")
            if nro is None:
                continue
            #arquivo = f"/home/novaloja2001/static/img/{int(nro)}.jpeg"
            arquivo = f"/static/img/{int(nro)}.jpeg"
            imagens.append({
                "arquivo": arquivo,
                "classe": str(classe) if classe is not None else "",
                "nome": nomeclassificacao or "",
                "max": int(row.get("quantidadepartes") or 0)
            })

        print("[CARROSSEL] imagens montadas:")
        try:
            pprint(imagens)
        except Exception:
            pass
        return jsonify(imagens)
    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        traceback.print_exc()
        return jsonify({"erro": "Erro de banco de dados", "detalhes": str(db_err)}), 500
    except Exception as e:
        print("[ERROR]", e)
        traceback.print_exc()
        return jsonify({"erro": "Erro interno no servidor", "detalhes": str(e)}), 500
    finally:
        try:
            if cursor:
                cursor.close()
        except Exception as e:
            print("[WARN] falha ao fechar cursor:", e)
        try:
            if conn:
                conn.close()
        except Exception as e:
            print("[WARN] falha ao fechar conexÃ£o:", e)
def _produtos_filtrar_legacy():
    """Retorna produtos onde produtos.classe = nomeclassificacao recebido em 'nome'."""
    nome = request.args.get("nome")
    conn = None
    cursor = None
    try:
        if not nome:
            return jsonify([])

        conn = conectar()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT produto, preco, classe FROM produtos WHERE classe = %s", (nome,))
        resultados = cursor.fetchall() or []

        resultados = [convert_types(r) for r in resultados]
        return jsonify(resultados)

    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        traceback.print_exc()
        return jsonify({"erro": "Erro de banco de dados", "detalhes": str(db_err)}), 500

    except Exception as e:
        print("[ERROR]", e)
        traceback.print_exc()
        return jsonify({"erro": "Erro interno no servidor", "detalhes": str(e)}), 500

    finally:
        try:
            if cursor:
                cursor.close()
        except Exception as e:
            print("[WARN] falha ao fechar cursor:", e)
        try:
            if conn:
                conn.close()
        except Exception as e:
            print("[WARN] falha ao fechar conexÃ£o:", e)

@app.route("/produtos-filtrar")
@login_required
def produtos_filtrar():
    """Retorna produtos onde produtos.classe = nomeclassificacao recebido em 'nome'."""
    nome = request.args.get("nome")
    conn = None
    cursor = None
    try:
        if not nome:
            return jsonify([])

        conn = conectar()
        cursor = conn.cursor(dictionary=True)
        id_cliente = session.get('id_cliente')
        cursor.execute("SELECT produto, preco, classe, chave FROM produtos WHERE classe = %s AND id_cliente = %s", (nome, id_cliente))
        resultados = cursor.fetchall() or []

        resultados = [convert_types(r) for r in resultados]
        return jsonify(resultados)

    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        traceback.print_exc()
        return jsonify({"erro": "Erro de banco de dados", "detalhes": str(db_err)}), 500

    except Exception as e:
        print("[ERROR]", e)
        traceback.print_exc()
        return jsonify({"erro": "Erro interno no servidor", "detalhes": str(e)}), 500

    finally:
        try:
            if cursor:
                cursor.close()
        except Exception as e:
            print("[WARN] falha ao fechar cursor:", e)
        try:
            if conn:
                conn.close()
        except Exception as e:
            print("[WARN] falha ao fechar conexÃ£o:", e)

@app.route("/produto/<classe>")
def produto(classe):
    conn = None
    cursor = None
    try:
        conn = conectar()
        cursor = conn.cursor(dictionary=True)

        # Debug log no servidor
        print(f"[DEBUG] Consulta produto pela classe: {classe}")
        id_cliente = session.get('id_cliente')
        cursor.execute("SELECT * FROM produtos WHERE classe = %s AND id_cliente = %s", (classe, id_cliente))
        
        resultado = cursor.fetchone()
        cursor.fetchall()  # Limpa qualquer resultado pendente
        pprint(resultado)
        resultado = convert_types(resultado)
       

        if resultado:
            
            return jsonify(resultado)  # 200
        else:
            return jsonify({"erro": "Produto nÃ£o encontrado", "classe": classe}), 404

    except mysql.connector.Error as db_err:
        # log detalhado no servidor
        print("[DB ERROR]", db_err)
        traceback.print_exc()
        return jsonify({"erro": "Erro de banco de dados", "detalhes": str(db_err)}), 500

    except Exception as e:
        print("[ERROR]", e)
        traceback.print_exc()
        return jsonify({"erro": "Erro interno no servidor", "detalhes": str(e)}), 500

    finally:
        # Fecha cursor/conn apenas se existirem
        try:
            if cursor:
                cursor.close()
        except Exception as e:
            print("[WARN] falha ao fechar cursor:", e)

        try:
            if conn:
                conn.close()
        except Exception as e:
            print("[WARN] falha ao fechar conexÃ£o:", e)


@app.route("/buscar-cliente")
@login_required
def buscar_cliente():
    telefone = request.args.get("telefone")
    conn = None
    cursor = None
    try:
        if not telefone:
            return jsonify({"erro": "Telefone não fornecido"}), 400

        conn = conectar()
        cursor = conn.cursor(dictionary=True)
        id_cliente = session.get('id_cliente')
        tel_digits = "".join(ch for ch in str(telefone) if ch.isdigit())
        cursor.execute("SELECT * FROM clientes WHERE id_cliente = %s ORDER BY chave DESC LIMIT 1500", (id_cliente,))
        rows = cursor.fetchall() or []
        resultado = None
        for row in rows:
            db_tel = "".join(ch for ch in str(row.get("telefone") or "") if ch.isdigit())
            if not db_tel:
                continue
            if db_tel == tel_digits or db_tel.endswith(tel_digits) or tel_digits.endswith(db_tel):
                resultado = row
                break

        if resultado:
            resultado = convert_types(resultado)
            return jsonify(resultado)
        else:
            return jsonify({"erro": "Cliente não encontrado"}), 404

    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        traceback.print_exc()
        return jsonify({"erro": "Erro de banco de dados", "detalhes": str(db_err)}), 500

    except Exception as e:
        print("[ERROR]", e)
        traceback.print_exc()
        return jsonify({"erro": "Erro interno no servidor", "detalhes": str(e)}), 500

    finally:
        try:
            if cursor:
                cursor.close()
        except Exception as e:
            print("[WARN] falha ao fechar cursor:", e)
        try:
            if conn:
                conn.close()
        except Exception as e:
            print("[WARN] falha ao fechar conexão:", e)

@app.route("/forma-cobrar")
@login_required
def forma_cobrar():
    nome = request.args.get("nome", "")
    conn = None
    cursor = None
    try:
        conn = conectar()
        cursor = conn.cursor(dictionary=True)
        id_cliente = session.get('id_cliente')
        cursor.execute(
            "SELECT formadecobrar FROM classificacao WHERE nomeclassificacao = %s AND id_cliente = %s",
            (nome, id_cliente),
        )
        resultado = cursor.fetchone()
        cursor.fetchall()
        
        if resultado and resultado.get("formadecobrar"):
            forma = str(resultado["formadecobrar"]).lower().strip()
            return jsonify({"forma": forma})
        else:
            return jsonify({"forma": "normal"})
    
    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        traceback.print_exc()
        return jsonify({"erro": "Erro de banco de dados", "detalhes": str(db_err)}), 500
    
    except Exception as e:
        print("[ERROR]", e)
        traceback.print_exc()
        return jsonify({"erro": "Erro interno no servidor", "detalhes": str(e)}), 500
    
    finally:
        try:
            if cursor:
                cursor.close()
        except Exception as e:
            print("[WARN] falha ao fechar cursor:", e)
        try:
            if conn:
                conn.close()
        except Exception as e:
            print("[WARN] falha ao fechar conexão:", e)

@app.route("/proximo-pedido", methods=["GET"])
@login_required
def proximo_pedido():
    conn = None
    cursor = None
    try:
        conn = conectar()
        cursor = conn.cursor(dictionary=True)
        
        id_cliente = session.get('id_cliente')
        if not id_cliente:
            return jsonify({"erro": "id_cliente não encontrado na sessão"}), 400

        # Verifica se existe registro para este id_cliente
        cursor.execute("SELECT contador FROM contadorpedido WHERE id_cliente = %s", (id_cliente,))
        resultado = cursor.fetchone()

        if resultado:
            # Incrementa o contador existente
            novo_numero = resultado["contador"] + 1
            cursor.execute("UPDATE contadorpedido SET contador = %s WHERE id_cliente = %s", (novo_numero, id_cliente))
            numero = novo_numero
        else:
            # Cria o registro inicial para este id_cliente
            cursor.execute("INSERT INTO contadorpedido (contador, id_cliente) VALUES (1, %s)", (id_cliente,))
            numero = 1

        conn.commit()
        return jsonify({"numero": numero})
    
    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        traceback.print_exc()
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        return jsonify({"erro": "Erro de banco de dados", "detalhes": str(db_err)}), 500

    except Exception as e:
        print("[ERROR]", e)
        traceback.print_exc()
        return jsonify({"erro": "Erro interno no servidor", "detalhes": str(e)}), 500

    finally:
        try:
            if cursor:
                cursor.close()
        except Exception as e:
            print("[WARN] falha ao fechar cursor:", e)
        try:
            if conn:
                conn.close()
        except Exception as e:
            print("[WARN] falha ao fechar conexão:", e)

@app.route("/numero-pedido-atual", methods=["GET"])
@login_required
def numero_pedido_atual():
    """Retorna o próximo número de pedido SEM incrementar o contador"""
    conn = None
    cursor = None
    try:
        conn = conectar()
        cursor = conn.cursor(dictionary=True)
        
        id_cliente = session.get('id_cliente')
        if not id_cliente:
            return jsonify({"erro": "id_cliente não encontrado na sessão"}), 400

        # Verifica se existe registro para este id_cliente
        cursor.execute("SELECT contador FROM contadorpedido WHERE id_cliente = %s", (id_cliente,))
        resultado = cursor.fetchone()

        if resultado:
            # Retorna o próximo número (atual + 1) mas SEM incrementar no banco
            numero = resultado["contador"] + 1
        else:
            # Se não existe, o próximo será 1
            numero = 1

        return jsonify({"numero": numero})
    
    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        traceback.print_exc()
        if conn:
            conn.rollback()
        return jsonify({"erro": "Erro de banco de dados", "detalhes": str(db_err)}), 500
    
    except Exception as e:
        print("[ERROR]", e)
        traceback.print_exc()
        return jsonify({"erro": "Erro interno no servidor", "detalhes": str(e)}), 500
    
    finally:
        try:
            if cursor:
                cursor.close()
        except Exception as e:
            print("[WARN] falha ao fechar cursor:", e)
        try:
            if conn:
                conn.close()
        except Exception as e:
            print("[WARN] falha ao fechar conexão:", e)



@app.route("/delivery-pendente", methods=["GET"])
@restaurant_only
def listar_delivery_pendente():
    """Lista todos os registros pendentes de entrega, agrupados por nropedido"""
    conn = None
    cursor = None
    try:
        conn = conectar()
        cursor = conn.cursor(dictionary=True)
        
        # Busca registros agrupados por pedido (fonte principal: pedido_diarios)
        cursor.execute("""
            SELECT 
                MIN(COALESCE(nrolancamento, chave)) as chave,
                nropedido,
                telefone,
                cep,
                nome,
                endereco,
                nrocasa,
                complemento,
                MAX(entregador) as entregador,
                SUM(CAST(preco AS DECIMAL(10,2)) * CAST(quantidade AS DECIMAL(10,3))) as total_preco,
                COUNT(*) as total_produtos
            FROM pedido_diarios
            WHERE id_cliente = %s
              AND origem = 'DELIVERY'
              AND UPPER(COALESCE(status_pedido, '')) = 'AGUARDE'
              AND UPPER(COALESCE(status_pedido, '')) <> 'ITEM_REMOVIDO'
            GROUP BY nropedido, telefone, cep, nome, endereco, nrocasa, complemento
            ORDER BY MIN(chave) DESC
        """, (session.get('id_cliente'),))
        
        registros = cursor.fetchall() or []
        registros = [convert_types(r) for r in registros]
        
        return jsonify({
            "sucesso": True,
            "total": len(registros),
            "registros": registros
        })
    
    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        traceback.print_exc()
        return jsonify({"erro": "Erro de banco de dados", "detalhes": str(db_err)}), 500
    
    except Exception as e:
        print("[ERROR]", e)
        traceback.print_exc()
        return jsonify({"erro": "Erro interno no servidor", "detalhes": str(e)}), 500
    
    finally:
        try:
            if cursor:
                cursor.close()
        except Exception as e:
            print("[WARN] falha ao fechar cursor:", e)
        try:
            if conn:
                conn.close()
        except Exception as e:
            print("[WARN] falha ao fechar conexão:", e)

@app.route("/atribuir-entregador", methods=["POST"])
@restaurant_only
def atribuir_entregador():
    """Atribui um entregador a um pedido na tabela deliverypendente"""
    conn = None
    cursor = None
    try:
        dados = request.json or {}
        nropedido = dados.get("nropedido")
        entregador = dados.get("entregador", "").strip()
        
        if not nropedido:
            return jsonify({"erro": "Número do pedido é obrigatório"}), 400
        
        if not entregador:
            return jsonify({"erro": "Nome do entregador é obrigatório"}), 400

        id_cliente = session.get("id_cliente")
        if not id_cliente:
            return jsonify({"erro": "id_cliente não encontrado na sessão"}), 400
        
        conn = conectar()
        cursor = conn.cursor()
        
        # Atualiza o entregador em todos os produtos do pedido (fonte principal)
        cursor.execute(
            """
            UPDATE pedido_diarios
            SET entregador = %s
            WHERE nropedido = %s AND id_cliente = %s AND origem = 'DELIVERY'
            """,
            (entregador, nropedido, id_cliente),
        )
        
        conn.commit()
        
        print(f"[ENTREGADOR] {entregador} atribuído ao pedido {nropedido}")
        
        return jsonify({
            "sucesso": True,
            "mensagem": f"Entregador {entregador} atribuído ao pedido {nropedido}"
        })
    
    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        traceback.print_exc()
        return jsonify({"erro": "Erro de banco de dados", "detalhes": str(db_err)}), 500
    
    except Exception as e:
        print("[ERROR]", e)
        traceback.print_exc()
        return jsonify({"erro": "Erro interno no servidor", "detalhes": str(e)}), 500
    
    finally:
        try:
            if cursor:
                cursor.close()
        except Exception as e:
            print("[WARN] falha ao fechar cursor:", e)
        try:
            if conn:
                conn.close()
        except Exception as e:
            print("[WARN] falha ao fechar conexão:", e)

@app.route("/api/diagnostico-comanda", methods=["GET"])
@login_required
def diagnostico_comanda():
    """Verifica a estrutura da tabela comanda"""
    conn = None
    cursor = None
    try:
        conn = conectar()
        cursor = conn.cursor(dictionary=True)
        
        # Obtém informações sobre a tabela
        cursor.execute("DESCRIBE comanda")
        colunas = cursor.fetchall()
        
        # Obtém número de registros
        cursor.execute("SELECT COUNT(*) as total FROM comanda")
        total = cursor.fetchone()
        
        return jsonify({
            "sucesso": True,
            "colunas": colunas,
            "total_registros": total['total'] if total else 0
        })
    
    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        return jsonify({"sucesso": False, "erro": str(db_err)}), 500
    
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@app.route("/fechar-comanda", methods=["POST"])
def fechar_comanda():
    """Transfere um pedido de pedido_diarios para comanda (fecha a comanda)"""
    conn = None
    cursor = None
    try:
        dados = request.json or {}
        nropedido = dados.get("nropedido")
        
        if not nropedido:
            return jsonify({"erro": "Número do pedido é obrigatório"}), 400

        id_cliente = session.get("id_cliente")
        if not id_cliente:
            return jsonify({"erro": "id_cliente não encontrado na sessão"}), 400
        
        conn = conectar()
        cursor = conn.cursor(dictionary=True)
        
        # Verifica se o pedido tem entregador atribuído (fonte principal)
        cursor.execute(
            """
            SELECT entregador
            FROM pedido_diarios
            WHERE nropedido = %s AND id_cliente = %s AND origem = 'DELIVERY'
              AND UPPER(COALESCE(status_pedido, '')) <> 'ITEM_REMOVIDO'
            ORDER BY chave DESC
            LIMIT 1
            """,
            (nropedido, id_cliente),
        )
        
        resultado = cursor.fetchone()
        
        if not resultado:
            return jsonify({"erro": "Pedido não encontrado"}), 404
        
        entregador = resultado.get('entregador', '')
        
        if not entregador or entregador.strip() == '':
            return jsonify({"erro": "Não é possível fechar a comanda sem atribuir um entregador"}), 400
        
        # Transfere os dados (fonte principal) para comanda
        cursor.execute(
            """
            INSERT INTO comanda
            (nropedido, telefone, cep, nome, endereco, nrocasa, complemento,
             codigoproduto, produto, preco, quantidade, classe, entregador, cliente, id_cliente, formapagamento)
            SELECT nropedido, telefone, cep, nome, endereco, nrocasa, complemento,
                   codigoproduto, produto, preco, quantidade, classe, entregador, cliente, id_cliente, formapagamento
            FROM pedido_diarios
            WHERE nropedido = %s AND id_cliente = %s AND origem = 'DELIVERY'
              AND UPPER(COALESCE(status_pedido, '')) <> 'ITEM_REMOVIDO'
        """,
            (nropedido, id_cliente),
        )
        
        registros_transferidos = cursor.rowcount
        
        # Remove os registros do pedido (fonte principal)
        cursor.execute(
            """
            DELETE FROM pedido_diarios
            WHERE nropedido = %s AND id_cliente = %s AND origem = 'DELIVERY'
            """,
            (nropedido, id_cliente),
        )
        
        conn.commit()
        
        print(f"[FECHAR COMANDA] Pedido {nropedido} transferido para comanda ({registros_transferidos} registros)")
        
        return jsonify({
            "sucesso": True,
            "mensagem": f"Comanda do pedido {nropedido} fechada com sucesso",
            "registros_transferidos": registros_transferidos
        })
    
    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(db_err)}), 500
    
    except Exception as e:
        print("[ERROR]", e)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(e)}), 500
    
    finally:
        try:
            if cursor:
                cursor.close()
        except Exception as e:
            print("[WARN] falha ao fechar cursor:", e)
        try:
            if conn:
                conn.close()
        except Exception as e:
            print("[WARN] falha ao fechar conexão:", e)

@app.route("/cancelar-pedido", methods=["POST"])
def cancelar_pedido():
    """Transfere um pedido de pedido_diarios para canceladas"""
    conn = None
    cursor = None
    try:
        dados = request.json or {}
        nropedido = dados.get("nropedido")
        
        if not nropedido:
            return jsonify({"erro": "Número do pedido é obrigatório"}), 400

        id_cliente = session.get("id_cliente")
        if not id_cliente:
            return jsonify({"erro": "id_cliente não encontrado na sessão"}), 400
        
        conn = conectar()
        cursor = conn.cursor()
        
        # Transfere os dados (fonte principal) para canceladas
        cursor.execute(
            """
            INSERT INTO canceladas
            (nropedido, cliente, telefone, nome, cep, endereco, nrocasa, complemento,
             codigoproduto, produto, preco, quantidade, classe, entregador, id_cliente)
            SELECT nropedido, cliente, telefone, nome, cep, endereco, nrocasa, complemento,
                   codigoproduto, produto, preco, quantidade, classe, entregador, id_cliente
            FROM pedido_diarios
            WHERE nropedido = %s AND id_cliente = %s AND origem = 'DELIVERY'
              AND UPPER(COALESCE(status_pedido, '')) <> 'ITEM_REMOVIDO'
            """,
            (nropedido, id_cliente),
        )
        
        registros_transferidos = cursor.rowcount
        
        # Remove os registros do pedido (fonte principal)
        cursor.execute(
            """
            DELETE FROM pedido_diarios
            WHERE nropedido = %s AND id_cliente = %s AND origem = 'DELIVERY'
            """,
            (nropedido, id_cliente),
        )
        
        conn.commit()
        
        print(f"[CANCELAR PEDIDO] Pedido {nropedido} transferido para canceladas ({registros_transferidos} registros)")
        
        return jsonify({
            "sucesso": True,
            "mensagem": f"Pedido {nropedido} cancelado com sucesso",
            "registros_transferidos": registros_transferidos
        })
    
    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(db_err)}), 500
    
    except Exception as e:
        print("[ERROR]", e)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(e)}), 500
    
    finally:
        try:
            if cursor:
                cursor.close()
        except Exception as e:
            print("[WARN] falha ao fechar cursor:", e)
        try:
            if conn:
                conn.close()
        except Exception as e:
            print("[WARN] falha ao fechar conexão:", e)

@app.route("/salvar-cliente", methods=["POST"])
@login_required
def salvar_cliente():
    conn = None
    cursor = None
    try:
        dados = request.json or {}
        
        # Log dos dados recebidos para debug
        print(f"\n{'='*60}")
        print(f"[SALVAR CLIENTE] REQUEST JSON COMPLETO:")
        print(dados)
        print(f"{'='*60}")
        print(f"[SALVAR CLIENTE] Dados recebidos:")
        print(f"  - Taxa do formulário (raw): {dados.get('taxaentrega')}")
        print(f"  - Taxa do formulário (type): {type(dados.get('taxaentrega'))}")
        print(f"  - Distância do formulário (raw): {dados.get('distancia')}")
        print(f"  - Distância do formulário (type): {type(dados.get('distancia'))}")
        print(f"{'='*60}\n")
        
        telefone = dados.get("telefone")
        
        if not telefone:
            return jsonify({"erro": "Telefone é obrigatório"}), 400

        conn = conectar()
        cursor = conn.cursor(dictionary=True)
        
        # Verifica configuração para saber se deve calcular distância/taxa
        id_cliente = session.get('id_cliente')
        cursor.execute("SELECT calculodistancia FROM configuracao WHERE chave = 1 AND id_cliente = %s", (id_cliente,))
        config = cursor.fetchone()
        calculo_habilitado = True
        if config:
            calculo_dist = (config.get('calculodistancia') or 'Sim').strip().lower()
            calculo_habilitado = (calculo_dist == 'sim')
            print(f"[SALVAR CLIENTE] Configuração: calculodistancia={calculo_dist}, habilitado={calculo_habilitado}")
        
        # Se cálculo estiver habilitado, calcula; senão usa valores do formulário
        if calculo_habilitado:
            # Distância: usa valor manual se enviado (>0), senão calcula automático
            distancia_bruta = dados.get("distancia", 0)
            try:
                distancia_bruta = float(distancia_bruta)
            except Exception:
                distancia_bruta = 0
            distancia_calc, lat_cli, lon_cli = calcular_distancia_cliente(dados)
            distancia_final = distancia_bruta if distancia_bruta > 0 else distancia_calc
            
            # Calcula taxa de entrega baseado na distância
            taxa_entrega = calcular_taxa_entrega(distancia_final, id_cliente)
            print(f"[SALVAR CLIENTE] Modo CALCULADO - Taxa={taxa_entrega}, Dist={distancia_final}")
        else:
            # Usa valores que vieram do formulário
            distancia_final = float(dados.get("distancia", 0) or 0)
            taxa_entrega = float(dados.get("taxaentrega", 0) or 0)
            lat_cli = None
            lon_cli = None
            print(f"[SALVAR CLIENTE] Modo MANUAL - Taxa={taxa_entrega}, Dist={distancia_final}")
        cursor = conn.cursor(dictionary=True)
        
        # Verificar se o cliente já existe
        id_cliente = session.get('id_cliente')
        cursor.execute("SELECT chave FROM clientes WHERE telefone = %s AND id_cliente = %s", (telefone, id_cliente))
        cliente_existente = cursor.fetchone()
        
        # Verificar se as colunas lat_cliente e lon_cliente existem
        cursor.execute("SHOW COLUMNS FROM clientes LIKE 'lat_cliente'")
        tem_lat_lon = cursor.fetchone() is not None
        # Verificar se coluna CEP existe
        cursor.execute("SHOW COLUMNS FROM clientes LIKE 'cep'")
        tem_cep = cursor.fetchone() is not None
        
        if cliente_existente:
            # Atualizar cliente existente
            if tem_lat_lon and tem_cep:
                sql = """UPDATE clientes SET 
                         nome = %s, endereco = %s, nrocasa = %s, complemento = %s,
                         referencia = %s, bairro = %s, cidade = %s, estado = %s,
                         taxaentrega = %s, distancia = %s, lat_cliente = %s, lon_cliente = %s, cep = %s
                         WHERE telefone = %s AND id_cliente = %s"""
                valores = (
                    dados.get("nome", ""),
                    dados.get("endereco", ""),
                    dados.get("nrocasa", ""),
                    dados.get("complemento", ""),
                    dados.get("referencia", ""),
                    dados.get("bairro", ""),
                    dados.get("cidade", ""),
                    dados.get("estado", ""),
                    taxa_entrega,
                    distancia_final,
                    lat_cli,
                    lon_cli,
                    dados.get("cep", ""),
                    telefone,
                    id_cliente
                )
            elif tem_lat_lon and not tem_cep:
                sql = """UPDATE clientes SET 
                         nome = %s, endereco = %s, nrocasa = %s, complemento = %s,
                         referencia = %s, bairro = %s, cidade = %s, estado = %s,
                         taxaentrega = %s, distancia = %s, lat_cliente = %s, lon_cliente = %s
                         WHERE telefone = %s AND id_cliente = %s"""
                valores = (
                    dados.get("nome", ""),
                    dados.get("endereco", ""),
                    dados.get("nrocasa", ""),
                    dados.get("complemento", ""),
                    dados.get("referencia", ""),
                    dados.get("bairro", ""),
                    dados.get("cidade", ""),
                    dados.get("estado", ""),
                    taxa_entrega,
                    distancia_final,
                    lat_cli,
                    lon_cli,
                    telefone,
                    id_cliente
                )
            elif tem_cep and not tem_lat_lon:
                sql = """UPDATE clientes SET 
                         nome = %s, endereco = %s, nrocasa = %s, complemento = %s,
                         referencia = %s, bairro = %s, cidade = %s, estado = %s,
                         taxaentrega = %s, distancia = %s, cep = %s
                         WHERE telefone = %s AND id_cliente = %s"""
                valores = (
                    dados.get("nome", ""),
                    dados.get("endereco", ""),
                    dados.get("nrocasa", ""),
                    dados.get("complemento", ""),
                    dados.get("referencia", ""),
                    dados.get("bairro", ""),
                    dados.get("cidade", ""),
                    dados.get("estado", ""),
                    taxa_entrega,
                    distancia_final,
                    dados.get("cep", ""),
                    telefone,
                    id_cliente
                )
            else:
                sql = """UPDATE clientes SET 
                         nome = %s, endereco = %s, nrocasa = %s, complemento = %s,
                         referencia = %s, bairro = %s, cidade = %s, estado = %s,
                         taxaentrega = %s, distancia = %s
                         WHERE telefone = %s AND id_cliente = %s"""
                valores = (
                    dados.get("nome", ""),
                    dados.get("endereco", ""),
                    dados.get("nrocasa", ""),
                    dados.get("complemento", ""),
                    dados.get("referencia", ""),
                    dados.get("bairro", ""),
                    dados.get("cidade", ""),
                    dados.get("estado", ""),
                    taxa_entrega,
                    distancia_final,
                    telefone,
                    id_cliente
                )
            cursor.execute(sql, valores)
            conn.commit()
            return jsonify({"sucesso": True, "mensagem": "Cliente atualizado com sucesso", "chave": cliente_existente["chave"], "distancia_calculada": distancia_final, "taxa_calculada": taxa_entrega})
        else:
            # Inserir novo cliente conforme colunas disponíveis
            if tem_lat_lon and tem_cep:
                sql = """INSERT INTO clientes 
                         (telefone, nome, endereco, nrocasa, complemento, referencia, 
                          bairro, cidade, estado, taxaentrega, distancia, lat_cliente, lon_cliente, cep, id_cliente)
                         VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
                valores = (
                    telefone,
                    dados.get("nome", ""),
                    dados.get("endereco", ""),
                    dados.get("nrocasa", ""),
                    dados.get("complemento", ""),
                    dados.get("referencia", ""),
                    dados.get("bairro", ""),
                    dados.get("cidade", ""),
                    dados.get("estado", ""),
                    taxa_entrega,
                    distancia_final,
                    lat_cli,
                    lon_cli,
                    dados.get("cep", ""),
                    id_cliente
                )
            elif tem_lat_lon and not tem_cep:
                sql = """INSERT INTO clientes 
                         (telefone, nome, endereco, nrocasa, complemento, referencia, 
                          bairro, cidade, estado, taxaentrega, distancia, lat_cliente, lon_cliente, id_cliente)
                         VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
                valores = (
                    telefone,
                    dados.get("nome", ""),
                    dados.get("endereco", ""),
                    dados.get("nrocasa", ""),
                    dados.get("complemento", ""),
                    dados.get("referencia", ""),
                    dados.get("bairro", ""),
                    dados.get("cidade", ""),
                    dados.get("estado", ""),
                    taxa_entrega,
                    distancia_final,
                    lat_cli,
                    lon_cli,
                    id_cliente
                )
            elif tem_cep and not tem_lat_lon:
                sql = """INSERT INTO clientes 
                         (telefone, nome, endereco, nrocasa, complemento, referencia, 
                          bairro, cidade, estado, taxaentrega, distancia, cep, id_cliente)
                         VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
                valores = (
                    telefone,
                    dados.get("nome", ""),
                    dados.get("endereco", ""),
                    dados.get("nrocasa", ""),
                    dados.get("complemento", ""),
                    dados.get("referencia", ""),
                    dados.get("bairro", ""),
                    dados.get("cidade", ""),
                    dados.get("estado", ""),
                    taxa_entrega,
                    distancia_final,
                    dados.get("cep", ""),
                    id_cliente
                )
            else:
                sql = """INSERT INTO clientes 
                         (telefone, nome, endereco, nrocasa, complemento, referencia, 
                          bairro, cidade, estado, taxaentrega, distancia, id_cliente)
                         VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
                valores = (
                    telefone,
                    dados.get("nome", ""),
                    dados.get("endereco", ""),
                    dados.get("nrocasa", ""),
                    dados.get("complemento", ""),
                    dados.get("referencia", ""),
                    dados.get("bairro", ""),
                    dados.get("cidade", ""),
                    dados.get("estado", ""),
                    taxa_entrega,
                    distancia_final,
                    id_cliente
                )
            cursor.execute(sql, valores)
            conn.commit()
            return jsonify({"sucesso": True, "mensagem": "Cliente cadastrado com sucesso", "chave": cursor.lastrowid, "distancia_calculada": distancia_final, "taxa_calculada": taxa_entrega})
    
    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        traceback.print_exc()
        if conn:
            conn.rollback()
        return jsonify({"erro": "Erro de banco de dados", "detalhes": str(db_err)}), 500
    
    except Exception as e:
        print("[ERROR]", e)
        traceback.print_exc()
        return jsonify({"erro": "Erro interno no servidor", "detalhes": str(e)}), 500
    
    finally:
        try:
            if cursor:
                cursor.close()
        except Exception as e:
            print("[WARN] falha ao fechar cursor:", e)
        try:
            if conn:
                conn.close()
        except Exception as e:
            print("[WARN] falha ao fechar conexão:", e)

@app.route("/api/comandas", methods=["GET"])
@restaurant_only
def api_comandas():
    """Retorna todos os registros da tabela comanda em JSON"""
    conn = None
    cursor = None
    try:
        conn = conectar()
        cursor = conn.cursor(dictionary=True)
        
        id_cliente = session.get('id_cliente')
        cursor.execute("SELECT * FROM comanda WHERE id_cliente = %s", (id_cliente,))
        registros = cursor.fetchall() or []
        
        return jsonify({
            "sucesso": True,
            "registros": registros
        })
    
    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        return jsonify({"sucesso": False, "erro": "Erro de banco de dados"}), 500
    
    except Exception as e:
        print("[ERROR]", e)
        return jsonify({"sucesso": False, "erro": "Erro interno no servidor"}), 500
    
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@app.route("/api/canceladas", methods=["GET"])
@login_required
def api_canceladas():
    """Retorna todos os registros da tabela canceladas em JSON"""
    conn = None
    cursor = None
    try:
        conn = conectar()
        cursor = conn.cursor(dictionary=True)
        
        id_cliente = session.get('id_cliente')
        cursor.execute("SELECT * FROM canceladas WHERE id_cliente = %s", (id_cliente,))
        registros = cursor.fetchall() or []
        
        return jsonify({
            "sucesso": True,
            "registros": registros
        })
    
    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        return jsonify({"sucesso": False, "erro": "Erro de banco de dados"}), 500
    
    except Exception as e:
        print("[ERROR]", e)
        return jsonify({"sucesso": False, "erro": "Erro interno no servidor"}), 500
    
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@app.route("/criar-coluna-cliente-canceladas", methods=["POST"])
def criar_coluna_cliente_canceladas():
    """Adiciona as colunas cliente nas tabelas canceladas, comanda e deliverypendente se não existir"""
    conn = None
    cursor = None
    try:
        conn = conectar()
        cursor = conn.cursor()
        
        # Verifica e adiciona coluna cliente na tabela canceladas
        cursor.execute("SHOW COLUMNS FROM canceladas LIKE 'cliente'")
        if cursor.fetchone() is None:
            cursor.execute("ALTER TABLE canceladas ADD COLUMN cliente VARCHAR(255) NULL")
            print("[INFO] Coluna 'cliente' adicionada à tabela canceladas")
        
        # Verifica e adiciona coluna cliente na tabela comanda
        cursor.execute("SHOW COLUMNS FROM comanda LIKE 'cliente'")
        if cursor.fetchone() is None:
            cursor.execute("ALTER TABLE comanda ADD COLUMN cliente VARCHAR(255) NULL")
            print("[INFO] Coluna 'cliente' adicionada à tabela comanda")
        
        # Verifica e adiciona coluna cliente na tabela deliverypendente
        cursor.execute("SHOW COLUMNS FROM deliverypendente LIKE 'cliente'")
        if cursor.fetchone() is None:
            cursor.execute("ALTER TABLE deliverypendente ADD COLUMN cliente VARCHAR(255) NULL")
            print("[INFO] Coluna 'cliente' adicionada à tabela deliverypendente")
        
        # Verifica e adiciona coluna telefone na tabela canceladas (se não existir)
        cursor.execute("SHOW COLUMNS FROM canceladas LIKE 'telefone'")
        if cursor.fetchone() is None:
            # Adiciona após nropedido
            cursor.execute("ALTER TABLE canceladas ADD COLUMN telefone VARCHAR(20) NULL AFTER nropedido")
            print("[INFO] Coluna 'telefone' adicionada à tabela canceladas")
        
        return jsonify({"sucesso": True, "mensagem": "Colunas adicionadas com sucesso"})
    
    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        return jsonify({"sucesso": False, "erro": "Erro de banco de dados", "detalhes": str(db_err)}), 500
    
    except Exception as e:
        print("[ERROR]", e)
        return jsonify({"sucesso": False, "erro": "Erro interno", "detalhes": str(e)}), 500
    
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

# Servir arquivos PDF estáticos da pasta pedidos
@app.route("/pedidos/<path:filename>")
def servir_pdf(filename):
    """Serve PDFs gerados da pasta pedidos."""
    from flask import send_from_directory
    return send_from_directory("c:\\novaloja1\\pedidos", filename)

@app.route("/criar-tabela-usuarios", methods=["POST"])
def criar_tabela_usuarios():
    """Cria a tabela de usuários para login"""
    conn = None
    cursor = None
    try:
        conn = conectar()
        cursor = conn.cursor()
        
        # Criar tabela
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                chave INT AUTO_INCREMENT PRIMARY KEY,
                usuario VARCHAR(100) NOT NULL UNIQUE,
                senha VARCHAR(255) NOT NULL,
                data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Inserir usuário padrão
        cursor.execute("SELECT COUNT(*) FROM usuarios WHERE usuario = 'admin'")
        if cursor.fetchone()[0] == 0:
            cursor.execute("INSERT INTO usuarios (usuario, senha) VALUES ('admin', 'admin')")
        
        conn.commit()
        
        print("[INFO] Tabela 'usuarios' criada com sucesso")
        return jsonify({"sucesso": True, "mensagem": "Tabela de usuários criada com sucesso"})
    
    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        return jsonify({"sucesso": False, "erro": str(db_err)}), 500
    
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@app.route("/atualizar-cliente-comanda", methods=["POST"])
def atualizar_cliente_comanda():
    """Atualiza o campo cliente na tabela comanda copiando de nome"""
    conn = None
    cursor = None
    try:
        conn = conectar()
        cursor = conn.cursor()
        
        # Atualiza registros onde cliente está vazio
        cursor.execute("UPDATE comanda SET cliente = nome WHERE cliente IS NULL OR cliente = ''")
        registros_atualizados = cursor.rowcount
        
        conn.commit()
        
        print(f"[INFO] {registros_atualizados} registros atualizados na tabela comanda")
        return jsonify({
            "sucesso": True, 
            "mensagem": f"{registros_atualizados} registros atualizados com sucesso"
        })
    
    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        return jsonify({"sucesso": False, "erro": str(db_err)}), 500
    
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@app.route("/verificar-estrutura-produtos", methods=["GET"])
def verificar_estrutura_produtos():
    """Retorna a estrutura da tabela produtos"""
    conn = None
    cursor = None
    try:
        conn = conectar()
        cursor = conn.cursor(dictionary=True)
        
        # Mostra as colunas da tabela
        cursor.execute("DESCRIBE produtos")
        colunas = cursor.fetchall()
        
        return jsonify({"sucesso": True, "colunas": colunas})
    
    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        return jsonify({"sucesso": False, "erro": str(db_err)}), 500
    
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@app.route("/api/fechamento/preview", methods=["POST"])
@login_required
def api_fechamento_preview():
    """Resumo de linhas RECEBIDO/ITEM_REMOVIDO no intervalo (pedido_diarios)."""
    try:
        id_cliente = session.get("id_cliente")
        if not id_cliente:
            return jsonify({"sucesso": False, "erro": "Sessão inválida: id_cliente não encontrado."}), 401
        data = request.get_json(silent=True) or {}
        di = str(data.get("data_inicio") or "").strip()
        df = str(data.get("data_fim") or "").strip()
        out = preview_fechamento(int(id_cliente), di, df)
        return jsonify(out)
    except ValueError as ve:
        return jsonify({"sucesso": False, "erro": str(ve)}), 400
    except Exception as e:
        print("[FECHAMENTO PREVIEW]", e, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(e)}), 500


@app.route("/api/fechamento/resumo-financeiro", methods=["POST"])
@login_required
def api_fechamento_resumo_financeiro():
    """Totais por status e forma de pagamento no período (RECEBIDO/ITEM_REMOVIDO)."""
    try:
        id_cliente = session.get("id_cliente")
        if not id_cliente:
            return jsonify({"sucesso": False, "erro": "Sessão inválida: id_cliente não encontrado."}), 401
        data = request.get_json(silent=True) or {}
        di = str(data.get("data_inicio") or "").strip()
        df = str(data.get("data_fim") or "").strip()
        out = resumo_financeiro_fechamento(int(id_cliente), di, df)
        return jsonify(out)
    except ValueError as ve:
        return jsonify({"sucesso": False, "erro": str(ve)}), 400
    except Exception as e:
        print("[FECHAMENTO RESUMO FINANCEIRO]", e, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(e)}), 500


@app.route("/api/fechamento/relatorio-gerencial", methods=["POST"])
@login_required
def api_fechamento_relatorio_gerencial():
    """Prestação de contas: canais, pagamentos (JSON baixa), cancelamentos, produtos, horários, clientes novos."""
    try:
        id_cliente = session.get("id_cliente")
        if not id_cliente:
            return jsonify({"sucesso": False, "erro": "Sessão inválida: id_cliente não encontrado."}), 401
        data = request.get_json(silent=True) or {}
        di = str(data.get("data_inicio") or "").strip()
        df = str(data.get("data_fim") or "").strip()
        out = relatorio_gerencial_periodo(int(id_cliente), di, df)
        return jsonify(out)
    except ValueError as ve:
        return jsonify({"sucesso": False, "erro": str(ve)}), 400
    except Exception as e:
        print("[FECHAMENTO RELATORIO GERENCIAL]", e, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(e)}), 500


@app.route("/api/fechamento/executar", methods=["POST"])
@login_required
def api_fechamento_executar():
    """Arquiva em pedido_periodos, remove do diário e grava relatório .txt."""
    try:
        id_cliente = session.get("id_cliente")
        if not id_cliente:
            return jsonify({"sucesso": False, "erro": "Sessão inválida: id_cliente não encontrado."}), 401
        data = request.get_json(silent=True) or {}
        di = str(data.get("data_inicio") or "").strip()
        df = str(data.get("data_fim") or "").strip()
        out = executar_fechamento(int(id_cliente), di, df)
        if not out.get("sucesso"):
            return jsonify(out), 400
        return jsonify(out)
    except ValueError as ve:
        return jsonify({"sucesso": False, "erro": str(ve)}), 400
    except Exception as e:
        print("[FECHAMENTO EXECUTAR]", e, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(e)}), 500


@app.route("/api/verificar-delivery-pendente", methods=["GET"])
@login_required
@restaurant_only
def verificar_delivery_pendente():
    """Verifica se existem registros na tabela deliverypendente, contando apenas pedidos únicos"""
    conn = None
    cursor = None
    try:
        conn = conectar()
        cursor = conn.cursor(dictionary=True)
        
        # Fonte principal: pedido_diarios (DELIVERY + AGUARDE)
        id_cliente = session.get('id_cliente')
        cursor.execute(
            """
            SELECT COUNT(DISTINCT nropedido) as total
            FROM pedido_diarios
            WHERE id_cliente = %s
              AND origem = 'DELIVERY'
              AND UPPER(COALESCE(status_pedido, '')) = 'AGUARDE'
              AND UPPER(COALESCE(status_pedido, '')) <> 'ITEM_REMOVIDO'
            """,
            (id_cliente,),
        )
        resultado = cursor.fetchone()
        total = resultado['total'] if resultado else 0
        
        return jsonify({
            "existe": total > 0,
            "total": total
        })
    
    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        return jsonify({"existe": False, "total": 0, "erro": str(db_err)}), 500
    
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@app.route("/api/limpar-delivery-pendente", methods=["POST"])
@login_required
@restaurant_only
def limpar_delivery_pendente():
    """Apaga todos os registros da tabela deliverypendente"""
    conn = None
    cursor = None
    try:
        conn = conectar()
        cursor = conn.cursor()
        
        id_cliente = session.get('id_cliente')
        # Obtém o número de pedidos únicos antes de deletar (fonte principal)
        cursor.execute(
            """
            SELECT COUNT(DISTINCT nropedido) as total
            FROM pedido_diarios
            WHERE id_cliente = %s
              AND origem = 'DELIVERY'
              AND UPPER(COALESCE(status_pedido, '')) = 'AGUARDE'
              AND UPPER(COALESCE(status_pedido, '')) <> 'ITEM_REMOVIDO'
            """,
            (id_cliente,),
        )
        resultado = cursor.fetchone()
        pedidos_deletados = resultado[0] if resultado else 0
        # Deleta os registros pendentes (fonte principal) e mantém deliverypendente em sincronia
        cursor.execute(
            """
            DELETE FROM pedido_diarios
            WHERE id_cliente = %s
              AND origem = 'DELIVERY'
              AND UPPER(COALESCE(status_pedido, '')) = 'AGUARDE'
              AND UPPER(COALESCE(status_pedido, '')) <> 'ITEM_REMOVIDO'
            """,
            (id_cliente,),
        )
        conn.commit()
        
        return jsonify({
            "sucesso": True,
            "registros_deletados": pedidos_deletados,
            "mensagem": f"{pedidos_deletados} pedido(s) deletado(s) com sucesso"
        })
    
    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        return jsonify({
            "sucesso": False,
            "mensagem": str(db_err)
        }), 500
    
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@app.route("/api/verificar-comandas", methods=["GET"])
@login_required
@restaurant_only
def verificar_comandas():
    """Verifica se existem registros na tabela comandas, contando apenas pedidos únicos"""
    conn = None
    cursor = None
    try:
        conn = conectar()
        cursor = conn.cursor(dictionary=True)
        
        # Conta registros únicos de pedidos na tabela comandas (agrupado por nropedido)
        id_cliente = session.get('id_cliente')
        cursor.execute("SELECT COUNT(DISTINCT nropedido) as total FROM comanda WHERE id_cliente = %s", (id_cliente,))
        resultado = cursor.fetchone()
        total = resultado['total'] if resultado else 0
        
        return jsonify({
            "existe": total > 0,
            "total": total
        })
    
    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        return jsonify({"existe": False, "total": 0, "erro": str(db_err)}), 500
    
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@app.route("/api/transferir-comandas-liquidadas", methods=["POST"])
@login_required
@restaurant_only
def transferir_comandas_liquidadas():
    """Transfere registros da tabela comanda para liquidada e reseta o contador"""
    conn = None
    cursor = None
    try:
        conn = conectar()
        cursor = conn.cursor()
        id_cliente = session.get('id_cliente')
        
        # Obtém o número de pedidos únicos antes de transferir
        cursor.execute("SELECT COUNT(DISTINCT nropedido) as total FROM comanda WHERE id_cliente = %s", (id_cliente,))
        resultado = cursor.fetchone()
        pedidos_transferidos = resultado[0] if resultado else 0
        
        if pedidos_transferidos > 0:
            # Insere os registros na tabela liquidada
            cursor.execute("""
                INSERT INTO liquidada 
                (nropedido, telefone, cep, nome, endereco, nrocasa, complemento, 
                 codigoproduto, produto, preco, quantidade, classe, entregador, cliente, data_criacao, id_cliente, formapagamento)
                SELECT nropedido, telefone, cep, nome, endereco, nrocasa, complemento,
                       codigoproduto, produto, preco, quantidade, classe, entregador, cliente, data_criacao, id_cliente, formapagamento
                FROM comanda WHERE id_cliente = %s
            """, (id_cliente,))
            
            # Deleta todos os registros da tabela comanda
            cursor.execute("DELETE FROM comanda WHERE id_cliente = %s", (id_cliente,))
        
        # Reseta o contador de pedidos para zero apenas para o id_cliente atual
        print(f"[RESET CONTADOR] id_cliente={id_cliente}")
        cursor.execute("UPDATE contadorpedido SET contador = 0 WHERE id_cliente = %s", (id_cliente,))
        print(f"[RESET CONTADOR] Linhas afetadas: {cursor.rowcount}")
        conn.commit()

        # Busca o valor atualizado do contador para o id_cliente
        cursor.execute("SELECT contador FROM contadorpedido WHERE id_cliente = %s", (id_cliente,))
        contador_atual = cursor.fetchone()
        contador_valor = contador_atual[0] if contador_atual else 0
        print(f"[RESET CONTADOR] Valor atual: {contador_valor}")

        return jsonify({
            "sucesso": True,
            "registros_transferidos": pedidos_transferidos,
            "contador_atual": contador_valor,
            "mensagem": f"{pedidos_transferidos} pedido(s) transferido(s) com sucesso e contador resetado"
        })
    
    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        return jsonify({
            "sucesso": False,
            "mensagem": str(db_err)
        }), 500
    
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()



# Endpoint para retornar formas de pagamento filtradas por id_cliente (API)
@app.route("/api/formas-pagamento", methods=["GET"])
@login_required
def formas_pagamento_api():
    conn = None
    cursor = None
    try:
        conn = conectar()
        cursor = conn.cursor(dictionary=True)
        id_cliente = session.get('id_cliente')
        print(f"[DEBUG] id_cliente na sessão: {id_cliente}")
        cursor.execute("SELECT * FROM formapagamento WHERE id_cliente = %s", (id_cliente,))
        formas = cursor.fetchall() or []
        print(f"[DEBUG] Formas encontradas: {formas}")
        return jsonify({"sucesso": True, "formas": formas})
    except Exception as e:
        print("[ERRO FORMAS PAGAMENTO]", e)
        return jsonify({"sucesso": False, "erro": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

# Endpoint para buscar produtos de uma mesa específica
@app.route("/api/mesa/<int:mesanro>", methods=["GET"])
@login_required
@restaurant_only
def buscar_mesa(mesanro):
    try:
        _ensure_pedido_diarios_preparo_columns()
        id_cliente = session.get('id_cliente')
        print(f"[DEBUG] /api/mesa/<mesanro> chamado com mesanro={mesanro} (type={type(mesanro)}) e id_cliente={id_cliente}", flush=True)
        conn = conectar()
        cur = conn.cursor(dictionary=True)
        if not id_cliente:
            return jsonify({"sucesso": False, "mensagem": "Sessão inválida."}), 401
        prod_imp_col = None
        prod_cod_col = None
        try:
            cur.execute("SHOW COLUMNS FROM produtos LIKE 'impressora'")
            if cur.fetchone() is not None:
                prod_imp_col = "impressora"
            else:
                cur.execute("SHOW COLUMNS FROM produtos LIKE 'impressoras'")
                if cur.fetchone() is not None:
                    prod_imp_col = "impressoras"
            for cand in ("codigoproduto", "codigo", "codbarra", "cod_barras", "ean"):
                cur.execute("SHOW COLUMNS FROM produtos LIKE %s", (cand,))
                if cur.fetchone() is not None:
                    prod_cod_col = cand
                    break
        except Exception:
            prod_imp_col = None
            prod_cod_col = None
        try:
            cur.execute("SHOW COLUMNS FROM pedido_diarios LIKE 'status_mesa'")
            if cur.fetchone() is None:
                cur.execute("ALTER TABLE pedido_diarios ADD COLUMN status_mesa VARCHAR(20) NULL AFTER nropedido")
        except Exception as e:
            print("[MESA] Falha ao garantir coluna status_mesa:", e, flush=True)
        try:
            cur.execute("SHOW COLUMNS FROM pedido_diarios LIKE 'pessoas_mesa'")
            if cur.fetchone() is None:
                cur.execute("ALTER TABLE pedido_diarios ADD COLUMN pessoas_mesa INT NULL AFTER status_mesa")
        except Exception as e:
            print("[MESA] Falha ao garantir coluna pessoas_mesa:", e, flush=True)
        params_pd = [mesanro, id_cliente]
        imp_sel = f"COALESCE(p.{prod_imp_col},'') AS impressoras_produto" if prod_imp_col else "'' AS impressoras_produto"
        join_on = ""
        if prod_imp_col:
            if prod_cod_col:
                join_on = (
                    f"p.id_cliente = pedido_diarios.id_cliente AND ("
                    f"p.chave = CAST(pedido_diarios.codigoproduto AS UNSIGNED) OR "
                    f"TRIM(COALESCE(p.{prod_cod_col},'')) = TRIM(COALESCE(pedido_diarios.codigoproduto,''))"
                    f")"
                )
            else:
                join_on = "p.id_cliente = pedido_diarios.id_cliente AND p.chave = CAST(pedido_diarios.codigoproduto AS UNSIGNED)"
        join_prod = (
            f"LEFT JOIN produtos p ON {join_on}" if (prod_imp_col and join_on) else ""
        )
        query_pd = f"""
            SELECT
                chave AS id,
                nropedido AS mesanro,
                produto,
                preco,
                quantidade,
                codigoproduto,
                classe,
                id_cliente,
                COALESCE(lancamento, nrolancamento) AS lancamento,
                COALESCE(lancamento, nrolancamento) AS nrolancamento,
                obs_item,
                dados_item,
                IFNULL(produto, '') AS descricao_produto,
                COALESCE(imp_preparo,'N') AS imp_preparo,
                {imp_sel}
            FROM pedido_diarios
            {join_prod}
            WHERE origem = 'MESA'
              AND nropedido = %s
              AND UPPER(COALESCE(status_pedido, '')) <> 'ITEM_REMOVIDO'
              AND UPPER(COALESCE(status_mesa, '')) <> 'RECEBIDO'
              AND id_cliente = %s
            ORDER BY chave ASC
        """
        print(f"[DEBUG] Query pedido_diarios mesa: {query_pd.strip()} params={params_pd}", flush=True)
        registros = []
        try:
            cur.execute(query_pd, params_pd)
            registros = cur.fetchall() or []
        except Exception as e:
            print("[MESA] Falha ao executar query com join de produtos:", e, flush=True)
            traceback.print_exc()
            query_fallback = f"""
                SELECT
                    chave AS id,
                    nropedido AS mesanro,
                    produto,
                    preco,
                    quantidade,
                    codigoproduto,
                    classe,
                    id_cliente,
                    COALESCE(lancamento, nrolancamento) AS lancamento,
                    COALESCE(lancamento, nrolancamento) AS nrolancamento,
                    obs_item,
                    dados_item,
                    IFNULL(produto, '') AS descricao_produto,
                    COALESCE(imp_preparo,'N') AS imp_preparo,
                    '' AS impressoras_produto
                FROM pedido_diarios
                WHERE origem = 'MESA'
                  AND nropedido = %s
                  AND UPPER(COALESCE(status_pedido, '')) <> 'ITEM_REMOVIDO'
                  AND UPPER(COALESCE(status_mesa, '')) <> 'RECEBIDO'
                  AND id_cliente = %s
                ORDER BY chave ASC
            """
            print(f"[DEBUG] Query fallback pedido_diarios mesa: {query_fallback.strip()} params={params_pd}", flush=True)
            cur.execute(query_fallback, params_pd)
            registros = cur.fetchall() or []
        _preencher_impressoras_produto(cur, id_cliente, registros, src_cod_field="codigoproduto", dest_field="impressoras_produto")
        cur.execute(
            """
            SELECT
              SUM(CASE WHEN UPPER(COALESCE(status_mesa,'')) = 'CONTA' THEN 1 ELSE 0 END) AS conta_count,
              SUM(CASE WHEN UPPER(COALESCE(status_pedido,'')) <> 'ITEM_REMOVIDO' AND UPPER(COALESCE(status_mesa,'')) <> 'RECEBIDO' THEN 1 ELSE 0 END) AS ativa_count,
              MAX(COALESCE(pessoas_mesa, 0)) AS pessoas_mesa
            FROM pedido_diarios
            WHERE origem = 'MESA'
              AND nropedido = %s
              AND id_cliente = %s
            """,
            (mesanro, id_cliente),
        )
        st_row = cur.fetchone() or {}
        conta_count = int(st_row.get("conta_count") or 0)
        ativa_count = int(st_row.get("ativa_count") or 0)
        mesa_status = "CONTA" if conta_count > 0 else ("ATIVA" if ativa_count > 0 else "LIVRE")
        try:
            pessoas_mesa = int(st_row.get("pessoas_mesa") or 0)
        except Exception:
            pessoas_mesa = 0
        if pessoas_mesa <= 0:
            pessoas_mesa = 1
        cur.close()
        conn.close()
        return jsonify({"sucesso": True, "registros": registros, "fonte": "pedido_diarios", "mesa_status": mesa_status, "pessoas_mesa": pessoas_mesa})
    except Exception as e:
        print('[ERRO] ao buscar produtos da mesa:', e, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "mensagem": "Erro ao buscar produtos da mesa."}), 500


@app.route("/api/mesa/<int:mesanro>/pessoas", methods=["POST"])
@login_required
@restaurant_only
def api_mesa_set_pessoas(mesanro):
    conn = None
    cur = None
    try:
        data = request.get_json(silent=True) or {}
        try:
            pessoas = int(data.get("pessoas") or 0)
        except Exception:
            pessoas = 0
        if pessoas < 1 or pessoas > 50:
            return jsonify({"sucesso": False, "erro": "Informe um número de pessoas entre 1 e 50."}), 400

        id_cliente = session.get("id_cliente")
        if not id_cliente:
            return jsonify({"sucesso": False, "erro": "Sessão inválida."}), 401

        conn = conectar()
        conn.start_transaction()
        cur = conn.cursor(dictionary=True)
        cur.execute("SHOW COLUMNS FROM pedido_diarios LIKE 'status_mesa'")
        if cur.fetchone() is None:
            cur.execute("ALTER TABLE pedido_diarios ADD COLUMN status_mesa VARCHAR(20) NULL AFTER nropedido")
        cur.execute("SHOW COLUMNS FROM pedido_diarios LIKE 'pessoas_mesa'")
        if cur.fetchone() is None:
            cur.execute("ALTER TABLE pedido_diarios ADD COLUMN pessoas_mesa INT NULL AFTER status_mesa")

        cur.execute(
            """
            SELECT
              SUM(CASE WHEN UPPER(COALESCE(status_pedido,'')) <> 'ITEM_REMOVIDO' THEN 1 ELSE 0 END) AS total_itens,
              MAX(UPPER(COALESCE(status_mesa,''))) AS status_mesa
            FROM pedido_diarios
            WHERE origem = 'MESA'
              AND nropedido = %s
              AND id_cliente = %s
            """,
            (mesanro, id_cliente),
        )
        row = cur.fetchone() or {}
        if int(row.get("total_itens") or 0) <= 0:
            conn.rollback()
            return jsonify({"sucesso": False, "erro": "Mesa sem itens."}), 404
        st = str(row.get("status_mesa") or "").strip().upper()
        if st == "RECEBIDO":
            conn.rollback()
            return jsonify({"sucesso": False, "erro": "Mesa já está RECEBIDO e não pode ser alterada."}), 409

        cur.execute(
            """
            UPDATE pedido_diarios
            SET pessoas_mesa = %s
            WHERE origem = 'MESA'
              AND nropedido = %s
              AND id_cliente = %s
              AND UPPER(COALESCE(status_pedido,'')) <> 'ITEM_REMOVIDO'
            """,
            (pessoas, mesanro, id_cliente),
        )
        conn.commit()
        return jsonify({"sucesso": True, "pessoas_mesa": pessoas})
    except Exception as e:
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        print("[MESA PESSOAS ERRO]", e, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route("/api/mesa/<int:mesanro>/reabrir", methods=["POST"])
@login_required
@restaurant_only
def api_mesa_reabrir(mesanro):
    conn = None
    cur = None
    try:
        id_cliente = session.get("id_cliente")
        if not id_cliente:
            return jsonify({"sucesso": False, "erro": "Sessão inválida."}), 401
        conn = conectar()
        conn.start_transaction()
        cur = conn.cursor(dictionary=True)
        cur.execute("SHOW COLUMNS FROM pedido_diarios LIKE 'status_mesa'")
        if cur.fetchone() is None:
            cur.execute("ALTER TABLE pedido_diarios ADD COLUMN status_mesa VARCHAR(20) NULL AFTER nropedido")

        cur.execute(
            """
            SELECT
              SUM(CASE WHEN UPPER(COALESCE(status_pedido,'')) <> 'ITEM_REMOVIDO' AND UPPER(COALESCE(status_mesa,'')) <> 'RECEBIDO' THEN 1 ELSE 0 END) AS total_ativos,
              SUM(CASE WHEN UPPER(COALESCE(status_mesa,'')) = 'CONTA' THEN 1 ELSE 0 END) AS conta_count
            FROM pedido_diarios
            WHERE origem = 'MESA'
              AND nropedido = %s
              AND id_cliente = %s
            """,
            (mesanro, id_cliente),
        )
        row = cur.fetchone() or {}
        if int(row.get("total_ativos") or 0) <= 0:
            conn.rollback()
            return jsonify({"sucesso": False, "erro": "Mesa sem itens."}), 404
        if int(row.get("conta_count") or 0) <= 0:
            conn.rollback()
            return jsonify({"sucesso": False, "erro": "Mesa não está em CONTA."}), 409

        cur.execute(
            """
            UPDATE pedido_diarios
            SET status_mesa = 'ABERTA'
            WHERE origem = 'MESA'
              AND nropedido = %s
              AND id_cliente = %s
              AND UPPER(COALESCE(status_pedido, '')) <> 'ITEM_REMOVIDO'
              AND UPPER(COALESCE(status_mesa, '')) = 'CONTA'
            """,
            (mesanro, id_cliente),
        )
        if cur.rowcount <= 0:
            conn.rollback()
            return jsonify({"sucesso": False, "erro": "Não foi possível reabrir a mesa."}), 500
        conn.commit()
        return jsonify({"sucesso": True})
    except Exception as e:
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        print("[MESA REABRIR ERRO]", e, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route("/api/mesa/<int:mesanro>/transferir", methods=["POST"])
@login_required
@restaurant_only
def api_mesa_transferir(mesanro):
    conn = None
    cur = None
    try:
        data = request.get_json(silent=True) or {}
        try:
            mesa_para = int(data.get("para") or 0)
        except Exception:
            mesa_para = 0
        if mesa_para <= 0:
            return jsonify({"sucesso": False, "erro": "Mesa destino inválida."}), 400
        if mesa_para == int(mesanro):
            return jsonify({"sucesso": False, "erro": "Mesa destino deve ser diferente da origem."}), 400

        id_cliente = session.get("id_cliente")
        if not id_cliente:
            return jsonify({"sucesso": False, "erro": "Sessão inválida."}), 401

        conn = conectar()
        conn.start_transaction()
        cur = conn.cursor(dictionary=True)
        cur.execute("SHOW COLUMNS FROM pedido_diarios LIKE 'status_mesa'")
        if cur.fetchone() is None:
            cur.execute("ALTER TABLE pedido_diarios ADD COLUMN status_mesa VARCHAR(20) NULL AFTER nropedido")

        cur.execute(
            """
            SELECT
              SUM(CASE WHEN UPPER(COALESCE(status_pedido,'')) <> 'ITEM_REMOVIDO' AND UPPER(COALESCE(status_mesa,'')) <> 'RECEBIDO' THEN 1 ELSE 0 END) AS ativos_origem
            FROM pedido_diarios
            WHERE origem = 'MESA'
              AND nropedido = %s
              AND id_cliente = %s
            """,
            (mesanro, id_cliente),
        )
        row_o = cur.fetchone() or {}
        if int(row_o.get("ativos_origem") or 0) <= 0:
            conn.rollback()
            return jsonify({"sucesso": False, "erro": "Mesa origem sem itens."}), 404

        cur.execute(
            """
            SELECT
              SUM(CASE WHEN UPPER(COALESCE(status_pedido,'')) <> 'ITEM_REMOVIDO' AND UPPER(COALESCE(status_mesa,'')) <> 'RECEBIDO' THEN 1 ELSE 0 END) AS ativos_destino
            FROM pedido_diarios
            WHERE origem = 'MESA'
              AND nropedido = %s
              AND id_cliente = %s
            """,
            (mesa_para, id_cliente),
        )
        row_d = cur.fetchone() or {}
        if int(row_d.get("ativos_destino") or 0) > 0:
            conn.rollback()
            return jsonify({"sucesso": False, "erro": "Mesa destino já possui itens."}), 409

        cur.execute(
            """
            UPDATE pedido_diarios
            SET nropedido = %s
            WHERE origem = 'MESA'
              AND nropedido = %s
              AND id_cliente = %s
              AND UPPER(COALESCE(status_pedido,'')) <> 'ITEM_REMOVIDO'
              AND UPPER(COALESCE(status_mesa,'')) <> 'RECEBIDO'
            """,
            (mesa_para, mesanro, id_cliente),
        )
        if cur.rowcount <= 0:
            conn.rollback()
            return jsonify({"sucesso": False, "erro": "Não foi possível transferir a mesa."}), 500

        conn.commit()
        return jsonify({"sucesso": True, "de": int(mesanro), "para": int(mesa_para)})
    except Exception as e:
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        print("[MESA TRANSFERIR ERRO]", e, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route("/api/mesa/<int:mesanro>/status", methods=["POST"])
@login_required
@restaurant_only
def api_mesa_set_status(mesanro):
    conn = None
    cur = None
    try:
        data = request.get_json(silent=True) or {}
        status = str(data.get("status") or "").strip().upper()
        if status not in ("CONTA", "RECEBIDO"):
            return jsonify({"sucesso": False, "erro": "Status inválido."}), 400
        id_cliente = session.get("id_cliente")
        if not id_cliente:
            return jsonify({"sucesso": False, "erro": "Sessão inválida."}), 401
        conn = conectar()
        conn.start_transaction()
        cur = conn.cursor(dictionary=True)
        cur.execute("SHOW COLUMNS FROM pedido_diarios LIKE 'status_mesa'")
        if cur.fetchone() is None:
            cur.execute("ALTER TABLE pedido_diarios ADD COLUMN status_mesa VARCHAR(20) NULL AFTER nropedido")
        cur.execute(
            """
            SELECT
              SUM(CASE WHEN UPPER(COALESCE(status_pedido,'')) <> 'ITEM_REMOVIDO' AND UPPER(COALESCE(status_mesa,'')) <> 'RECEBIDO' THEN 1 ELSE 0 END) AS total_ativos
            FROM pedido_diarios
            WHERE origem = 'MESA'
              AND nropedido = %s
              AND id_cliente = %s
            """,
            (mesanro, id_cliente),
        )
        row = cur.fetchone() or {}
        if int(row.get("total_ativos") or 0) <= 0:
            conn.rollback()
            return jsonify({"sucesso": False, "erro": "Mesa sem itens."}), 404
        if status == "RECEBIDO":
            conn.rollback()
            return jsonify({"sucesso": False, "erro": "Use o recebimento da mesa para marcar como RECEBIDO."}), 409
        cur.execute(
            """
            UPDATE pedido_diarios
            SET status_mesa = 'CONTA'
            WHERE origem = 'MESA'
              AND nropedido = %s
              AND id_cliente = %s
              AND UPPER(COALESCE(status_pedido, '')) <> 'ITEM_REMOVIDO'
              AND UPPER(COALESCE(status_mesa, '')) <> 'RECEBIDO'
            """,
            (mesanro, id_cliente),
        )
        conn.commit()
        return jsonify({"sucesso": True})
    except Exception as e:
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        print("[MESA STATUS ERRO]", e, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route("/api/mesa/<int:mesanro>/receber", methods=["POST"])
@login_required
@restaurant_only
def api_mesa_receber(mesanro):
    conn = None
    cur = None
    try:
        data = request.get_json(silent=True) or {}
        pagamentos = data.get("pagamentos") if isinstance(data.get("pagamentos"), list) else []
        pagos = []
        soma = 0.0
        for p in pagamentos:
            if not isinstance(p, dict):
                continue
            forma = str(p.get("forma") or "").strip()
            try:
                valor = float(str(p.get("valor") or 0).replace(",", "."))
            except Exception:
                valor = 0.0
            if not forma or valor <= 0:
                continue
            valor = round(float(valor), 2)
            soma += valor
            pagos.append({"forma": forma, "valor": valor})
        if not pagos:
            return jsonify({"sucesso": False, "erro": "Informe pelo menos uma forma de pagamento com valor."}), 400

        id_cliente = session.get("id_cliente")
        if not id_cliente:
            return jsonify({"sucesso": False, "erro": "Sessão inválida."}), 401

        conn = conectar()
        conn.start_transaction()
        cur = conn.cursor(dictionary=True)

        cur.execute("SHOW COLUMNS FROM pedido_diarios LIKE 'baixa_pagamento'")
        if cur.fetchone() is None:
            cur.execute("ALTER TABLE pedido_diarios ADD COLUMN baixa_pagamento TEXT NULL AFTER formapagamento")
        cur.execute("SHOW COLUMNS FROM pedido_diarios LIKE 'status_mesa'")
        if cur.fetchone() is None:
            cur.execute("ALTER TABLE pedido_diarios ADD COLUMN status_mesa VARCHAR(20) NULL AFTER nropedido")

        cur.execute(
            """
            SELECT
              SUM(COALESCE(preco, 0) * COALESCE(quantidade, 0)) AS subtotal,
              SUM(CASE WHEN UPPER(COALESCE(status_mesa,'')) = 'CONTA' THEN 1 ELSE 0 END) AS conta_count,
              SUM(CASE WHEN UPPER(COALESCE(status_pedido,'')) <> 'ITEM_REMOVIDO' AND UPPER(COALESCE(status_mesa,'')) NOT IN ('CONTA','RECEBIDO') THEN 1 ELSE 0 END) AS outros_ativos
            FROM pedido_diarios
            WHERE origem = 'MESA'
              AND nropedido = %s
              AND id_cliente = %s
              AND UPPER(COALESCE(status_pedido, '')) <> 'ITEM_REMOVIDO'
              AND UPPER(COALESCE(status_mesa, '')) <> 'RECEBIDO'
            """,
            (mesanro, id_cliente),
        )
        row = cur.fetchone() or {}
        subtotal = float(row.get("subtotal") or 0)
        conta_count = int(row.get("conta_count") or 0)
        outros_ativos = int(row.get("outros_ativos") or 0)
        if subtotal <= 0:
            conn.rollback()
            return jsonify({"sucesso": False, "erro": "Mesa sem itens."}), 404
        if conta_count <= 0:
            conn.rollback()
            return jsonify({"sucesso": False, "erro": "Mesa precisa estar em CONTA para receber."}), 409
        if outros_ativos > 0:
            conn.rollback()
            return jsonify({"sucesso": False, "erro": "Mesa não está totalmente em CONTA."}), 409

        cur.execute(
            "SELECT servicomesa FROM configuracao WHERE id_cliente = %s ORDER BY chave DESC LIMIT 1",
            (id_cliente,),
        )
        cfg = cur.fetchone() or {}
        try:
            pct = float(cfg.get("servicomesa") or 0)
        except Exception:
            pct = 0.0
        if pct < 0:
            pct = 0.0
        servico = round(float(subtotal) * (float(pct) / 100.0), 2) if pct else 0.0
        total = round(float(subtotal) + float(servico), 2)

        soma = round(float(soma), 2)
        diff = round(total - soma, 2)
        if diff > 0.01:
            conn.rollback()
            return jsonify({"sucesso": False, "erro": "Valores não fecham com o total da mesa.", "total": total, "somado": soma, "restante": diff}), 400

        troco = round(max(0.0, float(soma) - float(total)), 2)
        usuario = str(session.get("usuario_logado") or "").strip()
        baixa_obj = {
            "v": 1,
            "origem": "MESA",
            "nropedido": int(mesanro),
            "subtotal": round(float(subtotal), 2),
            "servico": servico,
            "total": total,
            "pagamentos": pagos,
            "troco": troco,
            "usuario": usuario,
            "ts": int(time.time()),
        }
        baixa_txt = json.dumps(baixa_obj, ensure_ascii=False)
        if len(pagos) == 1:
            forma_final = str(pagos[0].get("forma") or "").strip()
        else:
            forma_final = "MISTO"

        cur.execute(
            """
            UPDATE pedido_diarios
            SET status_mesa = 'RECEBIDO',
                baixa_pagamento = %s,
                formapagamento = %s
            WHERE origem = 'MESA'
              AND nropedido = %s
              AND id_cliente = %s
              AND UPPER(COALESCE(status_pedido, '')) <> 'ITEM_REMOVIDO'
              AND UPPER(COALESCE(status_mesa, '')) = 'CONTA'
            """,
            (baixa_txt, forma_final, mesanro, id_cliente),
        )
        if cur.rowcount <= 0:
            conn.rollback()
            return jsonify({"sucesso": False, "erro": "Não foi possível atualizar a mesa."}), 500
        conn.commit()
        return jsonify({"sucesso": True})
    except Exception as e:
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        print("[MESA RECEBER ERRO]", e, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

# Endpoint para remover item da mesa
@app.route("/api/mesa/<int:mesanro>/item/<int:item_id>", methods=["DELETE"])
@login_required
@restaurant_only
def remover_item_mesa(mesanro, item_id):
    try:
        id_cliente = session.get('id_cliente')
        print(f"[DEBUG] Removendo item {item_id} da mesa {mesanro} para id_cliente={id_cliente}", flush=True)
        if not id_cliente:
            return jsonify({"sucesso": False, "mensagem": "Sessão inválida."}), 401
        conn = conectar()
        cur = conn.cursor(dictionary=True)
        cur.execute("SHOW COLUMNS FROM pedido_diarios LIKE 'status_mesa'")
        if cur.fetchone() is None:
            cur.execute("ALTER TABLE pedido_diarios ADD COLUMN status_mesa VARCHAR(20) NULL AFTER nropedido")
        cur.execute(
            """
            SELECT 1
            FROM pedido_diarios
            WHERE origem = 'MESA'
              AND nropedido = %s
              AND id_cliente = %s
              AND UPPER(COALESCE(status_mesa, '')) IN ('CONTA', 'RECEBIDO')
            LIMIT 1
            """,
            (mesanro, id_cliente),
        )
        if cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({"sucesso": False, "mensagem": "Mesa está em CONTA e não pode ser alterada."}), 409
        cur.execute(
            """
            SELECT *
            FROM pedido_diarios
            WHERE chave = %s
              AND nropedido = %s
              AND origem = 'MESA'
              AND id_cliente = %s
              AND UPPER(COALESCE(status_pedido, '')) <> 'ITEM_REMOVIDO'
            LIMIT 1
            """,
            (item_id, mesanro, id_cliente)
        )
        item = cur.fetchone()

        if not item:
            cur.close()
            conn.close()
            return jsonify({"sucesso": False, "mensagem": "Item não encontrado ou não pertence a este cliente."}), 404

        nrolancamento = item.get("lancamento") or item.get("nrolancamento")
        status_item = str(item.get("status_pedido") or "AGUARDE").upper()
        if nrolancamento is not None and int(nrolancamento) > 0:
            # Agrupa por lançamento mesmo quando só a coluna `lancamento` está preenchida.
            if status_item == "AGUARDE":
                cur.execute(
                    """
                    DELETE FROM pedido_diarios
                    WHERE origem = 'MESA'
                      AND nropedido = %s
                      AND id_cliente = %s
                      AND COALESCE(nrolancamento, lancamento) = %s
                    """,
                    (mesanro, id_cliente, int(nrolancamento)),
                )
            else:
                cur.execute(
                    """
                    UPDATE pedido_diarios
                    SET status_pedido = 'ITEM_REMOVIDO'
                    WHERE origem = 'MESA'
                      AND nropedido = %s
                      AND id_cliente = %s
                      AND COALESCE(nrolancamento, lancamento) = %s
                    """,
                    (mesanro, id_cliente, int(nrolancamento)),
                )
        else:
            if status_item == "AGUARDE":
                cur.execute(
                    """
                    DELETE FROM pedido_diarios
                    WHERE chave = %s
                      AND origem = 'MESA'
                      AND nropedido = %s
                      AND id_cliente = %s
                    """,
                    (item_id, mesanro, id_cliente)
                )
            else:
                cur.execute(
                    """
                    UPDATE pedido_diarios
                    SET status_pedido = 'ITEM_REMOVIDO'
                    WHERE chave = %s
                      AND origem = 'MESA'
                      AND nropedido = %s
                      AND id_cliente = %s
                    """,
                    (item_id, mesanro, id_cliente)
                )

        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"sucesso": True, "mensagem": "Item removido com sucesso."})

    except Exception as e:
        if "conn" in locals() and conn:
            conn.rollback()
        print(f'[ERRO] ao remover item da mesa: {e}', flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "mensagem": "Erro ao remover item da mesa."}), 500

@app.route("/api/mesa/<int:mesanro>/item/<int:item_id>", methods=["PATCH"])
@login_required
@restaurant_only
def alterar_item_mesa(mesanro, item_id):
    conn = None
    cur = None
    try:
        data = request.get_json(silent=True) or {}
        qtd_raw = data.get("qtd", None)
        obs_item = data.get("obs_item", None)
        dados_item = data.get("dados_item", None)
        if qtd_raw is None and obs_item is None and dados_item is None:
            return jsonify({"sucesso": False, "mensagem": "Nada para atualizar"}), 400
        id_cliente = session.get("id_cliente")
        conn = conectar()
        cur = conn.cursor()
        cur.execute("SHOW COLUMNS FROM pedido_diarios LIKE 'status_mesa'")
        if cur.fetchone() is None:
            cur.execute("ALTER TABLE pedido_diarios ADD COLUMN status_mesa VARCHAR(20) NULL AFTER nropedido")
        cur.execute(
            """
            SELECT 1
            FROM pedido_diarios
            WHERE origem = 'MESA'
              AND nropedido = %s
              AND id_cliente = %s
              AND UPPER(COALESCE(status_mesa, '')) IN ('CONTA', 'RECEBIDO')
            LIMIT 1
            """,
            (mesanro, id_cliente),
        )
        if cur.fetchone():
            return jsonify({"sucesso": False, "mensagem": "Mesa está em CONTA e não pode ser alterada."}), 409
        set_parts = []
        params = []
        if qtd_raw is not None:
            qtd = float(qtd_raw or 0)
            if qtd <= 0:
                return jsonify({"sucesso": False, "mensagem": "Quantidade deve ser maior que zero"}), 400
            set_parts.append("quantidade = %s")
            params.append(qtd)
        if obs_item is not None:
            set_parts.append("obs_item = %s")
            params.append(str(obs_item).strip())
        if dados_item is not None:
            set_parts.append("dados_item = %s")
            params.append(str(dados_item).strip())
        params.extend([item_id, mesanro, id_cliente])
        cur.execute(
            f"""
            UPDATE pedido_diarios
            SET {", ".join(set_parts)}
            WHERE chave = %s
              AND nropedido = %s
              AND origem = 'MESA'
              AND id_cliente = %s
              AND UPPER(COALESCE(status_pedido, '')) <> 'ITEM_REMOVIDO'
            """,
            params,
        )
        conn.commit()
        if cur.rowcount == 0:
            return jsonify({"sucesso": False, "mensagem": "Item não encontrado."}), 404
        return jsonify({"sucesso": True})
    except Exception as e:
        if conn:
            conn.rollback()
        print("[MESA PATCH ITEM ERRO]", e, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "mensagem": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route("/api/mesa/<int:mesanro>/ajuste-item", methods=["POST"])
@login_required
@restaurant_only
def api_mesa_ajuste_item(mesanro):
    conn = None
    cur = None
    try:
        data = request.get_json(silent=True) or {}
        valor = float(data.get("valor") or 0)
        if valor == 0:
            msg = "Valor do ajuste deve ser diferente de zero."
            return jsonify({"sucesso": False, "erro": msg, "mensagem": msg}), 400
        id_cliente = session.get("id_cliente")
        if not id_cliente:
            msg = "Sessão inválida."
            return jsonify({"sucesso": False, "erro": msg, "mensagem": msg}), 401
        conn = conectar()
        conn.start_transaction()
        cur = conn.cursor(dictionary=True)
        cur.execute("SHOW COLUMNS FROM pedido_diarios LIKE 'status_mesa'")
        if cur.fetchone() is None:
            cur.execute("ALTER TABLE pedido_diarios ADD COLUMN status_mesa VARCHAR(20) NULL AFTER nropedido")
        cur.execute(
            """
            SELECT 1
            FROM pedido_diarios
            WHERE origem = 'MESA'
              AND nropedido = %s
              AND id_cliente = %s
              AND UPPER(COALESCE(status_mesa, '')) IN ('CONTA', 'RECEBIDO')
            LIMIT 1
            """,
            (mesanro, id_cliente),
        )
        if cur.fetchone():
            conn.rollback()
            msg = "Mesa está em CONTA e não pode ser alterada."
            return jsonify({"sucesso": False, "erro": msg, "mensagem": msg}), 409
        # Ancoragem: prefere último item que não é ajuste técnico; se só existir ajuste, reutiliza essa linha.
        cur.execute(
            """
            SELECT cod_classe, cod_usuario, status_pedido
            FROM pedido_diarios
            WHERE origem = 'MESA'
              AND nropedido = %s
              AND id_cliente = %s
              AND UPPER(COALESCE(status_pedido, '')) <> 'ITEM_REMOVIDO'
              AND UPPER(TRIM(COALESCE(codigoproduto, ''))) <> 'AJUSTE_TECNICO'
            ORDER BY chave DESC
            LIMIT 1
            """,
            (mesanro, id_cliente),
        )
        base = cur.fetchone()
        if not base:
            cur.execute(
                """
                SELECT cod_classe, cod_usuario, status_pedido
                FROM pedido_diarios
                WHERE origem = 'MESA'
                  AND nropedido = %s
                  AND id_cliente = %s
                  AND UPPER(COALESCE(status_pedido, '')) <> 'ITEM_REMOVIDO'
                ORDER BY chave DESC
                LIMIT 1
                """,
                (mesanro, id_cliente),
            )
            base = cur.fetchone()
        if not base:
            conn.rollback()
            msg = "Mesa vazia: lance pelo menos um item antes da taxa extra ou desconto."
            return jsonify({"sucesso": False, "erro": msg, "mensagem": msg}), 400

        cod_classe = base.get("cod_classe")
        cod_usuario = base.get("cod_usuario")
        if cod_usuario is None:
            id_usuario_sessao = session.get("id_usuario")
            if id_usuario_sessao is not None:
                try:
                    cod_usuario = int(id_usuario_sessao)
                except Exception:
                    cod_usuario = None
        if cod_usuario is None:
            usuario_logado = str(session.get("usuario_logado") or "").strip()
            if usuario_logado:
                cur.execute(
                    "SELECT chave FROM usuarios WHERE usuario = %s AND id_cliente = %s LIMIT 1",
                    (usuario_logado, id_cliente),
                )
                row_u = cur.fetchone() or {}
                cod_usuario = row_u.get("chave")

        status_insert = "ABERTO" if str(base.get("status_pedido") or "").upper() == "ABERTO" else "AGUARDE"
        produto = "TAXA EXTRA" if valor > 0 else "DESCONTO"
        codigoproduto = "AJUSTE_TECNICO"
        classe = "AJUSTE_TECNICO"
        obs_item = str(data.get("descricao") or "").strip()

        cur.execute("SHOW COLUMNS FROM pedido_diarios LIKE 'status_mesa'")
        has_status_mesa_col = cur.fetchone() is not None
        cur.execute("SHOW COLUMNS FROM pedido_diarios LIKE 'lancamento'")
        has_lancamento_col = cur.fetchone() is not None
        if not has_lancamento_col:
            conn.rollback()
            return jsonify({"sucesso": False, "erro": "Coluna lancamento ausente em pedido_diarios."}), 500

        cur.execute(
            """
            DELETE FROM pedido_diarios
            WHERE origem = 'MESA'
              AND nropedido = %s
              AND id_cliente = %s
              AND UPPER(TRIM(COALESCE(codigoproduto, ''))) = 'AJUSTE_TECNICO'
            """,
            (mesanro, id_cliente),
        )

        cur.execute(
            """
            SELECT COALESCE(MAX(COALESCE(lancamento, 0)), 0) AS max_lancamento
            FROM pedido_diarios
            WHERE origem = 'MESA' AND id_cliente = %s AND nropedido = %s
            """,
            (id_cliente, mesanro),
        )
        row_lanc = cur.fetchone() or {}
        lancamento_atual = int(row_lanc.get("max_lancamento") or 0) + 1

        cols = [
            "origem",
            "nropedido",
            "status_pedido",
            "status_comanda",
            "codigoproduto",
            "produto",
            "preco",
            "quantidade",
            "obs_item",
            "classe",
            "cod_classe",
            "cod_usuario",
            "cliente",
            "id_cliente",
            "lancamento",
        ]
        vals = [
            "MESA",
            int(mesanro),
            status_insert,
            "NORMAL",
            codigoproduto,
            produto,
            float(valor),
            1.0,
            obs_item,
            classe,
            cod_classe,
            cod_usuario,
            "",
            id_cliente,
            lancamento_atual,
        ]
        if has_status_mesa_col:
            cols.insert(2, "status_mesa")
            vals.insert(2, "ABERTA")

        placeholders = ", ".join(["%s"] * len(vals))
        cur.execute(
            f"INSERT INTO pedido_diarios ({', '.join(cols)}) VALUES ({placeholders})",
            tuple(vals),
        )
        conn.commit()
        return jsonify({"sucesso": True, "produto": produto, "valor": valor})
    except Exception as e:
        if conn:
            conn.rollback()
        print("[MESA AJUSTE ITEM ERRO]", e, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route("/api/mesa/<int:mesanro>/item/<int:item_id>/obs", methods=["PATCH"])
@login_required
@restaurant_only
def atualizar_obs_item_mesa(mesanro, item_id):
    conn = None
    cur = None
    try:
        data = request.get_json(silent=True) or {}
        obs_item = (data.get("obs_item") or "").strip()
        id_cliente = session.get("id_cliente")
        conn = conectar()
        cur = conn.cursor()
        cur.execute("SHOW COLUMNS FROM pedido_diarios LIKE 'status_mesa'")
        if cur.fetchone() is None:
            cur.execute("ALTER TABLE pedido_diarios ADD COLUMN status_mesa VARCHAR(20) NULL AFTER nropedido")
        cur.execute(
            """
            SELECT 1
            FROM pedido_diarios
            WHERE origem = 'MESA'
              AND nropedido = %s
              AND id_cliente = %s
              AND UPPER(COALESCE(status_mesa, '')) IN ('CONTA', 'RECEBIDO')
            LIMIT 1
            """,
            (mesanro, id_cliente),
        )
        if cur.fetchone():
            return jsonify({"sucesso": False, "mensagem": "Mesa está em CONTA e não pode ser alterada."}), 409
        cur.execute(
            """
            UPDATE pedido_diarios
            SET obs_item = %s
            WHERE chave = %s
              AND nropedido = %s
              AND origem = 'MESA'
              AND id_cliente = %s
              AND UPPER(COALESCE(status_pedido, '')) <> 'ITEM_REMOVIDO'
            """,
            (obs_item, item_id, mesanro, id_cliente)
        )
        conn.commit()
        if cur.rowcount == 0:
            return jsonify({"sucesso": False, "mensagem": "Item não encontrado."}), 404
        return jsonify({"sucesso": True})
    except Exception as e:
        if conn:
            conn.rollback()
        print("[MESA OBS_ITEM ERRO]", e, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "mensagem": "Erro ao salvar observação do item."}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

# Inicialização do servidor Flask
if __name__ == "__main__":
    _tpl = os.path.join(app.root_path, app.template_folder or "templates")
    print("\n" + "=" * 62, flush=True)
    print("[LojaOnline] A arrancar a partir desta pasta:", flush=True)
    print(" ", os.path.abspath(app.root_path), flush=True)
    print("[LojaOnline] Templates (HTML) carregados de:", flush=True)
    print(" ", os.path.abspath(_tpl), flush=True)
    print("[LojaOnline] Menu principal (/) = templates/painel_menu.html", flush=True)
    print("=" * 62 + "\n", flush=True)
    try:
        from datetime import datetime

        _marker = os.path.join(_BASE_DIR, "ultimo_arranque_loja.txt")
        with open(_marker, "w", encoding="utf-8") as _mf:
            _mf.write(
                "Gerado automaticamente ao iniciar app.py nesta pasta.\n"
                "Se o caminho abaixo NAO for a pasta do Cursor, o servidor nao e o mesmo projeto.\n\n"
            )
            _mf.write(f"quando_local={datetime.now().isoformat(timespec='seconds')}\n\n")
            _mf.write(_loja_diagnostico_texto())
            _mf.write("\n")
        print(f"[LojaOnline] Diagnostico gravado em: {_marker}", flush=True)
    except OSError as _e:
        print(f"[LojaOnline] Nao foi possivel gravar ultimo_arranque_loja.txt: {_e}", flush=True)
    bootstrap_schema()
    app.run(host="0.0.0.0", port=2001, debug=Config.FLASK_DEBUG)
