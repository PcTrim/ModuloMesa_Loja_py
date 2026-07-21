"""Shared helpers: geo, taxa, printing, delivery persistence."""
import decimal
import math
import re
import sys
import unicodedata

import mysql.connector
import requests
from flask import session

from database import conectar
from services.dados_loja import obter_dados_loja

try:
    import win32print
    import win32api
except Exception:
    win32print = None
    win32api = None


DISTANCIA_COLISAO_METROS = 50


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(R * c, 2)


def normalizar_campo_endereco(valor):
    s = str(valor or "").strip().lower()
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalizar_cep(valor):
    digits = re.sub(r"\D", "", str(valor or ""))
    return digits if len(digits) == 8 else ""


def equivalente_se_ambos_presentes(valor_novo, valor_antigo):
    a = normalizar_campo_endereco(valor_novo)
    b = normalizar_campo_endereco(valor_antigo)
    if not a or not b:
        return True
    return a == b


def endereco_geo_inalterado(dados_novos, cliente_existente):
    if not cliente_existente:
        return False
    cep_novo = normalizar_cep(dados_novos.get("cep"))
    cep_antigo = normalizar_cep(cliente_existente.get("cep"))
    if cep_novo == "" or cep_antigo == "":
        return False
    if cep_novo != cep_antigo:
        return False
    if normalizar_campo_endereco(dados_novos.get("endereco")) != normalizar_campo_endereco(
        cliente_existente.get("endereco")
    ):
        return False
    if normalizar_campo_endereco(dados_novos.get("nrocasa")) != normalizar_campo_endereco(
        cliente_existente.get("nrocasa")
    ):
        return False
    if not equivalente_se_ambos_presentes(dados_novos.get("cidade"), cliente_existente.get("cidade")):
        return False
    if not equivalente_se_ambos_presentes(dados_novos.get("estado"), cliente_existente.get("estado")):
        return False
    return True


def montar_endereco_geocode(dados):
    end = (dados.get("endereco") or "").strip()
    nro = (dados.get("nrocasa") or "").strip()
    bairro = (dados.get("bairro") or "").strip()
    cidade = (dados.get("cidade") or "").strip()
    uf = (dados.get("estado") or "").strip()
    cep = normalizar_cep(dados.get("cep"))
    partes = []
    if end and nro:
        partes.append(f"{end}, {nro}")
    elif end:
        partes.append(end)
    elif nro:
        partes.append(nro)
    if bairro:
        partes.append(bairro)
    if cidade and uf:
        partes.append(f"{cidade} - {uf}")
    elif cidade:
        partes.append(cidade)
    elif uf:
        partes.append(uf)
    if cep:
        partes.append(f"{cep[:5]}-{cep[5:]}")
    partes.append("Brasil")
    return ", ".join(partes)


def geocodificar(endereco):
    if not endereco or len(endereco.strip()) < 5:
        return None, None
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": endereco, "format": "json", "limit": 1, "countrycodes": "br"}
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
        dist_m = routes[0].get("distance")
        if dist_m is None:
            return None
        return round(dist_m / 1000.0, 2)
    except Exception as e:
        print("[OSRM ERRO]", e)
        return None


def coords_em_colisao(lat_loja, lon_loja, lat_cli, lon_cli):
    if None in (lat_loja, lon_loja, lat_cli, lon_cli):
        return False
    try:
        dist_m = haversine_km(lat_loja, lon_loja, lat_cli, lon_cli) * 1000
        return dist_m <= DISTANCIA_COLISAO_METROS
    except Exception:
        return False


def enderecos_textuais_diferentes(dados_cliente, dados_loja):
    rua_cli = normalizar_campo_endereco(dados_cliente.get("endereco"))
    rua_loja = normalizar_campo_endereco(dados_loja.get("endereco"))
    nro_cli = normalizar_campo_endereco(dados_cliente.get("nrocasa"))
    nro_loja = normalizar_campo_endereco(dados_loja.get("nrocasa") or "")
    if rua_cli != rua_loja:
        return True
    if nro_cli != nro_loja:
        return True
    return False


def resolver_distancia_km(loja_lat, loja_lon, lat_cli, lon_cli, dados_cliente, dados_loja):
    dist_osrm = distancia_osrm_km(loja_lat, loja_lon, lat_cli, lon_cli)
    if dist_osrm is not None and dist_osrm > 0:
        return dist_osrm, "osrm"
    if dist_osrm is None:
        return 0, "falha_osrm"
    if coords_em_colisao(loja_lat, loja_lon, lat_cli, lon_cli) and enderecos_textuais_diferentes(
        dados_cliente, dados_loja
    ):
        dist_hav = haversine_km(loja_lat, loja_lon, lat_cli, lon_cli)
        if dist_hav > 0:
            return dist_hav, "haversine_correcao"
    return 0, "osrm"


def _aviso_precisao_endereco(dados):
    if not str(dados.get("nrocasa") or "").strip():
        return "Endereço sem número — distância pode ser imprecisa."
    return None


def _coords_salvas_validas(cliente_existente):
    if not cliente_existente:
        return None, None
    try:
        lat = cliente_existente.get("lat_cliente")
        lon = cliente_existente.get("lon_cliente")
        if lat is None or lon is None:
            return None, None
        return float(lat), float(lon)
    except (TypeError, ValueError):
        return None, None


def calcular_distancia_cliente(dados, id_cliente=None, cliente_existente=None):
    """Calcula distância entre a loja e o cliente usando dados cadastrados."""
    loja = obter_dados_loja(id_cliente)
    loja_lat = loja["latitude"]
    loja_lon = loja["longitude"]
    aviso_precisao = _aviso_precisao_endereco(dados)

    lat_cli = lon_cli = None
    if endereco_geo_inalterado(dados, cliente_existente):
        lat_cli, lon_cli = _coords_salvas_validas(cliente_existente)

    if lat_cli is None or lon_cli is None:
        endereco_str = montar_endereco_geocode(dados)
        lat_cli, lon_cli = geocodificar(endereco_str)
        if lat_cli is None or lon_cli is None:
            return {
                "distancia": 0,
                "lat_cli": None,
                "lon_cli": None,
                "origem_calculo": "falha_geocode",
                "aviso_precisao": aviso_precisao,
            }

    distancia, origem_calculo = resolver_distancia_km(
        loja_lat, loja_lon, lat_cli, lon_cli, dados, loja
    )
    return {
        "distancia": distancia,
        "lat_cli": lat_cli,
        "lon_cli": lon_cli,
        "origem_calculo": origem_calculo,
        "aviso_precisao": aviso_precisao,
    }


def calcular_taxa_entrega(distancia):
    """Calcula taxa de entrega baseado na distância usando tabela txentrega."""
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

        faixa_1_d = faixa.get("faixa1_d")
        faixa_1_v = faixa.get("faixa1_v")

        if faixa_1_d is not None and distancia < faixa_1_d:
            taxa = float(faixa_1_v) if faixa_1_v is not None else 0.0
            print(
                f"[TAXA ENTREGA] Distância {distancia}km é menor que faixa1_d ({faixa_1_d}km), retornando taxa mínima: R$ {taxa}"
            )
            return taxa

        for i in range(1, 11):
            faixa_d = faixa.get(f"faixa{i}_d")
            faixa_v = faixa.get(f"faixa{i}_v")

            if faixa_d is not None and distancia <= faixa_d:
                taxa = float(faixa_v) if faixa_v is not None else 0.0
                print(f"[TAXA ENTREGA] Distância {distancia}km cai na faixa {i}: R$ {taxa}")
                return taxa

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


def get_printer_from_db():
    """Obtém o nome da impressora ativa da tabela impressoras (imprenro=1)."""
    conn = None
    cursor = None
    try:
        conn = conectar()
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS impressoras (
                id INT AUTO_INCREMENT PRIMARY KEY,
                nomedaimpressora VARCHAR(255) NOT NULL,
                imprenro TINYINT NOT NULL DEFAULT 0
            )
        """
        )
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


def send_to_printer(conteudo, printer_name=None, marca_impressora=None):
    """Envia texto RAW para impressora no Windows."""
    if sys.platform != "win32" or win32print is None:
        return False, "Impressão silenciosa disponível apenas no Windows (pywin32)."
    try:
        nome = printer_name or win32print.GetDefaultPrinter()
        hPrinter = win32print.OpenPrinter(nome)
        try:
            hJob = win32print.StartDocPrinter(hPrinter, 1, ("Pedido", None, "RAW"))
            try:
                win32print.StartPagePrinter(hPrinter)
                if isinstance(conteudo, bytes):
                    data = conteudo
                else:
                    reset = b"\x1B\x40\x1B\x21\x00\x1D\x21\x00"
                    data = reset + str(conteudo).encode("cp1252", errors="replace")
                    data += reset
                    data += b"\x1B\x64\x03"
                    if marca_impressora:
                        marca = marca_impressora.strip().lower()
                        if "bematech" in marca or "daruma" in marca:
                            data += b"\x1B\x6D"
                        elif "epson" in marca:
                            data += b"\x1B\x69"
                        elif "elgin" in marca or "tanca" in marca or "diebold" in marca:
                            data += b"\x1D\x56\x00"
                        else:
                            data += b"\x1B\x6D"
                    else:
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
    """Grava dados do pedido na tabela deliverypendente."""
    conn = None
    cursor = None
    try:
        linhas = conteudo.split("\n")
        cliente_data = {
            "telefone": "",
            "cep": "",
            "nome": "",
            "endereco": "",
            "nrocasa": "",
            "complemento": "",
            "nropedido": 0,
        }
        for linha in linhas:
            if linha.startswith("Tel:"):
                cliente_data["telefone"] = linha.replace("Tel:", "").strip()
            elif linha.startswith("CEP:"):
                cliente_data["cep"] = linha.replace("CEP:", "").strip()
            elif linha.startswith("Nome:"):
                cliente_data["nome"] = linha.replace("Nome:", "").strip()
            elif linha.startswith("Compl:"):
                cliente_data["complemento"] = linha.replace("Compl:", "").strip()
            elif linha.startswith("End:"):
                end_info = linha.replace("End:", "").strip()
                partes = end_info.split(",")
                if len(partes) >= 1:
                    cliente_data["endereco"] = partes[0].strip()
                if len(partes) >= 2:
                    cliente_data["nrocasa"] = partes[1].strip()
            elif "PEDIDO NRO:" in linha:
                nro_str = linha.replace("PEDIDO NRO:", "").strip()
                try:
                    cliente_data["nropedido"] = int(nro_str)
                except Exception:
                    cliente_data["nropedido"] = 0
        if not cliente_data["telefone"]:
            print("[DELIVERY PENDENTE] Sem telefone, não gravando")
            return
        conn = conectar()
        cursor = conn.cursor(dictionary=True)
        for prod in produtos:
            prod_nome = prod.get("nome", "")
            prod_preco = float(prod.get("preco", 0))
            prod_qtd = int(prod.get("qtd", 1))
            prod_chave = prod.get("chave", "")
            prod_classe = prod.get("classe", "")
            if "TAXA ENTREGA" in prod_nome:
                prod_chave = "TXENTREGA"
                prod_classe = "TXENTREGA"
            id_cliente = session.get("id_cliente")
            colunas = [
                "nropedido",
                "telefone",
                "cep",
                "nome",
                "endereco",
                "nrocasa",
                "complemento",
                "produto",
                "preco",
                "quantidade",
                "codigoproduto",
                "classe",
                "cliente",
                "id_cliente",
            ]
            valores = [
                cliente_data["nropedido"],
                cliente_data["telefone"],
                cliente_data["cep"],
                cliente_data["nome"],
                cliente_data["endereco"],
                cliente_data["nrocasa"],
                cliente_data["complemento"],
                prod_nome,
                prod_preco,
                prod_qtd,
                prod_chave,
                prod_classe,
                cliente_data.get("cliente", cliente_data["nome"]),
                id_cliente,
            ]
            if forma_pagamento is not None:
                colunas.append("formapagamento")
                valores.append(forma_pagamento)
            sql = f"INSERT INTO deliverypendente ({', '.join(colunas)}) VALUES ({', '.join(['%s'] * len(colunas))})"
            cursor.execute(sql, valores)
            conn.commit()
            print(
                f"[DELIVERY PENDENTE] {prod_nome} (chave: {prod_chave}, classe: {prod_classe}) gravado para {cliente_data['telefone']} | Forma: {forma_pagamento}"
            )
    except Exception as e:
        print(f"[DELIVERY PENDENTE ERRO] {e}")
        raise
    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass
