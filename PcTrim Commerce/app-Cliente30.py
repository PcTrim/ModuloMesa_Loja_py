from flask import Flask, render_template, jsonify, request, session, redirect, url_for, make_response, Response
import mysql.connector
import decimal
import traceback
from pprint import pprint
import requests
import math
import sys
import os
import tempfile
import time
from functools import wraps

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
    import win32api
except Exception:
    win32api = None


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "usuario_logado" not in session:
            if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.headers.get("Accept") == "application/json":
                return jsonify({"sucesso": False, "mensagem": "Sessão expirada ou não autenticada."}), 401
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return decorated_function


_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(
    __name__,
    template_folder=os.path.join(_BASE_DIR, "templates"),
    static_folder=os.path.join(_BASE_DIR, "static"),
)
app.secret_key = "novaloja_secret_key_2025_change_in_production"
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = False
app.config["SESSION_COOKIE_DOMAIN"] = None


@app.after_request
def _evitar_cache_html(response):
    """HTML sempre fresco — evita ver layout antigo por cache do navegador."""
    ct = response.headers.get("Content-Type", "")
    if "text/html" in ct:
        response.headers["Cache-Control"] = "no-store, max-age=0, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.route("/api/mesa-todos")
def listar_todas_mesas():
    try:
        conn = conectar()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT * FROM mesa ORDER BY id DESC LIMIT 100")
        registros = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify({"registros": registros})
    except Exception as e:
        return jsonify({"erro": str(e)})


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
    nome_fantasia = "Minha Loja"
    try:
        conn = conectar()
        cur = conn.cursor(dictionary=True)
        if id_cliente:
            cur.execute("SELECT nome FROM dadosloja WHERE id_cliente = %s LIMIT 1", (id_cliente,))
            row = cur.fetchone()
            if row and row.get("nome"):
                nome_fantasia = row["nome"]
        cur.close()
        conn.close()
    except Exception:
        pass
    return render_template(
        "configuracoes.html",
        id_cliente=id_cliente,
        nome_fantasia=nome_fantasia,
    )


@app.route("/configuracoes-dados")
@login_required
def configuracoes_dados():
    return render_template("configuracoes_dados.html")

# Endpoint para salvar produtos enviados para a mesa
@app.route("/api/salvar-mesa", methods=["POST"])
@login_required
def salvar_mesa():
    try:
        data = request.get_json()
        produtos = data.get("produtos", [])
        id_cliente = session.get("id_cliente")
        _ensure_obs_columns()
        mesanro = data.get("nropedido")  # número da mesa selecionada
        classe = data.get("classe", None)
        if not produtos or not mesanro:
            return jsonify({"sucesso": False, "mensagem": "Produtos ou número da mesa não informados."}), 400
        conn = conectar()
        cursor = conn.cursor()
        # Buscar formadecobrar na tabela classificacao usando o nome da classe
        cursor_class = conn.cursor(dictionary=True)
        cursor_class.execute("SELECT formadecobrar FROM classificacao WHERE nomeclassificacao = %s AND id_cliente = %s LIMIT 1", (classe, id_cliente))
        class_row = cursor_class.fetchone()
        formadecobrar = (class_row["formadecobrar"].lower().strip() if class_row and class_row.get("formadecobrar") else "normal")
        cursor_class.close()

        if formadecobrar in ["media", "maior"] and len(produtos) > 1:
            partes = len(produtos)
            precos = []
            for prod in produtos:
                try:
                    precos.append(float(prod.get("preco", 0)))
                except Exception:
                    precos.append(0)
            if formadecobrar == "media":
                valor_principal = round(sum(precos) / partes, 2) if partes > 0 else 0
            else:  # maior
                valor_principal = max(precos) if precos else 0
            
            # Gerar nrolancamento único (timestamp em milissegundos)
            import time
            nrolancamento = int(time.time() * 1000)
            
            # Gerar um identificador único para o multiparte (usando nropedido + classe + timestamp para garantir unicidade)
            codigo_multiparte = f"{mesanro}_{classe}_{nrolancamento}"
            
            for idx, prod in enumerate(produtos):
                nome_original = prod.get("nome")
                prefixo = f"1/{partes} " if partes > 1 else ""
                nome = f"{prefixo}{nome_original}"
                qtd = prod.get("qtd")
                obs_item = (prod.get("obs_item") or "").strip()
                # Usar o identificador único para todas as partes do multiparte
                codigoproduto = codigo_multiparte
                preco_gravar = valor_principal if idx == 0 else 0
                cursor.execute(
                    """
                    INSERT INTO mesa (mesanro, produto, preco, quantidade, codigoproduto, classe, id_cliente, nrolancamento, obs_item)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (mesanro, nome, preco_gravar, qtd, codigoproduto, classe, id_cliente, nrolancamento, obs_item)
                )
        else:
            # Gerar nrolancamento único para cada produto individual
            import time
            
            for prod in produtos:
                nome = prod.get("nome")
                preco = prod.get("preco")
                qtd = prod.get("qtd")
                codigoproduto = prod.get("codigoproduto")
                obs_item = (prod.get("obs_item") or "").strip()
                
                # Cada produto individual tem seu próprio nrolancamento
                nrolancamento = int(time.time() * 1000)
                
                cursor.execute(
                    """
                    INSERT INTO mesa (mesanro, produto, preco, quantidade, codigoproduto, classe, id_cliente, nrolancamento, obs_item)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (mesanro, nome, preco, qtd, codigoproduto, classe, id_cliente, nrolancamento, obs_item)
                )
        conn.commit()
        return jsonify({"sucesso": True, "mensagem": "Produtos enviados para a mesa com sucesso!"})
    except Exception as e:
        print('[ERRO] ao salvar produtos na mesa:', e, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "mensagem": str(e)}), 500
    finally:
        if 'cursor' in locals() and cursor: cursor.close()
        if 'conn' in locals() and conn: conn.close()

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

@app.route("/api/casa/item", methods=["POST"])
@login_required
def api_casa_add_item():
    conn = None
    cur = None
    try:
        data = request.get_json(silent=True) or {}
        nropedido = data.get("nropedido")
        item = data.get("item") or {}
        if not nropedido:
            return jsonify({"sucesso": False, "erro": "nropedido é obrigatório"}), 400
        nome = (item.get("nome") or "").strip()
        if not nome:
            return jsonify({"sucesso": False, "erro": "Nome do item é obrigatório"}), 400

        id_cliente = session.get("id_cliente")
        if not id_cliente:
            return jsonify({"sucesso": False, "erro": "Sessão inválida: id_cliente não encontrado. Faça login novamente."}), 401
        _ensure_obs_columns()
        conn = conectar()
        cur = conn.cursor(dictionary=True)
        valores = (
            int(nropedido),
            (data.get("telefone") or "").strip(),
            (data.get("cep") or "").strip(),
            (data.get("nome") or "").strip(),
            (data.get("endereco") or "").strip(),
            (data.get("nrocasa") or "").strip(),
            (data.get("complemento") or "").strip(),
            nome,
            float(item.get("preco") or 0),
            float(item.get("qtd") or 1),
            str(item.get("codigoproduto") or ""),
            str(item.get("classe") or ""),
            str(item.get("obs_item") or ""),
            str(data.get("obs_geral") or ""),
            (data.get("cliente") or data.get("nome") or "").strip(),
            id_cliente,
        )
        cur.execute(
            """
            INSERT INTO deliverypendente
            (nropedido, telefone, cep, nome, endereco, nrocasa, complemento, produto, preco, quantidade, codigoproduto, classe, obs_item, obs_geral, cliente, id_cliente)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            valores
        )
        novo_id = cur.lastrowid
        conn.commit()
        return jsonify({"sucesso": True, "id": novo_id})
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
        id_cliente = session.get("id_cliente")
        _ensure_obs_columns()
        conn = conectar()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT d.chave, d.nropedido, d.produto, d.preco, d.quantidade, d.codigoproduto, d.classe, d.obs_item, d.obs_geral,
                   IFNULL(p.descricao, '') AS descricao_produto
            FROM deliverypendente d
            LEFT JOIN produtos p ON p.chave = CAST(d.codigoproduto AS UNSIGNED) AND p.id_cliente = d.id_cliente
            WHERE d.nropedido = %s AND d.id_cliente = %s
            ORDER BY chave DESC
            """,
            (nropedido, id_cliente)
        )
        regs = cur.fetchall() or []
        regs = [convert_types(r) for r in regs]
        obs_geral = ""
        if regs:
            obs_geral = (regs[0].get("obs_geral") or "").strip()
        return jsonify({"sucesso": True, "registros": regs, "obs_geral": obs_geral})
    except Exception as e:
        print("[CASA LISTA ERRO]", e, flush=True)
        traceback.print_exc()
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
        if qtd_raw is None and obs_item is None:
            return jsonify({"sucesso": False, "erro": "Nada para atualizar"}), 400
        id_cliente = session.get("id_cliente")
        _ensure_obs_columns()
        conn = conectar()
        cur = conn.cursor()
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
        params.extend([item_id, nropedido, id_cliente])
        cur.execute(
            f"UPDATE deliverypendente SET {', '.join(set_parts)} WHERE chave = %s AND nropedido = %s AND id_cliente = %s",
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
        _ensure_obs_columns()
        conn = conectar()
        cur = conn.cursor()
        cur.execute(
            "UPDATE deliverypendente SET obs_geral = %s WHERE nropedido = %s AND id_cliente = %s",
            (obs_geral, nropedido, id_cliente)
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
        cur.execute(
            "DELETE FROM deliverypendente WHERE chave = %s AND nropedido = %s AND id_cliente = %s",
            (item_id, nropedido, id_cliente)
        )
        conn.commit()
        return jsonify({"sucesso": True, "removidos": cur.rowcount})
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
        cur.execute(
            "DELETE FROM deliverypendente WHERE nropedido = %s AND id_cliente = %s",
            (nropedido, id_cliente)
        )
        conn.commit()
        return jsonify({"sucesso": True, "removidos": cur.rowcount})
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
        conn = conectar()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE deliverypendente
            SET formapagamento = %s
            WHERE nropedido = %s AND id_cliente = %s
            """,
            (forma, nropedido, id_cliente)
        )
        conn.commit()
        if cur.rowcount == 0:
            return jsonify({"sucesso": False, "erro": "Pedido sem itens para definir pagamento"}), 404
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

def _dir_pedidos_salvos_configurado_cli30():
    d = (os.environ.get("LOJA_PEDIDOS_SALVOS_DIR") or "").strip()
    return d if d else r"C:\Geral\Pedidos_Salvos"


def _uniq_base_dirs_candidates_cli30():
    primary = os.path.abspath(_dir_pedidos_salvos_configurado_cli30())
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


def _salvar_txt_pedido_casa_cli30(conteudo, nropedido, forma_pagamento):
    data_dir = time.strftime("%Y-%m-%d")
    sufixo = time.strftime("%H%M%S")
    nome_arquivo = f"pedido_{nropedido or 'sem_numero'}_{sufixo}.txt"
    corpo = str(conteudo or "").strip()
    if forma_pagamento:
        corpo += f"\nFORMA DE PAGAMENTO: {forma_pagamento}\n"
    ultimo = None
    for idx, base_dir in enumerate(_uniq_base_dirs_candidates_cli30()):
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
        caminho, nome_arquivo, usou_fallback = _salvar_txt_pedido_casa_cli30(conteudo, nropedido, forma_pagamento)
        out = {"sucesso": True, "caminho": caminho, "arquivo": nome_arquivo}
        if usou_fallback:
            out["aviso"] = (
                "Não foi possível gravar em C:\\Geral\\Pedidos_Salvos. "
                "Arquivo salvo em pasta alternativa (projeto ou %TEMP%\\LojaOnline_Pedidos_Salvos)."
            )
        return jsonify(out)
    except Exception as e:
        print("[CASA SALVAR TXT ERRO]", e, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "erro": str(e)}), 500

# LOG GLOBAL DE SESSÃO PARA DEPURAÇÃO (forçando log no stderr)
@app.before_request
def log_id_cliente_global():
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

# ROTA DE TESTE MESA
@app.route('/mesa_test')
@login_required
def mesa_test():
    return render_template('mesa_test.html')

# ROTA DA MESA (adicionando id_cliente no render_template)
@app.route('/mesa')
@login_required
def mesa():
    id_cliente = session.get('id_cliente')
    print(f"[LOG] (mesa) id_cliente na sessão: {id_cliente}", flush=True)
    dados_loja = obter_dados_loja()
    nome_fantasia = dados_loja.get('nome', 'Minha Loja')
    print(f"[LOG] (mesa) nome_fantasia: {nome_fantasia}", flush=True)
    # Buscar classificações do cliente
    classificacoes = []
    mesas_com_registro = set()
    config = None
    try:
        conn = conectar()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT * FROM classificacao WHERE id_cliente = %s ORDER BY nomeclassificacao", (id_cliente,))
        classificacoes = cur.fetchall()
        # Buscar mesas com registro
        cur.execute("SELECT DISTINCT mesanro FROM mesa WHERE id_cliente = %s", (id_cliente,))
        mesas_rows = cur.fetchall()
        mesas_com_registro = set(row['mesanro'] for row in mesas_rows if row.get('mesanro') is not None)
        # Buscar configuracao para nromesa e servicomesa
        try:
            cur.execute("SELECT * FROM configuracao WHERE id_cliente = %s ORDER BY chave DESC LIMIT 1", (id_cliente,))
            config = cur.fetchone()
            print(f"[LOG] (mesa) configuracao carregada: {config}", flush=True)
        except Exception as e_conf:
            print(f"[ERRO] ao buscar configuracao: {e_conf}", flush=True)
        cur.close()
        conn.close()
    except Exception as e:
        print('[ERRO] ao buscar classificações ou mesas para o carrossel:', e, flush=True)
    return render_template("mesa.html", id_cliente=id_cliente, nome_fantasia=nome_fantasia, classificacoes=classificacoes, mesas_com_registro=mesas_com_registro, config=config)

@app.route('/produtos_por_classificacao/<nome_classificacao>')
def produtos_por_classificacao(nome_classificacao):
    import sys
    import unicodedata
    sys.stderr.write(f"[DEBUG] Entrou na rota /produtos_por_classificacao com nome_classificacao: {nome_classificacao}\n")
    sys.stderr.flush()
    if 'id_cliente' not in session or not session.get('id_cliente'):
        sys.stderr.write("[ERRO] Sessão não autenticada ou id_cliente ausente ao acessar produtos_por_classificacao\n")
        sys.stderr.flush()
        return jsonify({"erro": "Sessão não autenticada ou id_cliente ausente"}), 401
    sys.stderr.write(f"[LOG][produtos_por_classificacao] Sessão id_cliente: {session.get('id_cliente')}\n")
    sys.stderr.flush()
    sys.stderr.write(f"[LOG][produtos_por_classificacao] Nome classificação recebido: {nome_classificacao}\n")
    sys.stderr.flush()
    conn = None
    cursor = None
    try:
        print("\n==================== INÍCIO LOG PRODUTOS POR CLASSIFICAÇÃO ====================", flush=True)
        print(f"[LOG] nome_classificacao recebido na URL: '{nome_classificacao}' (type: {type(nome_classificacao)})", flush=True)
        nome_classificacao_norm = unicodedata.normalize('NFKC', nome_classificacao).strip()
        conn = conectar()
        cursor = conn.cursor(dictionary=True)
        id_cliente = session.get('id_cliente')
        print(f"[LOG] id_cliente na sessão: {id_cliente}", flush=True)
        if not id_cliente:
            print("[ERRO] id_cliente não encontrado na sessão!", flush=True)
            print("==================== FIM LOG PRODUTOS POR CLASSIFICAÇÃO ====================\n", flush=True)
            return jsonify({"erro": "id_cliente não encontrado na sessão"}), 401

        # Log do select na tabela classificacao
        print(f"[LOG] Executando SELECT nomeclassificacao, id_cliente FROM classificacao WHERE nomeclassificacao = %s AND id_cliente = %s", (nome_classificacao_norm, id_cliente), flush=True)
        cursor.execute("SELECT nomeclassificacao, id_cliente FROM classificacao WHERE nomeclassificacao = %s AND id_cliente = %s", (nome_classificacao_norm, id_cliente))
        row = cursor.fetchone()
        print(f"[LOG] Resultado do SELECT classificacao: {row}", flush=True)
        if not row:
            print(f"[ERRO] Classificação '{nome_classificacao}' não encontrada para o cliente {id_cliente}", flush=True)
            print("==================== FIM LOG PRODUTOS POR CLASSIFICAÇÃO ====================\n", flush=True)
            return jsonify({"erro": f"Classificação '{nome_classificacao}' não encontrada para o cliente {id_cliente}"}), 404
        nome_classificacao_db = row['nomeclassificacao']
        print(f"[LOG] nomeclassificacao encontrada: {nome_classificacao_db}", flush=True)

        # Buscar produtos pela nomeclassificacao
        print(f"[LOG] Executando SELECT chave, produto, preco, descricao FROM produtos WHERE classe = %s AND id_cliente = %s", (nome_classificacao_db, id_cliente), flush=True)
        cursor.execute("SELECT chave, produto AS nome, preco, descricao AS observacao FROM produtos WHERE classe = %s AND id_cliente = %s", (nome_classificacao_db, id_cliente))
        produtos = cursor.fetchall()
        print(f"[LOG] Produtos retornados: {produtos}", flush=True)
        if not produtos:
            cursor.execute("SELECT DISTINCT classe, id_cliente FROM produtos")
            todas_classes = cursor.fetchall()
            print(f"[LOG] Todas as classes e id_cliente existentes: {todas_classes}", flush=True)
        print("==================== FIM LOG PRODUTOS POR CLASSIFICAÇÃO ====================\n", flush=True)
        return jsonify(produtos)
    except Exception as e:
        print('[ERRO] ao buscar produtos por classificação:', e, flush=True)
        traceback.print_exc()
        print("==================== FIM LOG PRODUTOS POR CLASSIFICAÇÃO ====================\n", flush=True)
        return jsonify({"erro": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


# Endpoint para salvar forma de pagamento (deve vir após login_required)
@app.route("/api/salvar-forma-pagamento", methods=["POST"])
@login_required
def salvar_forma_pagamento():
    data = request.get_json()
    forma = data.get("forma", "").strip()
    id_cliente = session.get("id_cliente")
    if not forma:
        return jsonify({"sucesso": False, "mensagem": "Forma de pagamento não informada"}), 400
    try:
        conn = conectar()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO formapagamento (forma, id_cliente) VALUES (%s, %s)", (forma, id_cliente))
        conn.commit()
        return jsonify({"sucesso": True, "mensagem": "Forma de pagamento adicionada com sucesso"})
    except Exception as e:
        return jsonify({"sucesso": False, "mensagem": str(e)}), 500
    finally:
        if 'cursor' in locals() and cursor: cursor.close()
        if 'conn' in locals() and conn: conn.close()

def conectar():
    return mysql.connector.connect(
        host="127.0.0.1",
        user="root",
        password="pctrim",
        port=3307,
        database="loja2001",
        autocommit=True
    )

def obter_dados_loja():
    """Obtém dados da loja cadastrados na tabela dadosloja"""
    conn = None
    cursor = None
    try:
        conn = conectar()
        cursor = conn.cursor(dictionary=True)
        # Se id_cliente for passado como argumento, busca pelo id_cliente
        import inspect
        frame = inspect.currentframe().f_back
        id_cliente = None
        if frame and 'id_cliente' in frame.f_locals:
            id_cliente = frame.f_locals['id_cliente']
        if id_cliente:
            cursor.execute("SELECT * FROM dadosloja WHERE id_cliente = %s LIMIT 1", (id_cliente,))
        else:
            cursor.execute("SELECT * FROM dadosloja WHERE chave = 1")
        dados = cursor.fetchone()
        if dados:
            return dados
    except Exception as e:
        print(f"[ERRO] Erro ao obter dados da loja: {e}")
        return {
            'latitude': -7.0793693,
            'longitude': -41.4687021,
            'nome': 'Minha Loja',
            'endereco': 'Praça São Pedro',
            'bairro': 'Aerolândia',
            'cidade': 'Picos - PI',
            'cep': '64600-000',
            'telefone': '',
            'ddd': '89',
            'cnpj': ''
        }
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

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
    loja = obter_dados_loja()
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

def calcular_taxa_entrega(distancia):
    """Calcula taxa de entrega baseado na distância usando tabela txentrega.
    Se distância for menor que faixa1_d, utiliza faixa1_v (taxa mínima).
    Retorna o valor da taxa ou 0.0 se erro."""
    conn = None
    cursor = None
    try:
        conn = conectar()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM txentrega WHERE chave = 1")
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
    """Converte Decimal para float para que jsonify funcione."""
    if not row:
        return row
    out = {}
    for k, v in row.items():
        if isinstance(v, decimal.Decimal):
            out[k] = float(v)
        else:
            out[k] = v
    return out

# ===================== Impressão =====================

def get_printer_from_db():
    """Obtém o nome da impressora ativa da tabela impressoras (imprenro=1)."""
    conn = None
    cursor = None
    try:
        conn = conectar()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS impressoras (
                id INT AUTO_INCREMENT PRIMARY KEY,
                nomedaimpressora VARCHAR(255) NOT NULL,
                imprenro TINYINT NOT NULL DEFAULT 0
            )
        """)
        cursor.execute("SELECT nomedaimpressora FROM impressoras WHERE imprenro = 1 LIMIT 1")
        row = cursor.fetchone()
        return row[0] if row else None
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
            if len(p) >= 3 and p[2]:
                nomes.append(str(p[2]).strip())
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
        nome = str(printer_name or win32print.GetDefaultPrinter() or "").strip()
        if not nome:
            return False, "Nenhuma impressora disponível no Windows."
        disponiveis = list_installed_printers()
        if disponiveis and nome.lower() not in {x.lower() for x in disponiveis}:
            return False, f"Impressora não encontrada no Windows: {nome}"
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
    """Grava dados do pedido na tabela deliverypendente, incluindo a forma de pagamento se fornecida."""
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
        # Grava um registro por produto
        for prod in produtos:
            prod_nome = prod.get("nome", "")
            prod_preco = float(prod.get("preco", 0))
            prod_qtd = int(prod.get("qtd", 1))
            prod_chave = prod.get("chave", "")
            # Se for taxa de entrega
            if "TAXA ENTREGA" in prod_nome:
                prod_chave = "TXENTREGA"
                prod_classe = "TXENTREGA"
            id_cliente = session.get('id_cliente')
            # Adiciona a coluna formapagamento se existir
            colunas = ["nropedido", "telefone", "cep", "nome", "endereco", "nrocasa", "complemento", "produto", "preco", "quantidade", "codigoproduto", "classe", "cliente", "id_cliente"]
            valores = [
                cliente_data['nropedido'],
                cliente_data['telefone'],
                cliente_data['cep'],
                cliente_data['nome'],
                cliente_data['endereco'],
                cliente_data['nrocasa'],
                cliente_data['complemento'],
                prod_nome,
                prod_preco,
                prod_qtd,
                prod_chave,
                prod_classe,
                cliente_data.get('cliente', cliente_data['nome']),
                id_cliente
            ]
            if forma_pagamento is not None:
                colunas.append("formapagamento")
                valores.append(forma_pagamento)
            sql = f"INSERT INTO deliverypendente ({', '.join(colunas)}) VALUES ({', '.join(['%s']*len(colunas))})"
            cursor.execute(sql, valores)
            conn.commit()
            print(f"[DELIVERY PENDENTE] {prod_nome} (chave: {prod_chave}, classe: {prod_classe}) gravado para {cliente_data['telefone']} | Forma: {forma_pagamento}")
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
    _pm = os.path.join(_BASE_DIR, "templates", "painel_menu.html")
    return "\n".join(
        [
            "LOJA_BUILD=13",
            "rotas_diagnostico=/onde-esta-o-servidor /loja-build /__loja_build",
            f"app_py={os.path.abspath(__file__)}",
            f"cwd={os.getcwd()}",
            f"BASE_DIR={_BASE_DIR}",
            f"template_folder={os.path.abspath(app.template_folder)}",
            f"painel_menu={os.path.abspath(_pm)}",
            f"existe_painel={os.path.isfile(_pm)}",
        ]
    )


@app.route("/onde-esta-o-servidor", methods=["GET"])
def onde_esta_o_servidor():
    return Response(_loja_diagnostico_texto(), mimetype="text/plain; charset=utf-8")


@app.route("/loja-build", methods=["GET"])
@app.route("/__loja_build", methods=["GET"])
def loja_build_info():
    return Response(_loja_diagnostico_texto(), mimetype="text/plain; charset=utf-8")


@app.route("/")
@login_required
def index():
    id_cliente = session.get('id_cliente')
    dados_loja = obter_dados_loja()
    nome_fantasia = dados_loja.get('nome', 'Minha Loja')
    _pm = os.path.join(_BASE_DIR, "templates", "painel_menu.html")
    html = render_template(
        "painel_menu.html",
        id_cliente=id_cliente,
        nome_fantasia=nome_fantasia,
        _painel_template=os.path.abspath(_pm),
    )
    resp = make_response(html)
    resp.headers["X-Loja-Inicio"] = "painel-menu-build-13"
    return resp

@app.route("/login")
def login_page():
    """Splash antes do login; use /login?skip_splash=1 para ir direto ao formulário."""
    if request.args.get("skip_splash") == "1":
        return render_template("login.html", csrf_token="")
    return render_template(
        "splash.html",
        delay_ms=4000,
        redirect_url=url_for("login_page", skip_splash=1),
    )

@app.route("/login", methods=["POST"])
def login():
    """Autentica o usuário usando a tabela usuarios"""
    dados = request.json or {}
    usuario = dados.get("usuario", "").strip()
    senha = dados.get("senha", "").strip()
    
    conn = None
    cursor = None
    try:
        conn = conectar()
        cursor = conn.cursor(dictionary=True)
        
        # Busca o usuário na tabela
        cursor.execute("SELECT * FROM usuarios WHERE usuario = %s AND senha = %s", (usuario, senha))
        usuario_encontrado = cursor.fetchone()
        
        if usuario_encontrado:
            session['usuario_logado'] = usuario
            session['id_cliente'] = usuario_encontrado.get('id_cliente')
            # Verifica se existe dadosloja para este id_cliente
            id_cliente = usuario_encontrado.get('id_cliente')
            conn2 = None
            cursor2 = None
            try:
                conn2 = conectar()
                cursor2 = conn2.cursor(dictionary=True)
                cursor2.execute("SELECT 1 FROM dadosloja WHERE id_cliente = %s LIMIT 1", (id_cliente,))
                dadosloja_existe = cursor2.fetchone()
            finally:
                if cursor2:
                    cursor2.close()
                if conn2:
                    conn2.close()
            if not dadosloja_existe:
                # Redireciona para cadastro de dados da loja
                return jsonify({"sucesso": True, "redirecionar": "/dados-loja", "mensagem": "Complete os dados da loja", "id_cliente": id_cliente})
            return jsonify({"sucesso": True, "mensagem": "Login realizado com sucesso", "id_cliente": id_cliente})
        else:
            return jsonify({"sucesso": False, "erro": "Usuário ou senha incorretos"}), 401
    
    except mysql.connector.Error as db_err:
        print("[DB ERROR LOGIN]", db_err)
        return jsonify({"sucesso": False, "erro": "Erro ao validar login"}), 500
    
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@app.route("/logout")
def logout():
    """Desloga o usuário"""
    session.pop('usuario_logado', None)
    session.pop('id_cliente', None)
    return redirect(url_for('login_page'))

@app.route("/casa")
@login_required
def casa():
    """Página de pedidos (carrossel)"""
    id_cliente = session.get('id_cliente')
    dados_loja = obter_dados_loja()
    nome_fantasia = dados_loja.get('nome', 'Minha Loja')
    _idx = os.path.join(_BASE_DIR, "templates", "index.html")
    return render_template(
        "index.html",
        id_cliente=id_cliente,
        nome_fantasia=nome_fantasia,
        _pedidos_template=os.path.abspath(_idx),
    )

@app.route("/delivery-pendente-view")
@login_required
def delivery_pendente_view():
    """Página para visualizar pedidos pendentes de entrega"""
    id_cliente = session.get('id_cliente')
    dados_loja = obter_dados_loja()
    nome_fantasia = dados_loja.get('nome', 'Minha Loja')
    return render_template("delivery_pendente.html", id_cliente=id_cliente, nome_fantasia=nome_fantasia)

@app.route("/canceladas")
@login_required
def canceladas_view():
    """Página para visualizar pedidos cancelados"""
    id_cliente = session.get('id_cliente')
    dados_loja = obter_dados_loja()
    nome_fantasia = dados_loja.get('nome', 'Minha Loja')
    return render_template("canceladas.html", id_cliente=id_cliente, nome_fantasia=nome_fantasia)

@app.route("/comandas")
@login_required
def comandas_view():
    """Página para visualizar comandas fechadas"""
    id_cliente = session.get('id_cliente')
    dados_loja = obter_dados_loja()
    nome_fantasia = dados_loja.get('nome', 'Minha Loja')
    return render_template("comandas.html", id_cliente=id_cliente, nome_fantasia=nome_fantasia)

@app.route("/cadastrar-produto")
@login_required
def cadastrar_produto_view():
    """Página para cadastrar produtos"""
    id_cliente = session.get('id_cliente')
    dados_loja = obter_dados_loja()
    nome_fantasia = dados_loja.get('nome', 'Minha Loja')
    return render_template("cadastrar_produto.html", id_cliente=id_cliente, nome_fantasia=nome_fantasia)

@app.route("/api/salvar-produto", methods=["POST"])
@login_required
def salvar_produto():
    """Salva um novo produto na tabela de produtos"""
    conn = None
    cursor = None
    try:
        dados = request.json or {}
        produto = dados.get("produto", "").strip()
        preco = dados.get("preco", 0)
        classe = dados.get("classe", "").strip().upper()
        porkilo = dados.get("porkilo", "Nao")
        impressora = dados.get("impressora", 1)
        cfop = dados.get("cfop", "5102")
        ncm = dados.get("ncm", "")
        display = dados.get("display", 0)
        vendaliberada = dados.get("vendaliberada", "Sim")
        descricao = dados.get("descricao", "")
        
        if not classe or not produto:
            return jsonify({"sucesso": False, "erro": "Classe e nome do produto são obrigatórios"}), 400
        
        conn = conectar()
        cursor = conn.cursor()
        
        # Insere o produto (chave é auto_increment)
        id_cliente = session.get('id_cliente')
        cursor.execute("""
            INSERT INTO produtos (produto, preco, classe, porkilo, impressora, cfop, ncm, display, vendaliberada, descricao, id_cliente)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (produto, preco, classe, porkilo, impressora, cfop, ncm, display, vendaliberada, descricao, id_cliente))
        
        conn.commit()
        chave_gerada = cursor.lastrowid
        
        print(f"[PRODUTO CADASTRADO] {produto} (código: {chave_gerada}, classe: {classe})")
        return jsonify({
            "sucesso": True,
            "mensagem": f"Produto '{produto}' cadastrado com sucesso! (Código: {chave_gerada})"
        })
    
    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        return jsonify({"sucesso": False, "erro": "Erro ao salvar produto no banco de dados"}), 500
    
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@app.route("/api/listar-produtos", methods=["GET"])
@login_required
def listar_produtos():
    """Lista todos os produtos cadastrados"""
    conn = None
    cursor = None
    try:
        conn = conectar()
        cursor = conn.cursor(dictionary=True)
        
        id_cliente = session.get('id_cliente')
        cursor.execute("""
            SELECT chave, produto, preco, classe, porkilo, impressora, cfop, ncm, 
                   display, vendaliberada, descricao
            FROM produtos
            WHERE id_cliente = %s
            ORDER BY produto
        """, (id_cliente,))
        
        produtos = cursor.fetchall()
        
        return jsonify({
            "sucesso": True,
            "produtos": produtos
        })
    
    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        return jsonify({"sucesso": False, "erro": "Erro ao listar produtos"}), 500
    
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@app.route("/api/obter-produto/<int:chave>", methods=["GET"])
@login_required
def obter_produto(chave):
    """Obtém dados de um produto específico"""
    conn = None
    cursor = None
    try:
        conn = conectar()
        cursor = conn.cursor(dictionary=True)
        
        id_cliente = session.get('id_cliente')
        cursor.execute("""
            SELECT chave, produto, preco, classe, porkilo, impressora, cfop, ncm, 
                   display, vendaliberada, descricao
            FROM produtos
            WHERE chave = %s AND id_cliente = %s
        """, (chave, id_cliente))
        
        produto = cursor.fetchone()
        
        if produto:
            return jsonify({
                "sucesso": True,
                "produto": produto
            })
        else:
            return jsonify({"sucesso": False, "erro": "Produto não encontrado"}), 404
    
    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        return jsonify({"sucesso": False, "erro": "Erro ao obter produto"}), 500
    
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@app.route("/api/editar-produto/<int:chave>", methods=["PUT"])
@login_required
def editar_produto(chave):
    """Edita um produto existente"""
    conn = None
    cursor = None
    try:
        dados = request.json or {}
        produto = dados.get("produto", "").strip()
        preco = dados.get("preco", 0)
        classe = dados.get("classe", "").strip().upper()
        porkilo = dados.get("porkilo", "Nao")
        impressora = dados.get("impressora", 1)
        cfop = dados.get("cfop", "5102")
        ncm = dados.get("ncm", "")
        display = dados.get("display", 0)
        vendaliberada = dados.get("vendaliberada", "Sim")
        descricao = dados.get("descricao", "")
        
        if not classe or not produto:
            return jsonify({"sucesso": False, "erro": "Classe e nome do produto são obrigatórios"}), 400
        
        conn = conectar()
        cursor = conn.cursor()
        
        id_cliente = session.get('id_cliente')
        cursor.execute("""
            UPDATE produtos 
            SET produto = %s, preco = %s, classe = %s, porkilo = %s, 
                impressora = %s, cfop = %s, ncm = %s, display = %s, 
                vendaliberada = %s, descricao = %s
            WHERE chave = %s AND id_cliente = %s
        """, (produto, preco, classe, porkilo, impressora, cfop, ncm, display, vendaliberada, descricao, chave, id_cliente))
        
        conn.commit()
        
        if cursor.rowcount > 0:
            print(f"[PRODUTO ATUALIZADO] {produto} (código: {chave})")
            return jsonify({
                "sucesso": True,
                "mensagem": f"Produto '{produto}' atualizado com sucesso!"
            })
        else:
            return jsonify({"sucesso": False, "erro": "Produto não encontrado"}), 404
    
    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        return jsonify({"sucesso": False, "erro": "Erro ao editar produto"}), 500
    
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@app.route("/api/excluir-produto/<int:chave>", methods=["DELETE"])
@login_required
def excluir_produto(chave):
    """Exclui um produto"""
    conn = None
    cursor = None
    try:
        conn = conectar()
        cursor = conn.cursor(dictionary=True)
        
        # Primeiro busca o nome do produto
        id_cliente = session.get('id_cliente')
        cursor.execute("SELECT produto FROM produtos WHERE chave = %s AND id_cliente = %s", (chave, id_cliente))
        produto = cursor.fetchone()
        
        if not produto:
            return jsonify({"sucesso": False, "erro": "Produto não encontrado"}), 404
        
        # Exclui o produto
        cursor.execute("DELETE FROM produtos WHERE chave = %s AND id_cliente = %s", (chave, id_cliente))
        conn.commit()
        
        print(f"[PRODUTO EXCLUÍDO] {produto['produto']} (código: {chave})")
        return jsonify({
            "sucesso": True,
            "mensagem": f"Produto '{produto['produto']}' excluído com sucesso!"
        })
    
    except mysql.connector.Error as db_err:
        print("[DB ERROR]", db_err)
        return jsonify({"sucesso": False, "erro": "Erro ao excluir produto"}), 500
    
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

# ========== ENDPOINTS DE ENTREGADOR ==========

@app.route("/cadastrar-entregador")
@login_required
def cadastrar_entregador():
    """Página de cadastro de entregadores"""
    id_cliente = session.get('id_cliente')
    dados_loja = obter_dados_loja()
    nome_fantasia = dados_loja.get('nome', 'Minha Loja')
    return render_template("cadastrar_entregador.html", id_cliente=id_cliente, nome_fantasia=nome_fantasia)

@app.route("/api/salvar-entregador", methods=["POST"])
@login_required
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

@app.route("/api/obter-entregador/<int:chave>", methods=["GET"])
@login_required
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
    dados_loja = obter_dados_loja()
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
        
        if not nomeclassificacao:
            return jsonify({"sucesso": False, "mensagem": "Nome da classificação é obrigatório"}), 400
        
        conn = conectar()
        cursor = conn.cursor()
        
        id_cliente = session.get('id_cliente')
        cursor.execute("""
            INSERT INTO classificacao (nomeclassificacao, quantidadepartes, nrofoto, id_cliente)
            VALUES (%s, %s, %s, %s)
        """, (nomeclassificacao, quantidadepartes, nrofoto, id_cliente))
        
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
            SELECT chave, nomeclassificacao, quantidadepartes, nrofoto, formadecobrar
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
            SELECT chave, nomeclassificacao, quantidadepartes, nrofoto, formadecobrar
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
        
        if not nomeclassificacao:
            return jsonify({"sucesso": False, "mensagem": "Nome da classificação é obrigatório"}), 400
        
        conn = conectar()
        cursor = conn.cursor()
        
        id_cliente = session.get('id_cliente')
        cursor.execute("""
            UPDATE classificacao 
            SET nomeclassificacao = %s, quantidadepartes = %s, nrofoto = %s
            WHERE chave = %s AND id_cliente = %s
        """, (nomeclassificacao, quantidadepartes, nrofoto, chave, id_cliente))
        
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
    dados_loja = obter_dados_loja()
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
        cursor.execute("SELECT * FROM dadosloja WHERE chave = 1")
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
def cadastrar_taxa():
    """Página de cadastro de taxas de entrega"""
    id_cliente = session.get('id_cliente')
    dados_loja = obter_dados_loja()
    nome_fantasia = dados_loja.get('nome', 'Minha Loja')
    return render_template("cadastrar_taxa.html", id_cliente=id_cliente, nome_fantasia=nome_fantasia)

@app.route("/api/dados-loja-info")
@login_required
def dados_loja_info():
    """Retorna informações da loja para exibição"""
    try:
        dados = obter_dados_loja()
        return jsonify({"sucesso": True, "dados": dados})
    except Exception as e:
        print(f"[ERRO] {e}")
        return jsonify({"sucesso": False, "erro": str(e)}), 500

@app.route("/api/salvar-taxa", methods=["POST"])
@login_required
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
        print(f"[BUSCAR CONFIG DEBUG] id_cliente da sessão: {id_cliente} (tipo: {type(id_cliente)})")
        
        cursor.execute("SELECT * FROM configuracao WHERE id_cliente = %s ORDER BY chave DESC LIMIT 1", (id_cliente,))
        config = cursor.fetchone()
        
        print(f"[BUSCAR CONFIG DEBUG] Resultado: {config}")
        
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

@app.route("/imprimir", methods=["POST"])
def imprimir():
    """Endpoint de impressão silenciosa. Resolve nome da impressora pela ordem: parâmetro -> DB -> padrão do Windows.
    Retorna JSON com sucesso/erro e o nome da impressora utilizado.
    """
    dados = request.json or {}
    conteudo = dados.get("conteudo", "")
    printer_param = str(dados.get("printer", "") or "").strip()
    produtos = dados.get("produtos", [])
    origem = (dados.get("origem") or "").strip().lower()
    forma_pagamento = dados.get("forma_pagamento", "")
    copias = int(dados.get("copias", 1))  # Número de cópias a imprimir
    
    print(f"[IMPRESSAO DEBUG] Dados recebidos:")
    print(f"  - copias (raw): {dados.get('copias')}")
    print(f"  - copias (type): {type(dados.get('copias'))}")
    print(f"  - copias (convertido): {copias}")

    # Adiciona forma de pagamento ao conteudo se existir
    if forma_pagamento:
        conteudo += f"FORMA DE PAGAMENTO: {forma_pagamento}\n"
    
    # Adiciona apenas 1 linha em branco para adiantar o papel
    conteudo += "\n"
    
    # Comando de corte será adicionado na função send_to_printer como bytes puros

    # Extrai dados do cliente do conteúdo para gravar em deliverypendente
    if conteudo and produtos and origem != "casa":
        try:
            gravar_delivery_pendente(conteudo, produtos, forma_pagamento)
        except Exception as e:
            print(f"[DELIVERY PENDENTE ERRO] {e}")
            traceback.print_exc()

    # Resolve impressora
    printer_db = str(get_printer_from_db() or "").strip()
    printer_resolved = printer_param or printer_db or (win32print.GetDefaultPrinter() if (sys.platform == "win32" and win32print) else None)
    if printer_param:
        disponiveis = list_installed_printers()
        if disponiveis and printer_param.lower() not in {x.lower() for x in disponiveis}:
            return jsonify({
                "sucesso": False,
                "erro": f"Impressora informada não foi encontrada: {printer_param}",
                "impressoras_disponiveis": disponiveis,
            }), 400

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
        # Se for requisição AJAX/fetch, retorna JSON normalmente
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
            return jsonify({"sucesso": True, "printer": printer_resolved, "copias": copias})
        # Se for requisição normal (form), faz redirect
        return redirect("/")

@app.route("/testar-impressora", methods=["GET"])
def testar_impressora():
    """Envia uma linha de teste para a impressora configurada."""
    printer_param = str(request.args.get("printer", "") or "").strip()
    printer_db = str(get_printer_from_db() or "").strip()
    printer_resolved = printer_param or printer_db or (win32print.GetDefaultPrinter() if (sys.platform == "win32" and win32print) else None)
    print(f"[IMPRESSORA] Nome buscado para impressão: '{printer_resolved}'", flush=True)
    teste = "*** TESTE DE IMPRESSÃO - NOVALOJA ***\r\n"
    ok, err = send_to_printer(teste, printer_resolved)
    if ok:
        return jsonify({"sucesso": True, "printer": printer_resolved})
    else:
        return jsonify({"sucesso": False, "erro": err, "printer": printer_resolved}), 500

@app.route("/api/impressoras-disponiveis", methods=["GET"])
@login_required
def impressoras_disponiveis():
    """Retorna impressoras disponíveis para diagnóstico no frontend."""
    nomes = list_installed_printers()
    default_name = None
    if sys.platform == "win32" and win32print:
        try:
            default_name = win32print.GetDefaultPrinter()
        except Exception:
            default_name = None
    return jsonify({"sucesso": True, "impressoras": nomes, "padrao": default_name})

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
    dados_loja = obter_dados_loja()
    nome_fantasia = dados_loja.get('nome', 'Minha Loja')
    return render_template("visualizar_pedido.html", conteudo=conteudo, id_cliente=id_cliente, nome_fantasia=nome_fantasia)

@app.route("/gerar-pdf", methods=["POST"])
def gerar_pdf():
    """Gera PDF do pedido e salva em c:\\novaloja1\\pedidos\\. Retorna o caminho relativo para download."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        from reportlab.lib.units import mm
        import os
        from datetime import datetime
        
        dados = request.json or {}
        conteudo = dados.get("conteudo", "")
        produtos = dados.get("produtos", [])
        
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
        cursor.execute("SELECT * FROM clientes WHERE telefone = %s AND id_cliente = %s", (telefone, id_cliente))
        resultado = cursor.fetchone()
        cursor.fetchall()

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
def forma_cobrar():
    nome = request.args.get("nome", "")
    conn = None
    cursor = None
    try:
        conn = conectar()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT formadecobrar FROM classificacao WHERE nomeclassificacao = %s", (nome,))
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

@app.route("/numero-pedido-atual", methods=["GET"])
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
def listar_delivery_pendente():
    """Lista todos os registros pendentes de entrega, agrupados por nropedido"""
    conn = None
    cursor = None
    try:
        conn = conectar()
        cursor = conn.cursor(dictionary=True)
        
        # Busca registros agrupados por pedido
        cursor.execute("""
            SELECT 
                MIN(chave) as chave,
                nropedido,
                telefone,
                cep,
                nome,
                endereco,
                nrocasa,
                complemento,
                MAX(entregador) as entregador,
                SUM(CAST(preco AS DECIMAL(10,2))) as total_preco,
                COUNT(*) as total_produtos
            FROM deliverypendente
            WHERE id_cliente = %s
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
        
        conn = conectar()
        cursor = conn.cursor()
        
        # Atualiza o entregador em todos os produtos do pedido
        cursor.execute("""
            UPDATE deliverypendente 
            SET entregador = %s 
            WHERE nropedido = %s
        """, (entregador, nropedido))
        
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
    """Transfere um pedido de deliverypendente para comanda (fecha a comanda)"""
    conn = None
    cursor = None
    try:
        dados = request.json or {}
        nropedido = dados.get("nropedido")
        
        if not nropedido:
            return jsonify({"erro": "Número do pedido é obrigatório"}), 400
        
        conn = conectar()
        cursor = conn.cursor(dictionary=True)
        
        # Verifica se o pedido tem entregador atribuído
        cursor.execute("""
            SELECT entregador 
            FROM deliverypendente 
            WHERE nropedido = %s 
            LIMIT 1
        """, (nropedido,))
        
        resultado = cursor.fetchone()
        
        if not resultado:
            return jsonify({"erro": "Pedido não encontrado"}), 404
        
        entregador = resultado.get('entregador', '')
        
        if not entregador or entregador.strip() == '':
            return jsonify({"erro": "Não é possível fechar a comanda sem atribuir um entregador"}), 400
        
        # Transfere os dados de deliverypendente para comanda
        id_cliente = session.get('id_cliente')
        cursor.execute("""
            INSERT INTO comanda 
            (nropedido, telefone, cep, nome, endereco, nrocasa, complemento, 
             codigoproduto, produto, preco, quantidade, classe, entregador, cliente, id_cliente, formapagamento)
            SELECT nropedido, telefone, cep, nome, endereco, nrocasa, complemento,
                   codigoproduto, produto, preco, quantidade, classe, entregador, cliente, id_cliente, formapagamento
            FROM deliverypendente
            WHERE nropedido = %s AND id_cliente = %s
        """, (nropedido, id_cliente))
        
        registros_transferidos = cursor.rowcount
        
        # Remove os registros de deliverypendente após transferir
        cursor.execute("""
            DELETE FROM deliverypendente 
            WHERE nropedido = %s AND id_cliente = %s
        """, (nropedido, id_cliente))
        
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
    """Transfere um pedido de deliverypendente para canceladas"""
    conn = None
    cursor = None
    try:
        dados = request.json or {}
        nropedido = dados.get("nropedido")
        
        if not nropedido:
            return jsonify({"erro": "Número do pedido é obrigatório"}), 400
        
        conn = conectar()
        cursor = conn.cursor()
        
        # Transfere os dados de deliverypendente para canceladas
        id_cliente = session.get('id_cliente')
        cursor.execute("""
            INSERT INTO canceladas 
            (nropedido, cliente, telefone, nome, cep, endereco, nrocasa, complemento, 
             codigoproduto, produto, preco, quantidade, classe, entregador, id_cliente)
            SELECT nropedido, cliente, telefone, nome, cep, endereco, nrocasa, complemento,
                   codigoproduto, produto, preco, quantidade, classe, entregador, id_cliente
            FROM deliverypendente
            WHERE nropedido = %s AND id_cliente = %s
        """, (nropedido, id_cliente))
        
        registros_transferidos = cursor.rowcount
        
        # Remove os registros de deliverypendente após transferir
        cursor.execute("""
            DELETE FROM deliverypendente 
            WHERE nropedido = %s AND id_cliente = %s
        """, (nropedido, id_cliente))
        
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
            taxa_entrega = calcular_taxa_entrega(distancia_final)
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

@app.route("/api/verificar-delivery-pendente", methods=["GET"])
@login_required
def verificar_delivery_pendente():
    """Verifica se existem registros na tabela deliverypendente, contando apenas pedidos únicos"""
    conn = None
    cursor = None
    try:
        conn = conectar()
        cursor = conn.cursor(dictionary=True)
        
        # Conta registros únicos de pedidos na tabela deliverypendente (agrupado por nropedido)
        id_cliente = session.get('id_cliente')
        cursor.execute("SELECT COUNT(DISTINCT nropedido) as total FROM deliverypendente WHERE id_cliente = %s", (id_cliente,))
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
def limpar_delivery_pendente():
    """Apaga todos os registros da tabela deliverypendente"""
    conn = None
    cursor = None
    try:
        conn = conectar()
        cursor = conn.cursor()
        
        # Obtém o número de pedidos únicos antes de deletar
        cursor.execute("SELECT COUNT(DISTINCT nropedido) as total FROM deliverypendente WHERE id_cliente = %s", (session.get('id_cliente'),))
        resultado = cursor.fetchone()
        pedidos_deletados = resultado[0] if resultado else 0
        # Deleta todos os registros do cliente
        cursor.execute("DELETE FROM deliverypendente WHERE id_cliente = %s", (session.get('id_cliente'),))
        
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
def transferir_comandas_liquidadas():
    """Transfere registros da tabela comanda para liquidada e reseta o contador"""
    conn = None
    cursor = None
    try:
        conn = conectar()
        cursor = conn.cursor()
        
        # Obtém o número de pedidos únicos antes de transferir
        cursor.execute("SELECT COUNT(DISTINCT nropedido) as total FROM comanda")
        resultado = cursor.fetchone()
        pedidos_transferidos = resultado[0] if resultado else 0
        
        if pedidos_transferidos > 0:
            # Insere os registros na tabela liquidada
            id_cliente = session.get('id_cliente')
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
        print(f"[LOG][formas_pagamento_api] id_cliente na sessão: {id_cliente}")
        cursor.execute("SELECT * FROM formapagamento WHERE id_cliente = %s", (id_cliente,))
        formas = cursor.fetchall() or []
        print(f"[LOG][formas_pagamento_api] Formas encontradas: {formas}")
        if not formas:
            print(f"[LOG][formas_pagamento_api] Nenhuma forma encontrada para id_cliente: {id_cliente}")
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
def buscar_mesa(mesanro):
    try:
        id_cliente = session.get('id_cliente')
        print(f"[DEBUG] /api/mesa/<mesanro> chamado com mesanro={mesanro} (type={type(mesanro)}) e id_cliente={id_cliente}", flush=True)
        conn = conectar()
        cur = conn.cursor(dictionary=True)
        if id_cliente:
            query = """
                SELECT m.*, IFNULL(p.descricao, '') AS descricao_produto
                FROM mesa m
                LEFT JOIN produtos p ON p.chave = CAST(m.codigoproduto AS UNSIGNED) AND p.id_cliente = m.id_cliente
                WHERE (m.mesanro = %s OR m.mesanro = %s) AND m.id_cliente = %s 
                ORDER BY m.mesanro DESC
            """
            params = (mesanro, str(mesanro), id_cliente)
        else:
            # Fallback temporário para testes sem sessão: não filtra por id_cliente
            query = """
                SELECT m.*, IFNULL(p.descricao, '') AS descricao_produto
                FROM mesa m
                LEFT JOIN produtos p ON p.chave = CAST(m.codigoproduto AS UNSIGNED) AND p.id_cliente = m.id_cliente
                WHERE (m.mesanro = %s OR m.mesanro = %s)
                ORDER BY m.mesanro DESC
            """
            params = (mesanro, str(mesanro))
        print(f"[DEBUG] Executando query: {query.strip()} com params: {params}", flush=True)
        cur.execute(query, params)
        registros = cur.fetchall()
        print(f"[DEBUG] Registros retornados: {registros}", flush=True)
        cur.close()
        conn.close()
        return jsonify({"sucesso": True, "registros": registros})
    except Exception as e:
        print('[ERRO] ao buscar produtos da mesa:', e, flush=True)
        return jsonify({"sucesso": False, "mensagem": "Erro ao buscar produtos da mesa."}), 500

# Endpoint para remover item da mesa
@app.route("/api/mesa/<int:mesanro>/item/<int:item_id>", methods=["DELETE"])
def remover_item_mesa(mesanro, item_id):
    try:
        id_cliente = session.get('id_cliente')
        print(f"[DEBUG] Removendo item {item_id} da mesa {mesanro} para id_cliente={id_cliente}", flush=True)

        conn = conectar()
        cur = conn.cursor(dictionary=True)

        def coluna_existe(nome_coluna: str) -> bool:
            try:
                cur.execute(
                    """SELECT COUNT(*) AS existe FROM information_schema.columns
                        WHERE table_schema = DATABASE() AND table_name = 'mesa' AND column_name = %s""",
                    (nome_coluna,)
                )
                row = cur.fetchone()
                return bool(row and row.get('existe'))
            except Exception as e:
                print(f"[WARN] Falha ao verificar coluna {nome_coluna}: {e}", flush=True)
                return False

        col_id = 'id' if coluna_existe('id') else 'chave'
        col_mesa = 'mesanro' if coluna_existe('mesanro') else 'nropedido'
        col_cod = 'codigoproduto' if coluna_existe('codigoproduto') else None
        col_prod = 'produto' if coluna_existe('produto') else None
        col_classe = 'classe' if coluna_existe('classe') else None
        tem_id_cliente = coluna_existe('id_cliente')

        # Monta filtro de cliente somente se a coluna existir
        where_cliente = "" if not tem_id_cliente else " AND id_cliente = %s"
        params_base = [item_id, mesanro, str(mesanro)]
        params_cliente = [] if not tem_id_cliente else [id_cliente]

        select_sql = f"""
            SELECT * FROM mesa
            WHERE ({col_id} = %s) AND ({col_mesa} = %s OR {col_mesa} = %s){where_cliente}
        """
        print(f"[DEBUG] SELECT remover_item: {select_sql} params={params_base + params_cliente}", flush=True)
        cur.execute(select_sql, params_base + params_cliente)
        item = cur.fetchone()

        if not item:
            cur.close()
            conn.close()
            return jsonify({"sucesso": False, "mensagem": "Item não encontrado ou não pertence a este cliente."}), 404

        # Debug: Mostrar o item encontrado
        print(f"[DEBUG] Item encontrado: {item}", flush=True)

        # SOLUÇÃO COM NROLANCAMENTO:
        # Se o item tem nrolancamento, remover todos os itens com o mesmo número
        # Isso agrupa produtos de múltipla escolha (ex: pizza com vários sabores)
        
        nrolancamento = item.get('nrolancamento')
        print(f"[DEBUG] nrolancamento do item: {nrolancamento}", flush=True)
        
        if nrolancamento is not None and nrolancamento > 0:
            # Verificar quantos itens têm o mesmo nrolancamento
            count_sql = f"SELECT COUNT(*) as total FROM mesa WHERE nrolancamento = %s"
            count_params = [nrolancamento]
            if tem_id_cliente:
                count_sql += " AND id_cliente = %s"
                count_params.append(id_cliente)
            
            print(f"[DEBUG] COUNT SQL: {count_sql} params={count_params}", flush=True)
            cur.execute(count_sql, count_params)
            qtd_items = cur.fetchone()['total']
            print(f"[DEBUG] Quantidade de itens com nrolancamento={nrolancamento}: {qtd_items}", flush=True)
            
            if qtd_items > 1:
                # Múltipla escolha - deletar todos com mesmo nrolancamento
                delete_sql = f"DELETE FROM mesa WHERE nrolancamento = %s"
                delete_params = [nrolancamento]
                if tem_id_cliente:
                    delete_sql += " AND id_cliente = %s"
                    delete_params.append(id_cliente)
                print(f"[DEBUG] DELETE multiparte (nrolancamento): {delete_sql} params={delete_params}", flush=True)
                cur.execute(delete_sql, delete_params)
                print(f"[DEBUG] Linhas deletadas (multiparte): {cur.rowcount}", flush=True)
            else:
                # Apenas 1 item com esse nrolancamento - deletar por ID
                delete_sql = f"DELETE FROM mesa WHERE {col_id} = %s"
                delete_params = [item_id]
                if tem_id_cliente:
                    delete_sql += " AND id_cliente = %s"
                    delete_params.append(id_cliente)
                print(f"[DEBUG] DELETE único (ID): {delete_sql} params={delete_params}", flush=True)
                cur.execute(delete_sql, delete_params)
                print(f"[DEBUG] Linhas deletadas (único): {cur.rowcount}", flush=True)
        else:
            # Sem nrolancamento - deletar apenas por ID
            delete_sql = f"DELETE FROM mesa WHERE {col_id} = %s"
            delete_params = [item_id]
            if tem_id_cliente:
                delete_sql += " AND id_cliente = %s"
                delete_params.append(id_cliente)
            print(f"[DEBUG] DELETE sem nrolancamento: {delete_sql} params={delete_params}", flush=True)
            cur.execute(delete_sql, delete_params)
            print(f"[DEBUG] Linhas deletadas: {cur.rowcount}", flush=True)
        
        conn.commit()
        print(f"[DEBUG] Remoção concluída com sucesso.", flush=True)

        cur.close()
        conn.close()

        return jsonify({"sucesso": True, "mensagem": "Item removido com sucesso."})

    except Exception as e:
        print(f'[ERRO] ao remover item da mesa: {e}', flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "mensagem": "Erro ao remover item da mesa."}), 500

@app.route("/api/mesa/<int:mesanro>/item/<int:item_id>/obs", methods=["PATCH"])
@login_required
def atualizar_obs_item_mesa(mesanro, item_id):
    conn = None
    cur = None
    try:
        data = request.get_json(silent=True) or {}
        obs_item = (data.get("obs_item") or "").strip()
        id_cliente = session.get("id_cliente")
        _ensure_obs_columns()
        conn = conectar()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE mesa
            SET obs_item = %s
            WHERE chave = %s AND (mesanro = %s OR mesanro = %s) AND id_cliente = %s
            """,
            (obs_item, item_id, mesanro, str(mesanro), id_cliente)
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
    print("[LojaOnline / Cliente30] Pasta do app:", flush=True)
    print(" ", os.path.abspath(app.root_path), flush=True)
    print("[LojaOnline / Cliente30] Templates (HTML):", flush=True)
    print(" ", os.path.abspath(_tpl), flush=True)
    print("[LojaOnline / Cliente30] Menu (/) = templates/painel_menu.html", flush=True)
    print("=" * 62 + "\n", flush=True)
    try:
        from datetime import datetime

        _marker = os.path.join(_BASE_DIR, "ultimo_arranque_loja.txt")
        with open(_marker, "w", encoding="utf-8") as _mf:
            _mf.write(
                "Gerado ao iniciar app-Cliente30.py nesta pasta.\n"
                "Se o caminho NAO for a pasta do Cursor, nao e o mesmo projeto.\n\n"
            )
            _mf.write(f"quando_local={datetime.now().isoformat(timespec='seconds')}\n\n")
            _mf.write(_loja_diagnostico_texto())
            _mf.write("\n")
        print(f"[Cliente30] Diagnostico gravado em: {_marker}", flush=True)
    except OSError as _e:
        print(f"[Cliente30] Nao foi possivel gravar ultimo_arranque_loja.txt: {_e}", flush=True)
    _ensure_obs_columns()
    app.run(host="0.0.0.0", port=2001, debug=True)

