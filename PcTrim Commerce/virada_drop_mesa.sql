-- Virada final: remover tabela legado `mesa` com segurança.
-- Execucao manual, somente apos homologacao.

-- 1) Pre-checagens
SELECT 'pedido_diarios_exists' AS check_name, COUNT(*) AS total
FROM information_schema.tables
WHERE table_schema = DATABASE()
  AND table_name = 'pedido_diarios';

SELECT 'mesa_exists' AS check_name, COUNT(*) AS total
FROM information_schema.tables
WHERE table_schema = DATABASE()
  AND table_name = 'mesa';

SELECT 'pedido_diarios_mesa_rows' AS check_name, COUNT(*) AS total
FROM pedido_diarios
WHERE origem = 'MESA';

-- 2) Backup estrutural opcional (recomendado)
DROP TABLE IF EXISTS mesa_backup;
CREATE TABLE mesa_backup AS
SELECT * FROM mesa;

-- 3) Amostragem rapida para auditoria humana
SELECT * FROM mesa_backup ORDER BY nrolancamento DESC LIMIT 20;
SELECT * FROM pedido_diarios WHERE origem = 'MESA' ORDER BY chave DESC LIMIT 20;

-- 4) Virada (executar somente com aprovacao operacional)
-- DROP TABLE mesa;

-- 5) Rollback rapido (se necessario, manual)
-- CREATE TABLE mesa AS SELECT * FROM mesa_backup;
