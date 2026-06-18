"""Load loja row from dadosloja by tenant."""
from database import conectar


def obter_dados_loja(id_cliente=None):
    """Obtém dados da loja cadastrados na tabela dadosloja.

    Quando id_cliente é informado, filtra por esse tenant; caso contrário usa registro chave=1 (fallback legado).
    """
    dados_padrao = {
        "latitude": -7.0793693,
        "longitude": -41.4687021,
        "nome": "Minha Loja",
        "endereco": "Praça São Pedro",
        "bairro": "Aerolândia",
        "cidade": "Picos - PI",
        "cep": "64600-000",
        "telefone": "",
        "ddd": "89",
        "cnpj": "",
    }
    conn = None
    cursor = None
    try:
        conn = conectar()
        cursor = conn.cursor(dictionary=True)
        if id_cliente:
            cursor.execute("SELECT * FROM dadosloja WHERE id_cliente = %s LIMIT 1", (id_cliente,))
        else:
            cursor.execute("SELECT * FROM dadosloja WHERE chave = 1")
        dados = cursor.fetchone()
        if dados:
            return dados
    except Exception as e:
        print(f"[ERRO] Erro ao obter dados da loja: {e}")
        return dados_padrao
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    return dados_padrao
