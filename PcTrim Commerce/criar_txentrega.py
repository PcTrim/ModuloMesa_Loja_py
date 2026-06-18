import mysql.connector

conn = mysql.connector.connect(
    host='127.0.0.1', 
    port=3307, 
    user='root',
    password='pctrim',
    database='loja2001'
)
cursor = conn.cursor()

# Cria tabela txentrega
sql_create = """
CREATE TABLE IF NOT EXISTS txentrega (
    chave INT PRIMARY KEY,
    faixa1_d DECIMAL(10,2) DEFAULT NULL,
    faixa1_v DECIMAL(10,2) DEFAULT NULL,
    faixa2_d DECIMAL(10,2) DEFAULT NULL,
    faixa2_v DECIMAL(10,2) DEFAULT NULL,
    faixa3_d DECIMAL(10,2) DEFAULT NULL,
    faixa3_v DECIMAL(10,2) DEFAULT NULL,
    faixa4_d DECIMAL(10,2) DEFAULT NULL,
    faixa4_v DECIMAL(10,2) DEFAULT NULL,
    faixa5_d DECIMAL(10,2) DEFAULT NULL,
    faixa5_v DECIMAL(10,2) DEFAULT NULL,
    faixa6_d DECIMAL(10,2) DEFAULT NULL,
    faixa6_v DECIMAL(10,2) DEFAULT NULL,
    faixa7_d DECIMAL(10,2) DEFAULT NULL,
    faixa7_v DECIMAL(10,2) DEFAULT NULL,
    faixa8_d DECIMAL(10,2) DEFAULT NULL,
    faixa8_v DECIMAL(10,2) DEFAULT NULL,
    faixa9_d DECIMAL(10,2) DEFAULT NULL,
    faixa9_v DECIMAL(10,2) DEFAULT NULL,
    faixa10_d DECIMAL(10,2) DEFAULT NULL,
    faixa10_v DECIMAL(10,2) DEFAULT NULL,
    data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

cursor.execute(sql_create)
print("Tabela txentrega criada!")

# Insere valores padrão
sql_insert = """
INSERT INTO txentrega (chave, faixa1_d, faixa1_v, faixa2_d, faixa2_v, faixa3_d, faixa3_v, 
                       faixa4_d, faixa4_v, faixa5_d, faixa5_v, faixa6_d, faixa6_v, 
                       faixa7_d, faixa7_v, faixa8_d, faixa8_v, faixa9_d, faixa9_v, 
                       faixa10_d, faixa10_v)
VALUES (1, 3.00, 5.00, 5.00, 8.00, 8.00, 10.00, 10.00, 12.00, 12.00, 15.00, 
        15.00, 18.00, 18.00, 20.00, 20.00, 25.00, 25.00, 30.00, 30.00, 35.00)
ON DUPLICATE KEY UPDATE chave = chave
"""

cursor.execute(sql_insert)
conn.commit()
print("Valores padrão inseridos!")

cursor.close()
conn.close()
print("✓ Tabela txentrega configurada com sucesso!")
