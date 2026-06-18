import mysql.connector

DB_HOST = '92.113.33.100'
DB_PORT = 3308
DB_USER = 'root'
DB_PASSWORD = 'pctrim'
DB_NAME = 'loja2001'

# Garante que o banco exista antes de abrir a conexão com database definido.
admin_conn = mysql.connector.connect(
    host=DB_HOST,
    port=DB_PORT,
    user=DB_USER,
    password=DB_PASSWORD
)
admin_cursor = admin_conn.cursor()
admin_cursor.execute(f"CREATE DATABASE IF NOT EXISTS {DB_NAME}")
admin_conn.commit()
admin_cursor.close()
admin_conn.close()

conn = mysql.connector.connect(
    host=DB_HOST,
    port=DB_PORT,
    user=DB_USER,
    password=DB_PASSWORD,
    database=DB_NAME
)
cursor = conn.cursor()

print("Verificando se existe tabela 'comanda' para backup...")
cursor.execute("DROP TABLE IF EXISTS comanda_backup")
cursor.execute("SHOW TABLES LIKE 'comanda'")
backup_criado = False
if cursor.fetchone():
    print("Renomeando tabela 'comanda' antiga para 'comanda_backup'...")
    cursor.execute("RENAME TABLE comanda TO comanda_backup")
    backup_criado = True
else:
    print("Tabela 'comanda' não existe ainda. Será criada do zero...")

print("Criando nova tabela 'comanda' com estrutura correta...")
cursor.execute("""
    CREATE TABLE comanda (
        chave INT AUTO_INCREMENT PRIMARY KEY,
        nropedido INT NOT NULL,
        telefone VARCHAR(15) NOT NULL DEFAULT '',
        nome VARCHAR(100) NOT NULL DEFAULT '',
        cep VARCHAR(10) NOT NULL DEFAULT '',
        endereco VARCHAR(100) NOT NULL DEFAULT '',
        nrocasa VARCHAR(100) NOT NULL DEFAULT '',
        complemento VARCHAR(100) NOT NULL DEFAULT '',
        codigoproduto VARCHAR(15) NOT NULL DEFAULT '',
        produto VARCHAR(100) NOT NULL DEFAULT '',
        preco DOUBLE NOT NULL DEFAULT 0,
        quantidade DOUBLE NOT NULL DEFAULT 0,
        classe VARCHAR(100) NOT NULL DEFAULT '0',
        entregador VARCHAR(100) DEFAULT '',
        cliente VARCHAR(255) DEFAULT NULL,
        data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_nropedido (nropedido),
        INDEX idx_telefone (telefone)
    )
""")

conn.commit()
print("✓ Tabela 'comanda' recriada com sucesso!")
if backup_criado:
    print("✓ Tabela antiga salva como 'comanda_backup'")
else:
    print("✓ Nenhuma tabela antiga para backup (criação do zero)")

cursor.close()
conn.close()
