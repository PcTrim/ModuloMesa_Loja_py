-- Flags de impressão por setor (rode uma vez no MySQL)
ALTER TABLE impressoras ADD COLUMN caminho VARCHAR(512) DEFAULT '';
ALTER TABLE impressoras ADD COLUMN conta_mesa VARCHAR(1) DEFAULT 'N';
ALTER TABLE impressoras ADD COLUMN comanda_delivery VARCHAR(1) DEFAULT 'N';

-- Balcão / delivery (/casa): marque comanda_delivery = 'S'
-- UPDATE impressoras SET comanda_delivery = 'S', caminho = '\\\\SEU-PC\\ImpressoraBalcao' WHERE id = 1;

-- Mesa (/mesa): marque conta_mesa = 'S'
-- UPDATE impressoras SET conta_mesa = 'S', caminho = '\\\\SEU-PC\\ImpressoraMesa' WHERE id = 2;
