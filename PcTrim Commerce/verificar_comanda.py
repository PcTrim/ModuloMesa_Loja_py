import mysql.connector

conn = mysql.connector.connect(
    host='127.0.0.1',
    port=3307,
    user='root',
    password='pctrim',
    database='loja2001'
)
cursor = conn.cursor()

# Verifica se a tabela comanda existe
cursor.execute("SHOW TABLES LIKE 'comanda'")
existe = cursor.fetchone()

if existe:
    print("Tabela 'comanda' existe!")
    print("\nEstrutura da tabela comanda:")
    cursor.execute("DESCRIBE comanda")
    for row in cursor.fetchall():
        print(row)
    
    print("\n--- Estrutura da tabela deliverypendente:")
    cursor.execute("DESCRIBE deliverypendente")
    for row in cursor.fetchall():
        print(row)
else:
    print("Tabela 'comanda' NÃO existe! Criando...")
    
    # Cria tabela comanda com mesma estrutura que deliverypendente
    cursor.execute("""
        CREATE TABLE comanda (
            chave INT AUTO_INCREMENT PRIMARY KEY,
            nropedido INT NOT NULL,
            telefone VARCHAR(20),
            nome VARCHAR(255),
            cep VARCHAR(20),
            endereco VARCHAR(255),
            nrocasa VARCHAR(50),
            complemento VARCHAR(255),
            codigoproduto VARCHAR(50),
            produto VARCHAR(255),
            preco DECIMAL(10,2),
            quantidade INT,
            classe VARCHAR(100),
            entregador VARCHAR(255),
            cliente VARCHAR(255),
            data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_nropedido (nropedido),
            INDEX idx_telefone (telefone)
        )
    """)
    conn.commit()
    print("✓ Tabela 'comanda' criada com sucesso!")

cursor.close()
conn.close()
