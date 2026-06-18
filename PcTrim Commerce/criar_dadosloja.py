import mysql.connector

# Conectar ao banco de dados
conn = mysql.connector.connect(
    host="92.113.33.100",
    port=3308,
    user="root",
    password="pctrim",
    database="loja2001"
)

cursor = conn.cursor()

# Drop table se existir
cursor.execute("DROP TABLE IF EXISTS dadosloja")

# Criar tabela
cursor.execute("""
CREATE TABLE dadosloja (
    chave INT PRIMARY KEY,
    nome VARCHAR(255) NOT NULL,
    endereco TEXT NOT NULL,
    bairro VARCHAR(100),
    cidade VARCHAR(100),
    cep VARCHAR(10),
    telefone VARCHAR(20) NOT NULL,
    cnpj VARCHAR(20),
    latitude VARCHAR(20) NOT NULL,
    longitude VARCHAR(20) NOT NULL,
    ddd VARCHAR(3)
)
""")

# Inserir registro padrão
cursor.execute("""
INSERT INTO dadosloja (chave, nome, endereco, bairro, cidade, cep, telefone, cnpj, latitude, longitude, ddd)
VALUES (1, 'Minha Loja', 'Praça São Pedro', 'Aerolândia', 'Picos - PI', '64600-000', '(89) 99999-9999', '', '-7.0793693', '-41.4687021', '89')
""")

conn.commit()
cursor.close()
conn.close()

print("✅ Tabela dadosloja criada com sucesso!")
