"""
Testes E2E — geração atômica de nropedido (contadorpedido + LAST_INSERT_ID).

Modo padrão: Flask test_client + ThreadPoolExecutor (concorrência real no MySQL).
Modo opcional LIVE: E2E_LIVE=1 + servidor :2001 + E2E_LOGIN_USER/PASS.

Uso:
    cd "PcTrim Commerce"
    set E2E=1
    python -m tests.test_contador_pedido_e2e
"""
from __future__ import annotations

import os
import re
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable

import requests
from dotenv import load_dotenv

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

load_dotenv(os.path.join(_ROOT, ".env"))
from tests.test_env import aplicar_env_teste, conectar_teste  # noqa: E402

aplicar_env_teste()
os.environ.setdefault("FLASK_SECRET_KEY", os.getenv("FLASK_SECRET_KEY") or "e2e-test-secret")

BASE_URL = os.getenv("E2E_BASE_URL", "http://127.0.0.1:2001").rstrip("/")
E2E_USER = os.getenv("E2E_LOGIN_USER", "admin")
E2E_PASS = os.getenv("E2E_LOGIN_PASS", "admin")
LIVE_MODE = os.getenv("E2E_LIVE", "0") == "1"
PRODUTO_PREFIX = "Item Teste E2E"
CONCURRENT_WORKERS = int(os.getenv("E2E_CONCURRENT_WORKERS", "10"))
CLEANUP = os.getenv("E2E_CLEANUP", "1") != "0"
ID_CLIENTE_OVERRIDE = int(os.getenv("E2E_ID_CLIENTE", "0") or "0")
E2E_ENABLED = os.getenv("E2E", "0") == "1"


@dataclass
class TestReport:
    results: list[tuple[str, bool, str]] = field(default_factory=list)
    allocated_numbers: list[int] = field(default_factory=list)
    id_cliente: int = 0
    contador_inicial: int = 0
    max_nropedido_inicial: int = 0

    def ok(self, name: str, detail: str = ""):
        self.results.append((name, True, detail))
        print(f"  [OK] {name}" + (f" — {detail}" if detail else ""))

    def fail(self, name: str, detail: str = ""):
        self.results.append((name, False, detail))
        print(f"  [FALHA] {name}" + (f" — {detail}" if detail else ""))

    def skip(self, name: str, detail: str = ""):
        self.results.append((name, True, f"SKIP: {detail}"))
        print(f"  [SKIP] {name} — {detail}")

    @property
    def passed(self) -> bool:
        return all(ok for _, ok, _ in self.results)


def _db_query_one(sql: str, params=()) -> Any:
    conn = conectar_teste()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        return cur.fetchone()
    finally:
        cur.close()
        conn.close()


def _db_execute(sql: str, params=()) -> int:
    conn = conectar_teste()
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        conn.commit()
        return cur.rowcount
    finally:
        cur.close()
        conn.close()


def get_contador(id_cliente: int) -> int:
    row = _db_query_one(
        "SELECT contador FROM contadorpedido WHERE id_cliente = %s",
        (id_cliente,),
    )
    return int(row["contador"]) if row else 0


def get_max_nropedido(id_cliente: int) -> int:
    row = _db_query_one(
        """
        SELECT MAX(nropedido) AS mx
        FROM pedido_diarios
        WHERE id_cliente = %s AND origem IN ('BALCAO','DELIVERY')
        """,
        (id_cliente,),
    )
    return int(row["mx"] or 0) if row else 0


def get_tipo_negocio(id_cliente: int) -> str:
    row = _db_query_one(
        "SELECT tipo_negocio FROM dadosloja WHERE id_cliente = %s LIMIT 1",
        (id_cliente,),
    )
    if not row:
        return "restaurante"
    return str(row.get("tipo_negocio") or "restaurante").strip().lower()


def resolve_id_cliente() -> int:
    if ID_CLIENTE_OVERRIDE > 0:
        return ID_CLIENTE_OVERRIDE
    row = _db_query_one(
        "SELECT id_cliente FROM contadorpedido ORDER BY id_cliente LIMIT 1"
    )
    if row:
        return int(row["id_cliente"])
    row = _db_query_one("SELECT id_cliente FROM dadosloja ORDER BY id_cliente LIMIT 1")
    if row:
        return int(row["id_cliente"])
    return 1


def ensure_contador_row(id_cliente: int) -> None:
    conn = conectar_teste()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT IGNORE INTO contadorpedido (contador, id_cliente) VALUES (0, %s)",
            (id_cliente,),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


def payload_balcao(suffix: str = "") -> dict:
    return {
        "modo": "BALCAO",
        "telefone": "BALCAO",
        "item": {
            "nome": f"{PRODUTO_PREFIX}{suffix}",
            "preco": 1.0,
            "qtd": 1,
        },
    }


def payload_delivery(telefone: str, suffix: str = "") -> dict:
    return {
        "modo": "DELIVERY",
        "telefone": telefone,
        "item": {
            "nome": f"{PRODUTO_PREFIX}{suffix}",
            "preco": 1.0,
            "qtd": 1,
        },
    }


def payload_mesa(mesanro: int, suffix: str = "") -> dict:
    return {
        "modo": "MESA",
        "nropedido": mesanro,
        "telefone": f"MESA{mesanro}",
        "item": {
            "nome": f"{PRODUTO_PREFIX}{suffix}",
            "preco": 1.0,
            "qtd": 1,
        },
    }


def cleanup_test_rows(id_cliente: int) -> int:
    return _db_execute(
        "DELETE FROM pedido_diarios WHERE id_cliente = %s AND produto LIKE %s",
        (id_cliente, f"{PRODUTO_PREFIX}%"),
    )


# --- Transporte HTTP ---------------------------------------------------------

class HttpTransport:
    def get(self, path: str) -> tuple[int, dict]:
        raise NotImplementedError

    def post_item(self, payload: dict) -> tuple[int, dict]:
        raise NotImplementedError


class FlaskTransport(HttpTransport):
    def __init__(self, id_cliente: int):
        from app import app  # noqa: WPS433

        self.app = app
        self.id_cliente = id_cliente
        self._client = app.test_client()
        with self._client.session_transaction() as sess:
            sess["id_cliente"] = id_cliente
            sess["usuario_logado"] = "e2e-test"

    def get(self, path: str) -> tuple[int, dict]:
        r = self._client.get(path, headers={"Accept": "application/json"})
        try:
            return r.status_code, r.get_json(silent=True) or {}
        except Exception:
            return r.status_code, {}

    def post_item(self, payload: dict) -> tuple[int, dict]:
        r = self._client.post(
            "/api/casa/item",
            json=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        data = r.get_json(silent=True) or {}
        return r.status_code, data


class LiveTransport(HttpTransport):
    def __init__(self):
        self.session = self._login()

    def _login(self) -> requests.Session:
        s = requests.Session()
        r = s.get(f"{BASE_URL}/login/form", timeout=30)
        r.raise_for_status()
        m = re.search(r'id="csrf_token"\s+value="([^"]*)"', r.text)
        if not m:
            raise RuntimeError("CSRF token não encontrado")
        r2 = s.post(
            f"{BASE_URL}/login",
            json={"usuario": E2E_USER, "senha": E2E_PASS, "csrf_token": m.group(1)},
            timeout=30,
        )
        data = r2.json()
        if r2.status_code != 200 or not data.get("sucesso"):
            raise RuntimeError(f"Login falhou: {data.get('erro')}")
        return s

    def get(self, path: str) -> tuple[int, dict]:
        r = self.session.get(f"{BASE_URL}{path}", timeout=30)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, {}

    def post_item(self, payload: dict) -> tuple[int, dict]:
        r = self.session.post(
            f"{BASE_URL}/api/casa/item",
            json=payload,
            timeout=60,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, {"erro": r.text[:200]}


def make_flask_transport(id_cliente: int) -> FlaskTransport:
    return FlaskTransport(id_cliente)


# --- Casos de teste ----------------------------------------------------------

def test_preparacao(report: TestReport, transport: HttpTransport) -> None:
    name = "1. Preparação (contadorpedido + sessão)"
    try:
        report.id_cliente = resolve_id_cliente()
        ensure_contador_row(report.id_cliente)
        report.contador_inicial = get_contador(report.id_cliente)
        report.max_nropedido_inicial = get_max_nropedido(report.id_cliente)
        st, _ = transport.get("/numero-pedido-atual")
        if st == 401:
            report.fail(name, "Não autenticado")
            return
        report.ok(
            name,
            f"id_cliente={report.id_cliente}, contador={report.contador_inicial}, "
            f"max_nropedido={report.max_nropedido_inicial}",
        )
    except Exception as e:
        report.fail(name, str(e))


def test_preview(report: TestReport, transport: HttpTransport) -> None:
    name = "2. Preview (/numero-pedido-atual não incrementa)"
    try:
        c0 = get_contador(report.id_cliente)
        s1, d1 = transport.get("/numero-pedido-atual")
        s2, d2 = transport.get("/numero-pedido-atual")
        c1 = get_contador(report.id_cliente)
        if s1 != 200 or s2 != 200:
            report.fail(name, f"HTTP {s1}/{s2}")
            return
        n1, n2 = int(d1.get("numero") or 0), int(d2.get("numero") or 0)
        if n1 != n2:
            report.fail(name, f"Inconsistente {n1} vs {n2}")
            return
        if c1 != c0:
            report.fail(name, f"Contador mudou {c0}->{c1}")
            return
        report.ok(name, f"preview=#{n1}, contador={c1}")
    except Exception as e:
        report.fail(name, str(e))


def test_concorrencia(report: TestReport, id_cliente: int, factory: Callable[[], HttpTransport]) -> None:
    name = f"3. Concorrência ({CONCURRENT_WORKERS} POST simultâneos)"
    barrier = threading.Barrier(CONCURRENT_WORKERS)
    results: list[tuple[int, int, str]] = []
    lock = threading.Lock()

    def worker(idx: int):
        barrier.wait()
        t = factory()
        status, data = t.post_item(payload_balcao(f" conc-{idx}-{uuid.uuid4().hex[:6]}"))
        nro = int(data.get("nropedido") or 0) if isinstance(data, dict) else 0
        err = str(data.get("erro") or "") if isinstance(data, dict) else ""
        with lock:
            results.append((status, nro, err))

    try:
        with ThreadPoolExecutor(max_workers=CONCURRENT_WORKERS) as pool:
            futs = [pool.submit(worker, i) for i in range(CONCURRENT_WORKERS)]
            for f in as_completed(futs):
                f.result()

        statuses = [r[0] for r in results]
        numeros = [r[1] for r in results if r[1] > 0]
        if any(s != 200 for s in statuses):
            report.fail(name, f"HTTP: {statuses}")
            return
        if len(numeros) != CONCURRENT_WORKERS:
            report.fail(name, f"Esperados {CONCURRENT_WORKERS}, obtidos {len(numeros)}: {numeros}")
            return
        if len(set(numeros)) != CONCURRENT_WORKERS:
            report.fail(name, f"Duplicidade: {numeros}")
            return
        report.allocated_numbers.extend(numeros)
        report.ok(name, f"únicos: {sorted(numeros)}")
    except Exception as e:
        report.fail(name, str(e))


def test_sequencia(report: TestReport, transport: HttpTransport) -> None:
    name = "4. Sequência (5 pedidos seriais)"
    try:
        numeros = []
        for i in range(5):
            status, data = transport.post_item(payload_balcao(f" seq-{i}-{uuid.uuid4().hex[:6]}"))
            if status != 200:
                report.fail(name, f"HTTP {status} {data}")
                return
            nro = int(data.get("nropedido") or 0)
            if nro <= 0:
                report.fail(name, f"nropedido inválido no pedido {i}")
                return
            numeros.append(nro)
            time.sleep(0.03)
        if len(set(numeros)) != 5 or numeros != sorted(numeros):
            report.fail(name, str(numeros))
            return
        report.allocated_numbers.extend(numeros)
        report.ok(name, str(numeros))
    except Exception as e:
        report.fail(name, str(e))


def test_delivery_aguarde(report: TestReport, transport: HttpTransport) -> None:
    name = "5. DELIVERY AGUARDE (reutiliza nropedido)"
    if get_tipo_negocio(report.id_cliente) == "varejo":
        report.skip(name, "loja varejo")
        return
    tel = "11999990099"
    try:
        c0 = get_contador(report.id_cliente)
        s1, d1 = transport.post_item(payload_delivery(tel, f" del-1-{uuid.uuid4().hex[:6]}"))
        nro_a = int(d1.get("nropedido") or 0)
        c1 = get_contador(report.id_cliente)
        s2, d2 = transport.post_item(payload_delivery(tel, f" del-2-{uuid.uuid4().hex[:6]}"))
        nro_b = int(d2.get("nropedido") or 0)
        c2 = get_contador(report.id_cliente)
        if s1 != 200 or s2 != 200 or nro_a <= 0:
            report.fail(name, f"s1={s1} s2={s2} nro_a={nro_a}")
            return
        if nro_b != nro_a:
            report.fail(name, f"Não reutilizou {nro_a} vs {nro_b}")
            return
        if c2 != c1 or c1 <= c0:
            report.fail(name, f"contador {c0}->{c1}->{c2}")
            return
        report.allocated_numbers.append(nro_a)
        report.ok(name, f"nropedido={nro_a}, contador {c0}->{c1}")
    except Exception as e:
        report.fail(name, str(e))


def test_mesa(report: TestReport, transport: HttpTransport) -> None:
    name = "6. MESA (não usa contadorpedido)"
    if get_tipo_negocio(report.id_cliente) == "varejo":
        report.skip(name, "loja varejo")
        return
    mesanro = 5
    try:
        c0 = get_contador(report.id_cliente)
        status, data = transport.post_item(payload_mesa(mesanro, f" mesa-{uuid.uuid4().hex[:6]}"))
        c1 = get_contador(report.id_cliente)
        if status != 200:
            report.fail(name, f"HTTP {status} {data}")
            return
        if c1 != c0:
            report.fail(name, f"contador {c0}->{c1}")
            return
        if int(data.get("nropedido") or 0) != mesanro:
            report.fail(name, f"nropedido={data.get('nropedido')}")
            return
        report.ok(name, f"mesa={mesanro}, contador={c1}")
    except Exception as e:
        report.fail(name, str(e))


def test_integridade_db(report: TestReport) -> None:
    name = "7. Integridade DB (contador >= max nropedido)"
    try:
        contador = get_contador(report.id_cliente)
        max_nro = get_max_nropedido(report.id_cliente)
        if contador < max_nro:
            report.fail(name, f"contador={contador} < max={max_nro}")
            return
        nums = report.allocated_numbers
        if nums and len(set(nums)) != len(nums):
            report.fail(name, f"duplicatas {nums}")
            return
        report.ok(name, f"contador={contador}, max={max_nro}, teste={len(set(nums))} únicos")
    except Exception as e:
        report.fail(name, str(e))


def test_proximo_pedido(report: TestReport, transport: HttpTransport) -> None:
    name = "8. /proximo-pedido (somente preview)"
    try:
        c0 = get_contador(report.id_cliente)
        st, data = transport.get("/proximo-pedido")
        c1 = get_contador(report.id_cliente)
        if st != 200:
            report.fail(name, f"HTTP {st}")
            return
        preview = int(data.get("numero") or 0)
        if c1 != c0:
            report.fail(name, f"contador {c0}->{c1}")
            return
        if preview != (c0 + 1 if c0 else 1):
            report.fail(name, f"preview={preview}, esperado={c0 + 1}")
            return
        report.ok(name, f"preview=#{preview}, contador={c1}")
    except Exception as e:
        report.fail(name, str(e))


def test_manual_api_checks(report: TestReport) -> None:
    """Simula checklist manual via APIs (preview coerente entre 'terminais' Flask)."""
    name = "M1. Multi-terminal simulado (2 previews iguais)"
    try:
        cid = report.id_cliente
        t1 = make_flask_transport(cid)
        t2 = make_flask_transport(cid)
        _, d1 = t1.get("/numero-pedido-atual")
        _, d2 = t2.get("/numero-pedido-atual")
        n1, n2 = int(d1.get("numero") or 0), int(d2.get("numero") or 0)
        if n1 != n2:
            report.fail(name, f"preview divergente {n1} vs {n2}")
            return
        report.ok(name, f"ambos Próximo #{n1}")
    except Exception as e:
        report.fail(name, str(e))


def print_verdict(report: TestReport) -> int:
    print("\n" + "=" * 60)
    print("MATRIZ GO / NO-GO")
    print("=" * 60)
    fails = [(n, d) for n, ok, d in report.results if not ok]
    skips = [(n, d) for n, ok, d in report.results if ok and d.startswith("SKIP:")]
    oks = [(n, d) for n, ok, d in report.results if ok and not d.startswith("SKIP:")]

    for n, _ in oks:
        print(f"  GO   {n}")
    for n, d in skips:
        print(f"  SKIP {n} ({d})")
    for n, d in fails:
        print(f"  NO-GO {n} — {d}")

    print("=" * 60)
    if fails:
        print("VEREDITO: NO-GO — revisar falhas antes do deploy")
        return 1
    print("VEREDITO: GO — critérios automatizados atendidos")
    print("\nRecomendado no navegador: 2 abas, 1º item simultâneo, refresh ao focar aba.")
    return 0


def main() -> int:
    if not E2E_ENABLED and not LIVE_MODE:
        print(
            "E2E desativado no discover/gate. "
            "Rode com E2E=1 (test_client+MySQL) ou E2E_LIVE=1 (servidor :2001)."
        )
        return 0
    mode = "LIVE (HTTP :2001)" if LIVE_MODE else "in-process (Flask test_client + MySQL)"
    print(f"E2E nropedido — {mode}")
    print(f"Workers concorrência: {CONCURRENT_WORKERS}\n")

    report = TestReport()

    try:
        if LIVE_MODE:
            transport: HttpTransport = LiveTransport()
            factory = LiveTransport
        else:
            cid = resolve_id_cliente()
            transport = make_flask_transport(cid)
            factory = lambda: make_flask_transport(report.id_cliente or cid)
    except Exception as e:
        print(f"[ERRO FATAL] {e}")
        return 1

    if CLEANUP:
        try:
            cid = resolve_id_cliente()
            n = cleanup_test_rows(cid)
            if n:
                print(f"Limpeza prévia: {n} linha(s)\n")
        except Exception:
            pass

    test_preparacao(report, transport)
    if not report.id_cliente:
        return print_verdict(report)

    test_preview(report, transport)
    test_proximo_pedido(report, transport)
    test_concorrencia(report, report.id_cliente, factory)
    test_sequencia(report, transport)
    test_delivery_aguarde(report, transport)
    test_mesa(report, transport)
    test_integridade_db(report)
    test_manual_api_checks(report)

    if CLEANUP and report.id_cliente:
        try:
            n = cleanup_test_rows(report.id_cliente)
            print(f"\nLimpeza pós-teste: {n} linha(s)")
        except Exception as e:
            print(f"\n[WARN] Limpeza: {e}")

    return print_verdict(report)


if __name__ == "__main__":
    sys.exit(main())
