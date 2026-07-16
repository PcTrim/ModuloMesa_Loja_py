"""Configuração de impressão por terminal (PC) — tabela terminal_impressora."""
import getpass
import re
import socket

from database import conectar


def normalize_terminal_id(terminal_id):
    """Normaliza terminal_id recebido do bridge ou da UI."""
    s = re.sub(r"[^A-Z0-9_-]", "", str(terminal_id or "").upper().replace(" ", ""))
    return s[:120] if s else ""


def get_terminal_id():
    """Gera terminal_id local: HOSTNAME-USUARIO (mesma regra do Print Bridge)."""
    host = (socket.gethostname() or "HOST").strip()
    user = (getpass.getuser() or "USER").strip()
    return normalize_terminal_id(f"{host}-{user}")


def load_terminal_config(id_cliente, terminal_id):
    """Lista caminhos configurados para o terminal."""
    tid = normalize_terminal_id(terminal_id)
    if not tid or not id_cliente:
        return []
    conn = None
    cur = None
    try:
        conn = conectar()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT impressora_id, TRIM(COALESCE(caminho_local, '')) AS caminho_local
            FROM terminal_impressora
            WHERE id_cliente = %s AND terminal_id = %s
            ORDER BY impressora_id
            """,
            (int(id_cliente), tid),
        )
        return cur.fetchall() or []
    except Exception as e:
        print("[TERMINAL IMP load ERRO]", e, flush=True)
        return []
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def terminal_is_configured(id_cliente, terminal_id):
    """True se existir ao menos um registro para terminal + loja."""
    tid = normalize_terminal_id(terminal_id)
    if not tid or not id_cliente:
        return False
    conn = None
    cur = None
    try:
        conn = conectar()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT 1 FROM terminal_impressora
            WHERE id_cliente = %s AND terminal_id = %s
            LIMIT 1
            """,
            (int(id_cliente), tid),
        )
        return cur.fetchone() is not None
    except Exception as e:
        print("[TERMINAL IMP configured ERRO]", e, flush=True)
        return False
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def _impressoras_ids_validas(cur, id_cliente, impressora_ids):
    if not impressora_ids:
        return True
    ids = sorted(set(int(i) for i in impressora_ids if int(i) > 0))
    if not ids:
        return True
    placeholders = ", ".join(["%s"] * len(ids))
    cur.execute(
        f"""
        SELECT id FROM impressoras
        WHERE id IN ({placeholders})
          AND (id_cliente = %s OR id_cliente IS NULL)
        """,
        tuple(ids) + (int(id_cliente),),
    )
    found = {int(r[0]) for r in (cur.fetchall() or [])}
    return all(i in found for i in ids)


def _list_logical_printers(cur, id_cliente):
    """Lista (id, nome) das impressoras lógicas da loja."""
    cur.execute("SHOW COLUMNS FROM impressoras LIKE 'id_cliente'")
    has_id_cli = cur.fetchone() is not None
    where_cli = ""
    params = ()
    if has_id_cli:
        where_cli = " WHERE (id_cliente = %s OR id_cliente IS NULL)"
        params = (int(id_cliente),)
    cur.execute(
        f"""
        SELECT id, TRIM(COALESCE(nomedaimpressora, '')) AS nome
        FROM impressoras{where_cli}
        ORDER BY COALESCE(imprenro,0) DESC, nomedaimpressora
        """,
        params,
    )
    out = []
    for row in cur.fetchall() or []:
        try:
            iid = int(row[0] or 0)
        except (TypeError, ValueError):
            continue
        if iid <= 0:
            continue
        out.append((iid, str(row[1] or "").strip() or ("#" + str(iid))))
    return out


def save_terminal_config(id_cliente, terminal_id, itens):
    """Salva caminhos do terminal; exige caminho_local para TODAS as impressoras lógicas."""
    tid = normalize_terminal_id(terminal_id)
    if not tid:
        return False, "terminal_id inválido."
    if not id_cliente:
        return False, "Loja inválida."

    merged = {}
    for raw in itens or []:
        if not isinstance(raw, dict):
            continue
        try:
            iid = int(raw.get("impressora_id") or 0)
        except (TypeError, ValueError):
            continue
        if iid <= 0:
            continue
        merged[iid] = str(raw.get("caminho_local") or "").strip()

    conn = None
    cur = None
    try:
        conn = conectar()
        cur = conn.cursor()
        logical = _list_logical_printers(cur, id_cliente)
        if not logical:
            return False, "Cadastre ao menos uma impressora lógica antes de mapear o terminal."

        faltando = []
        for iid, nome in logical:
            cam = merged.get(iid, "")
            if not cam:
                faltando.append(nome)
        if faltando:
            return False, (
                "Informe o caminho Windows para todas as impressoras neste terminal. Faltando: "
                + ", ".join(faltando)
            )

        if not _impressoras_ids_validas(cur, id_cliente, [iid for iid, _n in logical]):
            return False, "Impressora inválida para esta loja."

        for iid, _nome in logical:
            caminho = merged[iid]
            cur.execute(
                """
                INSERT INTO terminal_impressora
                    (terminal_id, impressora_id, caminho_local, id_cliente)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE caminho_local = VALUES(caminho_local)
                """,
                (tid, int(iid), caminho, int(id_cliente)),
            )
        conn.commit()
        return True, None
    except Exception as e:
        if conn:
            conn.rollback()
        print("[TERMINAL IMP save ERRO]", e, flush=True)
        return False, str(e)
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def get_printer_path(id_cliente, terminal_id, impressora_id):
    """Retorna caminho_local ou None."""
    tid = normalize_terminal_id(terminal_id)
    if not tid or not id_cliente:
        return None
    try:
        iid = int(impressora_id or 0)
    except (TypeError, ValueError):
        return None
    if iid <= 0:
        return None

    conn = None
    cur = None
    try:
        conn = conectar()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT TRIM(COALESCE(caminho_local, '')) AS caminho_local
            FROM terminal_impressora
            WHERE id_cliente = %s AND terminal_id = %s AND impressora_id = %s
            LIMIT 1
            """,
            (int(id_cliente), tid, iid),
        )
        row = cur.fetchone()
        caminho = (row[0] if row else "") or ""
        caminho = str(caminho).strip()
        return caminho or None
    except Exception as e:
        print("[TERMINAL IMP get_printer_path ERRO]", e, flush=True)
        return None
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
