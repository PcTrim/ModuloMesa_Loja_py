"""Testes unitários do motor geo v3.3 (distância delivery)."""
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("FLASK_SECRET_KEY", "test-secret")

from helpers_app import (
    DISTANCIA_COLISAO_METROS,
    calcular_distancia_cliente,
    coords_em_colisao,
    endereco_geo_inalterado,
    enderecos_textuais_diferentes,
    equivalente_se_ambos_presentes,
    normalizar_campo_endereco,
    normalizar_cep,
    resolver_distancia_km,
    _aviso_precisao_endereco,
)


class NormalizacaoTests(unittest.TestCase):
    def test_normalizar_campo_endereco_acentos_espacos(self):
        self.assertEqual(normalizar_campo_endereco("  São  João  "), "sao joao")
        self.assertEqual(normalizar_campo_endereco("RUA A"), "rua a")

    def test_normalizar_cep_valido_e_invalido(self):
        self.assertEqual(normalizar_cep("64600-000"), "64600000")
        self.assertEqual(normalizar_cep("6460"), "")
        self.assertEqual(normalizar_cep(""), "")
        self.assertEqual(normalizar_cep(None), "")

    def test_equivalente_se_ambos_presentes(self):
        self.assertTrue(equivalente_se_ambos_presentes("Picos", ""))
        self.assertTrue(equivalente_se_ambos_presentes("", "Florianópolis"))
        self.assertFalse(equivalente_se_ambos_presentes("Picos", "Florianópolis"))


class EnderecoGeoInalteradoTests(unittest.TestCase):
    def _base(self):
        return {
            "cep": "64600000",
            "endereco": "Rua A",
            "nrocasa": "100",
            "cidade": "Picos",
            "estado": "PI",
            "lat_cliente": -7.0,
            "lon_cliente": -41.0,
        }

    def test_cep_invalido_falha_no_passo_1(self):
        novo = {"cep": "6460", "endereco": "Rua A", "nrocasa": "100"}
        self.assertFalse(endereco_geo_inalterado(novo, self._base()))

    def test_cep_diferente_falha_no_passo_2(self):
        novo = {"cep": "64000000", "endereco": "Rua A", "nrocasa": "100"}
        self.assertFalse(endereco_geo_inalterado(novo, self._base()))

    def test_numero_mudou_regeocode(self):
        novo = {"cep": "64600000", "endereco": "Rua A", "nrocasa": "200"}
        self.assertFalse(endereco_geo_inalterado(novo, self._base()))

    def test_endereco_inalterado_true(self):
        novo = {
            "cep": "64600-000",
            "endereco": "Rua A",
            "nrocasa": "100",
            "cidade": "Picos",
            "estado": "PI",
        }
        self.assertTrue(endereco_geo_inalterado(novo, self._base()))

    def test_cidade_ausente_nao_bloqueia(self):
        novo = {"cep": "64600000", "endereco": "Rua A", "nrocasa": "100"}
        antigo = self._base()
        antigo.pop("cidade")
        self.assertTrue(endereco_geo_inalterado(novo, antigo))


class ResolverDistanciaTests(unittest.TestCase):
    @patch("helpers_app.distancia_osrm_km", return_value=2.5)
    def test_osrm_ok(self, _mock):
        dist, origem = resolver_distancia_km(-7.0, -41.0, -7.01, -41.01, {}, {})
        self.assertEqual(dist, 2.5)
        self.assertEqual(origem, "osrm")

    @patch("helpers_app.distancia_osrm_km", return_value=None)
    def test_falha_osrm_sem_haversine_generico(self, _mock):
        dist, origem = resolver_distancia_km(-7.0, -41.0, -7.01, -41.01, {}, {})
        self.assertEqual(dist, 0)
        self.assertEqual(origem, "falha_osrm")

    @patch("helpers_app.distancia_osrm_km", return_value=0)
    @patch("helpers_app.coords_em_colisao", return_value=True)
    @patch("helpers_app.enderecos_textuais_diferentes", return_value=True)
    @patch("helpers_app.haversine_km", return_value=0.2)
    def test_haversine_correcao_em_colisao(self, _hav, _txt, _col, _osrm):
        dist, origem = resolver_distancia_km(
            -7.0,
            -41.0,
            -7.0,
            -41.0,
            {"endereco": "Rua B", "nrocasa": "10"},
            {"endereco": "Rua A", "nrocasa": "100"},
        )
        self.assertEqual(dist, 0.2)
        self.assertEqual(origem, "haversine_correcao")

    @patch("helpers_app.distancia_osrm_km", return_value=0)
    @patch("helpers_app.coords_em_colisao", return_value=False)
    def test_osrm_zero_sem_colisao(self, _col, _osrm):
        dist, origem = resolver_distancia_km(-7.0, -41.0, -7.0, -41.0, {}, {})
        self.assertEqual(dist, 0)
        self.assertEqual(origem, "osrm")


class ColisaoTests(unittest.TestCase):
    def test_coords_em_colisao_usa_constante(self):
        self.assertTrue(DISTANCIA_COLISAO_METROS == 50)
        lat, lon = -7.0769, -41.4677
        quase = lat + (DISTANCIA_COLISAO_METROS / 2) / 111000
        self.assertTrue(coords_em_colisao(lat, lon, quase, lon))

    def test_enderecos_textuais_diferentes(self):
        self.assertTrue(
            enderecos_textuais_diferentes(
                {"endereco": "Rua B", "nrocasa": "1"},
                {"endereco": "Rua A", "nrocasa": "1"},
            )
        )
        self.assertFalse(
            enderecos_textuais_diferentes(
                {"endereco": "Rua A", "nrocasa": "1"},
                {"endereco": "Rua A", "nrocasa": "1"},
            )
        )


class CalcularDistanciaClienteTests(unittest.TestCase):
    def test_aviso_precisao_sem_numero(self):
        self.assertIn("sem número", _aviso_precisao_endereco({"nrocasa": ""}).lower())

    @patch("helpers_app.obter_dados_loja")
    @patch("helpers_app.geocodificar", return_value=(-7.01, -41.01))
    @patch("helpers_app.distancia_osrm_km", return_value=1.5)
    def test_reuse_coords_quando_endereco_inalterado(self, _osrm, _geo, mock_loja):
        mock_loja.return_value = {
            "latitude": -7.0,
            "longitude": -41.0,
            "endereco": "Rua Loja",
            "nrocasa": "1",
        }
        existente = {
            "cep": "64600000",
            "endereco": "Rua A",
            "nrocasa": "100",
            "cidade": "Picos",
            "estado": "PI",
            "lat_cliente": -7.005,
            "lon_cliente": -41.005,
        }
        dados = {
            "cep": "64600-000",
            "endereco": "Rua A",
            "nrocasa": "100",
            "cidade": "Picos",
            "estado": "PI",
        }
        with patch("helpers_app.endereco_geo_inalterado", return_value=True):
            result = calcular_distancia_cliente(dados, id_cliente=1, cliente_existente=existente)
        _geo.assert_not_called()
        self.assertEqual(result["distancia"], 1.5)
        self.assertEqual(result["lat_cli"], -7.005)
        self.assertEqual(result["origem_calculo"], "osrm")


if __name__ == "__main__":
    unittest.main()
