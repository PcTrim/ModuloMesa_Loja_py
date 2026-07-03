"""Wrapper isolado da API uazapi (WhatsApp), multi-loja.

Princípios:
- O token de envio é POR LOJA (tabela whatsapp_config, por id_cliente), não do .env.
- O admintoken (nível servidor) vem do .env e é usado só para criar/gerenciar instâncias.
- Nenhuma função aqui pode quebrar o fluxo do pedido: erros são capturados e retornados
  como {"ok": False, "erro": "..."} e registrados em whatsapp_log.
"""
import threading

import requests

from config import Config
from database import conectar

TIMEOUT_ENVIO = 8
TIMEOUT_INSTANCIA = 20


# ----------------------------------------------------------------------------
# Acesso à configuração por loja (whatsapp_config)
# ----------------------------------------------------------------------------
def obter_config(id_cliente):
    """Retorna a linha de whatsapp_config da loja (dict) ou None."""
    conn = None
    cur = None
    try:
        conn = conectar()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT * FROM whatsapp_config WHERE id_cliente = %s LIMIT 1",
            (id_cliente,),
        )
        return cur.fetchone()
    except Exception as e:
        print("[UAZAPI obter_config ERRO]", e, flush=True)
        return None
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def _salvar_instancia(id_cliente, nome, token, url):
    """Upsert do token/nome/url da instância para a loja."""
    conn = None
    cur = None
    try:
        conn = conectar()
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM whatsapp_config WHERE id_cliente = %s LIMIT 1",
            (id_cliente,),
        )
        row = cur.fetchone()
        if row:
            cur.execute(
                """
                UPDATE whatsapp_config
                   SET instancia_nome = %s, instancia_token = %s, url = %s
                 WHERE id_cliente = %s
                """,
                (nome, token, url, id_cliente),
            )
        else:
            cur.execute(
                """
                INSERT INTO whatsapp_config (id_cliente, instancia_nome, instancia_token, url)
                VALUES (%s, %s, %s, %s)
                """,
                (id_cliente, nome, token, url),
            )
        conn.commit()
        return True
    except Exception as e:
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        print("[UAZAPI _salvar_instancia ERRO]", e, flush=True)
        return False
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def _url_base(cfg=None):
    url = (cfg or {}).get("url") if cfg else None
    url = (url or Config.UZAPI_URL or "").strip().rstrip("/")
    return url


def _token_loja(id_cliente, cfg=None):
    cfg = cfg or obter_config(id_cliente)
    token = (cfg or {}).get("instancia_token") if cfg else None
    # Fallback de desenvolvimento: token único do .env, se existir.
    return (token or Config.UZAPI_TOKEN or "").strip()


# ----------------------------------------------------------------------------
# Util
# ----------------------------------------------------------------------------
def _so_digitos(valor):
    return "".join(ch for ch in str(valor or "") if ch.isdigit())


def normalizar_telefone(numero, ddd_padrao=None):
    """Normaliza para DDI+DDD+numero (ex.: 5589999999999). Retorna '' se inválido."""
    d = _so_digitos(numero)
    if not d:
        return ""
    ddi = _so_digitos(Config.UZAPI_DDI_PADRAO) or "55"
    ddd = _so_digitos(ddd_padrao)
    # Já tem DDI (começa com 55 e tamanho compatível): mantém.
    if d.startswith(ddi) and len(d) >= (len(ddi) + 10):
        return d
    # 10 ou 11 dígitos => DDD + número, falta só o DDI.
    if len(d) in (10, 11):
        return ddi + d
    # 8 ou 9 dígitos => sem DDD; usa DDD padrão da loja se houver.
    if len(d) in (8, 9) and ddd:
        return ddi + ddd + d
    # Caso já venha grande o suficiente, devolve como está.
    if len(d) >= 12:
        return d
    return ""


def _buscar_token_resposta(data):
    """Procura o token da instância em formatos comuns de resposta do /instance/init."""
    if not isinstance(data, dict):
        return None
    for chave in ("token", "instanceToken", "apikey", "hash"):
        if data.get(chave):
            return str(data[chave])
    inst = data.get("instance")
    if isinstance(inst, dict):
        for chave in ("token", "instanceToken", "apikey", "hash"):
            if inst.get(chave):
                return str(inst[chave])
    return None


def _buscar_status_resposta(data):
    """Extrai o estado textual (connected/connecting/disconnected).

    O servidor pode devolver o estado como texto em instance.status OU como
    objeto em status={connected: true, ...}. Tratamos os dois.
    """
    if not isinstance(data, dict):
        return None
    inst = data.get("instance") if isinstance(data.get("instance"), dict) else {}
    s = inst.get("status") or inst.get("state")
    if isinstance(s, str) and s:
        return s
    st = data.get("status")
    if isinstance(st, dict):
        return "connected" if st.get("connected") else "disconnected"
    if isinstance(st, str) and st:
        return st
    state = data.get("state")
    if isinstance(state, str) and state:
        return state
    return None


def _buscar_qr_resposta(data):
    """Procura QR (base64) e paircode em formatos comuns do /instance/connect."""
    qr = None
    paircode = None
    if isinstance(data, dict):
        inst = data.get("instance") if isinstance(data.get("instance"), dict) else {}
        qr = (
            data.get("qrcode")
            or data.get("qrCode")
            or data.get("base64")
            or inst.get("qrcode")
            or inst.get("qrCode")
            or inst.get("base64")
        )
        paircode = data.get("paircode") or data.get("pairCode") or inst.get("paircode") or inst.get("pairCode")
    status = _buscar_status_resposta(data)
    return qr, paircode, status


# ----------------------------------------------------------------------------
# Gestão de instância
# ----------------------------------------------------------------------------
_UZAPI_ENV_HINT = (
    "Configure UZAPI_URL e UZAPI_ADMIN_TOKEN no .env do servidor e reinicie: sudo systemctl restart lojaonline"
)


def criar_instancia(id_cliente, nome):
    """Cria uma instância no servidor (admintoken) e salva o token para a loja."""
    url = _url_base()
    admintoken = (Config.UZAPI_ADMIN_TOKEN or "").strip()
    if not url:
        return {"ok": False, "erro": f"UZAPI_URL não configurada. {_UZAPI_ENV_HINT}"}
    if not admintoken:
        return {"ok": False, "erro": f"UZAPI_ADMIN_TOKEN não configurado no .env. {_UZAPI_ENV_HINT}"}
    try:
        resp = requests.post(
            f"{url}/instance/init",
            json={"name": nome},
            headers={"admintoken": admintoken, "Content-Type": "application/json"},
            timeout=TIMEOUT_INSTANCIA,
        )
        data = _json_seguro(resp)
        if resp.status_code == 429:
            return {"ok": False, "erro": "Limite de instâncias atingido no servidor (429)."}
        if not resp.ok:
            return {"ok": False, "erro": _erro_resposta(resp, data)}
        token = _buscar_token_resposta(data)
        if not token:
            return {"ok": False, "erro": "Instância criada mas token não retornado pela API."}
        _salvar_instancia(id_cliente, nome, token, url)
        return {"ok": True, "token": token}
    except requests.RequestException as e:
        return {"ok": False, "erro": f"Falha de conexão com a uazapi: {e}"}
    except Exception as e:
        return {"ok": False, "erro": str(e)}


def conectar_instancia(id_cliente, phone=None):
    """Gera o QR code (ou paircode) para a instância da loja."""
    cfg = obter_config(id_cliente)
    url = _url_base(cfg)
    token = _token_loja(id_cliente, cfg)
    if not url:
        return {"ok": False, "erro": f"UZAPI_URL não configurada. {_UZAPI_ENV_HINT}"}
    if not token:
        return {"ok": False, "erro": "Esta loja ainda não tem instância. Crie a instância primeiro."}
    try:
        body = {}
        if phone:
            body["phone"] = _so_digitos(phone)
        resp = requests.post(
            f"{url}/instance/connect",
            json=body,
            headers={"token": token, "Content-Type": "application/json"},
            timeout=TIMEOUT_INSTANCIA,
        )
        data = _json_seguro(resp)
        if not resp.ok:
            return {"ok": False, "erro": _erro_resposta(resp, data)}
        qr, paircode, status = _buscar_qr_resposta(data)
        return {"ok": True, "qrcode": qr, "paircode": paircode, "status": status}
    except requests.RequestException as e:
        return {"ok": False, "erro": f"Falha de conexão com a uazapi: {e}"}
    except Exception as e:
        return {"ok": False, "erro": str(e)}


def status_instancia(id_cliente):
    """Consulta o estado da conexão (connected/connecting/disconnected)."""
    cfg = obter_config(id_cliente)
    url = _url_base(cfg)
    token = _token_loja(id_cliente, cfg)
    if not url or not token:
        return {"ok": True, "status": "disconnected", "configurado": bool(token)}
    try:
        resp = requests.get(
            f"{url}/instance/status",
            headers={"token": token},
            timeout=TIMEOUT_ENVIO,
        )
        data = _json_seguro(resp)
        if not resp.ok:
            return {"ok": False, "erro": _erro_resposta(resp, data), "status": "disconnected"}
        return {"ok": True, "status": (_buscar_status_resposta(data) or "disconnected"), "configurado": True}
    except requests.RequestException as e:
        return {"ok": False, "erro": f"Falha de conexão com a uazapi: {e}", "status": "disconnected"}
    except Exception as e:
        return {"ok": False, "erro": str(e), "status": "disconnected"}


def servidor_env_status():
    """Diagnóstico das variáveis uazapi no .env (sem expor tokens)."""
    url = (Config.UZAPI_URL or "").strip().rstrip("/")
    admin = (Config.UZAPI_ADMIN_TOKEN or "").strip()
    host = ""
    if url:
        try:
            from urllib.parse import urlparse

            host = urlparse(url).netloc or url.replace("https://", "").replace("http://", "").split("/")[0]
        except Exception:
            host = url
    return {
        "uzapi_url_ok": bool(url),
        "uzapi_admin_ok": bool(admin),
        "uzapi_token_plataforma_ok": bool((Config.UZAPI_TOKEN or "").strip()),
        "uzapi_url_host": host,
    }


def status_instancia_plataforma():
    """Estado da instância central (UZAPI_TOKEN do .env)."""
    url = _url_base(None)
    token = (Config.UZAPI_TOKEN or "").strip()
    if not url or not token:
        return {"ok": False, "status": "disconnected", "configurado": False, "erro": "Plataforma não configurada."}
    try:
        resp = requests.get(
            f"{url}/instance/status",
            headers={"token": token},
            timeout=TIMEOUT_ENVIO,
        )
        data = _json_seguro(resp)
        if not resp.ok:
            return {
                "ok": False,
                "erro": _erro_resposta(resp, data),
                "status": "disconnected",
                "configurado": True,
            }
        st = (_buscar_status_resposta(data) or "disconnected").lower()
        return {"ok": True, "status": st, "configurado": True, "connected": st == "connected"}
    except requests.RequestException as e:
        return {"ok": False, "erro": f"Falha de conexão com a uazapi: {e}", "status": "disconnected", "configurado": True}
    except Exception as e:
        return {"ok": False, "erro": str(e), "status": "disconnected", "configurado": True}


def desconectar_instancia(id_cliente):
    """Encerra a sessão do WhatsApp (mantém a instância)."""
    cfg = obter_config(id_cliente)
    url = _url_base(cfg)
    token = _token_loja(id_cliente, cfg)
    if not url or not token:
        return {"ok": False, "erro": "Instância não configurada."}
    try:
        resp = requests.post(
            f"{url}/instance/disconnect",
            headers={"token": token},
            timeout=TIMEOUT_INSTANCIA,
        )
        data = _json_seguro(resp)
        if not resp.ok:
            return {"ok": False, "erro": _erro_resposta(resp, data)}
        return {"ok": True}
    except requests.RequestException as e:
        return {"ok": False, "erro": f"Falha de conexão com a uazapi: {e}"}
    except Exception as e:
        return {"ok": False, "erro": str(e)}


# ----------------------------------------------------------------------------
# Envio de mensagem (texto)
# ----------------------------------------------------------------------------
def enviar_texto(id_cliente, telefone, mensagem, evento="manual", ddd_padrao=None):
    """Envia texto pela instância da loja. Nunca lança exceção; retorna {ok, erro}."""
    telefone_norm = normalizar_telefone(telefone, ddd_padrao)
    if not telefone_norm:
        _log(id_cliente, telefone, evento, "erro", "telefone inválido")
        return {"ok": False, "erro": "Telefone inválido."}

    cfg = obter_config(id_cliente)
    url = _url_base(cfg)
    token = _token_loja(id_cliente, cfg)
    if not url or not token:
        _log(id_cliente, telefone_norm, evento, "erro", "instância não configurada")
        return {"ok": False, "erro": "WhatsApp não configurado para esta loja."}

    try:
        resp = requests.post(
            f"{url}/send/text",
            json={"number": telefone_norm, "text": mensagem},
            headers={"token": token, "Content-Type": "application/json"},
            timeout=TIMEOUT_ENVIO,
        )
        data = _json_seguro(resp)
        if not resp.ok:
            erro = _erro_resposta(resp, data)
            _log(id_cliente, telefone_norm, evento, "erro", erro)
            return {"ok": False, "erro": erro}
        _log(id_cliente, telefone_norm, evento, "ok", None)
        return {"ok": True}
    except requests.RequestException as e:
        _log(id_cliente, telefone_norm, evento, "erro", f"conexao: {e}")
        return {"ok": False, "erro": f"Falha de conexão com a uazapi: {e}"}
    except Exception as e:
        _log(id_cliente, telefone_norm, evento, "erro", str(e))
        return {"ok": False, "erro": str(e)}


def enviar_texto_async(id_cliente, telefone, mensagem, evento="manual", ddd_padrao=None):
    """Dispara o envio em thread separada para não travar a resposta HTTP do PDV."""
    def _run():
        try:
            enviar_texto(id_cliente, telefone, mensagem, evento=evento, ddd_padrao=ddd_padrao)
        except Exception as e:  # rede de segurança extra
            print("[UAZAPI enviar_texto_async ERRO]", e, flush=True)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t


def enviar_texto_plataforma(telefone, mensagem, evento="plataforma", id_cliente_log=None):
    """Envia texto pela instância central (Config.UZAPI_URL + UZAPI_TOKEN)."""
    telefone_norm = normalizar_telefone(telefone, None)
    log_cliente = id_cliente_log if id_cliente_log is not None else 0
    if not telefone_norm:
        _log(log_cliente, telefone, evento, "erro", "telefone inválido")
        return {"ok": False, "erro": "Telefone inválido."}

    url = _url_base(None)
    token = (Config.UZAPI_TOKEN or "").strip()
    if not url or not token:
        _log(log_cliente, telefone_norm, evento, "erro", "plataforma não configurada")
        return {"ok": False, "erro": "WhatsApp plataforma não configurado."}

    try:
        resp = requests.post(
            f"{url}/send/text",
            json={"number": telefone_norm, "text": mensagem},
            headers={"token": token, "Content-Type": "application/json"},
            timeout=TIMEOUT_ENVIO,
        )
        data = _json_seguro(resp)
        if not resp.ok:
            erro = _erro_resposta(resp, data)
            _log(log_cliente, telefone_norm, evento, "erro", erro)
            return {"ok": False, "erro": erro}
        _log(log_cliente, telefone_norm, evento, "ok", None)
        return {"ok": True}
    except requests.RequestException as e:
        _log(log_cliente, telefone_norm, evento, "erro", f"conexao: {e}")
        return {"ok": False, "erro": f"Falha de conexão com a uazapi: {e}"}
    except Exception as e:
        _log(log_cliente, telefone_norm, evento, "erro", str(e))
        return {"ok": False, "erro": str(e)}


# ----------------------------------------------------------------------------
# Helpers internos
# ----------------------------------------------------------------------------
def _json_seguro(resp):
    try:
        return resp.json()
    except Exception:
        return {"_raw": (resp.text or "")[:300]}


def _erro_resposta(resp, data):
    if isinstance(data, dict):
        msg = data.get("message") or data.get("erro")
        if isinstance(msg, str) and msg.strip():
            return f"HTTP {resp.status_code}: {msg.strip()}"
        err = data.get("error")
        if isinstance(err, str) and err.strip():
            return f"HTTP {resp.status_code}: {err.strip()}"
        if data.get("_raw"):
            return f"HTTP {resp.status_code}: {data['_raw']}"
    return f"HTTP {resp.status_code}"


def _log(id_cliente, telefone, evento, status, erro):
    conn = None
    cur = None
    try:
        conn = conectar()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO whatsapp_log (id_cliente, telefone, evento, status, erro)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (id_cliente, str(telefone or "")[:40], str(evento or "")[:60], str(status or "")[:20],
             (str(erro)[:500] if erro else None)),
        )
        conn.commit()
    except Exception as e:
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        print("[UAZAPI _log ERRO]", e, flush=True)
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
