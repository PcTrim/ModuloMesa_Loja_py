"""Mesa floor and related APIs."""
import sys
import traceback
import unicodedata

from flask import Blueprint, jsonify, render_template, request, session, url_for

from decorators import login_required, restaurant_only
from database import conectar
from repositories.mesa_repo import fetch_mesa_recent_for_client
from services.dados_loja import obter_dados_loja
from services.retail_catalog import listar_produtos_por_classificacao
from services.financeiro_inadimplencia import FinanceiroBloqueioError, assert_nova_venda_permitida
import time

mesa_shop_bp = Blueprint("mesa_shop", __name__)

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
        cur.execute("SHOW COLUMNS FROM pedido_diarios LIKE 'pessoas_mesa'")
        if cur.fetchone() is None:
            cur.execute("ALTER TABLE pedido_diarios ADD COLUMN pessoas_mesa INT NULL AFTER status_mesa")
        conn.commit()
    except Exception as e:
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        print("[MESA_BP PEDIDO_DIARIOS ERRO]", e, flush=True)
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@mesa_shop_bp.route("/api/mesa-todos")
@login_required
@restaurant_only
def listar_todas_mesas():
    try:
        id_cliente = session.get("id_cliente")
        if not id_cliente:
            return jsonify({"erro": "Sessão sem id_cliente"}), 401
        registros = fetch_mesa_recent_for_client(id_cliente)
        return jsonify({"registros": registros})
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


@mesa_shop_bp.route("/api/salvar-mesa", methods=["POST"])
@login_required
@restaurant_only
def salvar_mesa():
    try:
        data = request.get_json()
        produtos = data.get("produtos", [])
        acrescimo_total = data.get("acrescimo_total")
        id_cliente = session.get("id_cliente")
        mesanro = data.get("nropedido")
        classe = data.get("classe", None)
        if not produtos or not mesanro:
            return jsonify({"sucesso": False, "mensagem": "Produtos ou número da mesa não informados."}), 400
        conn = conectar()
        conn.start_transaction()
        cursor = conn.cursor()
        cursor_class = conn.cursor(dictionary=True)
        cursor.execute("SHOW COLUMNS FROM pedido_diarios LIKE 'status_mesa'")
        has_status_mesa_col = cursor.fetchone() is not None
        cursor.execute(
            """
            SELECT 1
            FROM pedido_diarios
            WHERE origem = 'MESA'
              AND nropedido = %s
              AND id_cliente = %s
              AND UPPER(COALESCE(status_mesa, '')) = 'CONTA'
            LIMIT 1
            """,
            (mesanro, id_cliente),
        )
        if cursor.fetchone():
            conn.rollback()
            return jsonify({"sucesso": False, "mensagem": "Mesa está em CONTA e não pode ser alterada."}), 409
        cursor.execute(
            """
            SELECT 1
            FROM pedido_diarios
            WHERE origem = 'MESA'
              AND nropedido = %s
              AND id_cliente = %s
            LIMIT 1
            """,
            (mesanro, id_cliente),
        )
        mesa_ja_aberta = cursor.fetchone() is not None
        if not mesa_ja_aberta:
            try:
                assert_nova_venda_permitida(id_cliente)
            except FinanceiroBloqueioError as e:
                conn.rollback()
                return jsonify({"sucesso": False, "mensagem": e.message}), 403
        cursor_class.execute(
            "SELECT formadecobrar FROM classificacao WHERE nomeclassificacao = %s AND id_cliente = %s LIMIT 1",
            (classe, id_cliente),
        )
        class_row = cursor_class.fetchone()
        formadecobrar = (
            class_row["formadecobrar"].lower().strip()
            if class_row and class_row.get("formadecobrar")
            else "normal"
        )
        cursor_class.execute(
            "SELECT chave FROM classificacao WHERE nomeclassificacao = %s AND id_cliente = %s LIMIT 1",
            (classe, id_cliente),
        )
        row_cod_classe = cursor_class.fetchone() or {}
        cod_classe = row_cod_classe.get("chave")
        cod_usuario = session.get("id_usuario")
        if cod_usuario is None:
            usuario_logado = str(session.get("usuario_logado") or "").strip()
            if usuario_logado:
                cursor_class.execute(
                    "SELECT chave FROM usuarios WHERE usuario = %s AND id_cliente = %s LIMIT 1",
                    (usuario_logado, id_cliente),
                )
                row_u = cursor_class.fetchone() or {}
                cod_usuario = row_u.get("chave")
        cursor_class.close()
        cursor.execute("SHOW COLUMNS FROM pedido_diarios LIKE 'status_mesa'")
        has_status_mesa_col = cursor.fetchone() is not None
        cursor.execute("SHOW COLUMNS FROM pedido_diarios LIKE 'pessoas_mesa'")
        has_pessoas_mesa_col = cursor.fetchone() is not None
        pessoas_mesa_val = 1
        if has_pessoas_mesa_col:
            cursor.execute(
                """
                SELECT MAX(COALESCE(pessoas_mesa, 0)) AS pessoas_mesa
                FROM pedido_diarios
                WHERE origem = 'MESA' AND id_cliente = %s AND nropedido = %s
                """,
                (id_cliente, mesanro),
            )
            row_pm = cursor.fetchone()
            if row_pm is None:
                pessoas_mesa_val = 1
            elif isinstance(row_pm, dict):
                pessoas_mesa_val = int(row_pm.get("pessoas_mesa") or 0)
            else:
                pessoas_mesa_val = int(row_pm[0] or 0)
            if pessoas_mesa_val <= 0:
                pessoas_mesa_val = 1
        cursor.execute("SHOW COLUMNS FROM pedido_diarios LIKE 'dados_item'")
        has_dados_item_col = cursor.fetchone() is not None
        cursor.execute("SHOW COLUMNS FROM pedido_diarios LIKE 'lancamento'")
        has_lancamento_col = cursor.fetchone() is not None
        if not has_lancamento_col:
            raise RuntimeError("Coluna obrigatória 'lancamento' não encontrada em pedido_diarios.")
        cursor.execute(
            """
            SELECT COALESCE(MAX(COALESCE(lancamento, 0)), 0) AS max_lancamento
            FROM pedido_diarios
            WHERE origem = 'MESA' AND id_cliente = %s AND nropedido = %s
            """,
            (id_cliente, mesanro),
        )
        row_lanc = cursor.fetchone()
        if row_lanc is None:
            lancamento_atual = 0
        elif isinstance(row_lanc, dict):
            lancamento_atual = int(row_lanc.get("max_lancamento") or 0)
        else:
            lancamento_atual = int(row_lanc[0] or 0)

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
            else:
                valor_principal = max(precos) if precos else 0

            try:
                acres = float(str(acrescimo_total or 0).replace(",", "."))
            except Exception:
                acres = 0.0
            if acres:
                valor_principal = round(float(valor_principal) + float(acres), 2)

            lancamento_atual += 1

            for idx, prod in enumerate(produtos):
                nome_original = prod.get("nome")
                prefixo = f"1/{partes} " if partes > 1 else ""
                nome = f"{prefixo}{nome_original}"
                qtd = prod.get("qtd")
                obs_item = (prod.get("obs_item") or "").strip()
                dados_item = (prod.get("dados_item") or "").strip()
                codigoproduto = str(prod.get("codigoproduto") or "").strip()
                preco_gravar = valor_principal if idx == 0 else 0
                cols = ["origem", "nropedido", "status_pedido", "status_comanda", "codigoproduto", "produto", "preco", "quantidade", "obs_item", "classe", "cod_classe", "cod_usuario", "cliente", "id_cliente", "lancamento"]
                vals = ["MESA", mesanro, "AGUARDE", "NORMAL", codigoproduto, nome, preco_gravar, qtd, obs_item, classe, cod_classe, cod_usuario, "", id_cliente, lancamento_atual]
                if has_status_mesa_col:
                    cols.insert(2, "status_mesa")
                    vals.insert(2, "ABERTA")
                if has_pessoas_mesa_col:
                    idx_pm = cols.index("status_comanda")
                    cols.insert(idx_pm, "pessoas_mesa")
                    vals.insert(idx_pm, pessoas_mesa_val)
                if has_dados_item_col:
                    idx_di = cols.index("obs_item") + 1
                    cols.insert(idx_di, "dados_item")
                    vals.insert(idx_di, dados_item)
                placeholders = ", ".join(["%s"] * len(vals))
                cursor.execute(f"INSERT INTO pedido_diarios ({', '.join(cols)}) VALUES ({placeholders})", tuple(vals))
        else:
            for prod in produtos:
                nome = prod.get("nome")
                preco = prod.get("preco")
                qtd = prod.get("qtd")
                codigoproduto = prod.get("codigoproduto")
                obs_item = (prod.get("obs_item") or "").strip()
                dados_item = (prod.get("dados_item") or "").strip()

                try:
                    acres = float(str(acrescimo_total or 0).replace(",", "."))
                except Exception:
                    acres = 0.0
                if acres:
                    try:
                        preco = round(float(preco or 0) + float(acres), 2)
                    except Exception:
                        preco = float(acres)

                lancamento_atual += 1

                cols = ["origem", "nropedido", "status_pedido", "status_comanda", "codigoproduto", "produto", "preco", "quantidade", "obs_item", "classe", "cod_classe", "cod_usuario", "cliente", "id_cliente", "lancamento"]
                vals = ["MESA", mesanro, "AGUARDE", "NORMAL", codigoproduto, nome, preco, qtd, obs_item, classe, cod_classe, cod_usuario, "", id_cliente, lancamento_atual]
                if has_status_mesa_col:
                    cols.insert(2, "status_mesa")
                    vals.insert(2, "ABERTA")
                if has_pessoas_mesa_col:
                    idx_pm = cols.index("status_comanda")
                    cols.insert(idx_pm, "pessoas_mesa")
                    vals.insert(idx_pm, pessoas_mesa_val)
                if has_dados_item_col:
                    idx_di = cols.index("obs_item") + 1
                    cols.insert(idx_di, "dados_item")
                    vals.insert(idx_di, dados_item)
                placeholders = ", ".join(["%s"] * len(vals))
                cursor.execute(f"INSERT INTO pedido_diarios ({', '.join(cols)}) VALUES ({placeholders})", tuple(vals))
        conn.commit()
        return jsonify({"sucesso": True, "mensagem": "Produtos enviados para a mesa com sucesso!"})
    except Exception as e:
        print("[ERRO] ao salvar produtos na mesa:", e, flush=True)
        traceback.print_exc()
        return jsonify({"sucesso": False, "mensagem": str(e)}), 500
    finally:
        if "cursor" in locals() and cursor:
            cursor.close()
        if "conn" in locals() and conn:
            conn.close()


@mesa_shop_bp.route("/mesa_test")
@login_required
@restaurant_only
def mesa_test():
    return render_template("mesa_test.html")


@mesa_shop_bp.route("/mesa")
@login_required
@restaurant_only
def mesa():
    id_cliente = session.get("id_cliente")
    print(f"[LOG] (mesa) id_cliente na sessão: {id_cliente}", flush=True)
    dados_loja = obter_dados_loja(id_cliente)
    nome_fantasia = dados_loja.get("nome", "Minha Loja")
    print(f"[LOG] (mesa) nome_fantasia: {nome_fantasia}", flush=True)
    classificacoes = []
    mesas_com_registro = set()
    config = None
    try:
        conn = conectar()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT * FROM classificacao WHERE id_cliente = %s ORDER BY nomeclassificacao",
            (id_cliente,),
        )
        classificacoes = cur.fetchall()
        cur.execute(
            """
            SELECT DISTINCT nropedido AS mesanro
            FROM pedido_diarios
            WHERE origem = 'MESA'
              AND id_cliente = %s
              AND UPPER(COALESCE(status_pedido, '')) NOT IN ('ITEM_REMOVIDO', 'RECEBIDO')
            """,
            (id_cliente,),
        )
        mesas_rows = cur.fetchall()
        mesas_com_registro = list(set(row["mesanro"] for row in mesas_rows if row.get("mesanro") is not None))
        try:
            cur.execute(
                "SELECT * FROM configuracao WHERE id_cliente = %s ORDER BY chave DESC LIMIT 1",
                (id_cliente,),
            )
            config = cur.fetchone()
            print(f"[LOG] (mesa) configuracao carregada: {config}", flush=True)
        except Exception as e_conf:
            print(f"[ERRO] ao buscar configuracao: {e_conf}", flush=True)
        cur.close()
        conn.close()
    except Exception as e:
        print("[ERRO] ao buscar classificações ou mesas para o carrossel:", e, flush=True)
    return render_template(
        "mesa.html",
        id_cliente=id_cliente,
        nome_fantasia=nome_fantasia,
        classificacoes=classificacoes,
        mesas_com_registro=mesas_com_registro,
        config=config,
    )


@mesa_shop_bp.route("/produtos_por_classificacao/<nome_classificacao>")
@login_required
def produtos_por_classificacao(nome_classificacao):
    sys.stderr.write(
        f"[DEBUG] Entrou na rota /produtos_por_classificacao com nome_classificacao: {nome_classificacao}\n"
    )
    sys.stderr.flush()
    conn = None
    cursor = None
    try:
        print("\n==================== INÍCIO LOG PRODUTOS POR CLASSIFICAÇÃO ====================", flush=True)
        print(
            f"[LOG] nome_classificacao recebido na URL: '{nome_classificacao}' (type: {type(nome_classificacao)})",
            flush=True,
        )
        nome_classificacao_norm = unicodedata.normalize("NFKC", nome_classificacao).strip()
        conn = conectar()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SHOW COLUMNS FROM pedido_diarios LIKE 'dados_item'")
        has_dados_item_col = cursor.fetchone() is not None
        id_cliente = session.get("id_cliente")
        print(f"[LOG] id_cliente na sessão: {id_cliente}", flush=True)
        if not id_cliente:
            print("[ERRO] id_cliente não encontrado na sessão!", flush=True)
            print("==================== FIM LOG PRODUTOS POR CLASSIFICAÇÃO ====================\n", flush=True)
            return jsonify({"erro": "id_cliente não encontrado na sessão"}), 401

        print(
            f"[LOG] Executando SELECT nomeclassificacao, id_cliente FROM classificacao WHERE nomeclassificacao = %s AND id_cliente = %s",
            (nome_classificacao_norm, id_cliente),
            flush=True,
        )
        cursor.execute(
            "SELECT nomeclassificacao, id_cliente FROM classificacao WHERE nomeclassificacao = %s AND id_cliente = %s",
            (nome_classificacao_norm, id_cliente),
        )
        row = cursor.fetchone()
        print(f"[LOG] Resultado do SELECT classificacao: {row}", flush=True)
        if not row:
            print(
                f"[ERRO] Classificação '{nome_classificacao}' não encontrada para o cliente {id_cliente}",
                flush=True,
            )
            print("==================== FIM LOG PRODUTOS POR CLASSIFICAÇÃO ====================\n", flush=True)
            return jsonify(
                {"erro": f"Classificação '{nome_classificacao}' não encontrada para o cliente {id_cliente}"}
            ), 404
        nome_classificacao_db = row["nomeclassificacao"]
        print(f"[LOG] nomeclassificacao encontrada: {nome_classificacao_db}", flush=True)

        produtos = listar_produtos_por_classificacao(cursor, id_cliente, nome_classificacao_db)
        print(f"[LOG] Produtos retornados: {produtos}", flush=True)
        if not produtos:
            cursor.execute("SELECT DISTINCT classe, id_cliente FROM produtos")
            todas_classes = cursor.fetchall()
            print(f"[LOG] Todas as classes e id_cliente existentes: {todas_classes}", flush=True)
        print("==================== FIM LOG PRODUTOS POR CLASSIFICAÇÃO ====================\n", flush=True)
        return jsonify(produtos)
    except Exception as e:
        print("[ERRO] ao buscar produtos por classificação:", e, flush=True)
        traceback.print_exc()
        print("==================== FIM LOG PRODUTOS POR CLASSIFICAÇÃO ====================\n", flush=True)
        return jsonify({"erro": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
