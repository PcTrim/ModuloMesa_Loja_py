#!/usr/bin/env python3
"""Teste rápido no Chromium: /menu-engineering com sessão simulada."""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import app  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402


def main() -> int:
    base = "http://127.0.0.1:2001"
    errors: list[str] = []

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["usuario_logado"] = "browser_test"
            sess["id_cliente"] = 2001
        client.get("/")
        cookie = client.get_cookie("session")
        if not cookie:
            print("ERRO: cookie de sessão não gerado")
            return 1

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        context.add_cookies(
            [
                {
                    "name": cookie.key,
                    "value": cookie.value,
                    "domain": "127.0.0.1",
                    "path": "/",
                }
            ]
        )
        page = context.new_page()
        page.on("console", lambda msg: errors.append(f"console:{msg.type}:{msg.text}") if msg.type == "error" else None)
        page.on("pageerror", lambda exc: errors.append(f"pageerror:{exc}"))

        # Página principal
        resp = page.goto(f"{base}/menu-engineering", wait_until="networkidle", timeout=30000)
        print(f"GET /menu-engineering -> HTTP {resp.status if resp else '?'}")
        page.wait_for_timeout(2500)
        body_text = page.inner_text("body")
        safe = body_text[:600].replace("\n", " | ").encode("ascii", "replace").decode("ascii")
        print("--- TEXTO VISIVEL (trecho) ---")
        print(safe)

        checks = {
            "titulo_custos": "Custos" in body_text and "Margens" in body_text,
            "kpi_ingredientes": "Ingredientes" in body_text,
            "kpi_receitas": "Receitas" in body_text,
            "sem_erro_api_generico": "API retornou erro" not in body_text,
            "sem_react_fail": "Não foi possível carregar a interface" not in body_text,
            "sem_grafico_indisponivel": "Gráfico indisponível no momento" not in body_text,
            "tabela_receitas": page.locator(".me-recipes-section, .me-recipe-table, table").count() > 0,
        }
        print("--- CHECKS ---")
        for name, ok in checks.items():
            print(f"  {'OK' if ok else 'FALHA'}: {name}")

        # APIs via fetch no contexto da página
        api_results = page.evaluate(
            """async () => {
              const opts = { credentials: 'same-origin', headers: { Accept: 'application/json', 'X-Requested-With': 'XMLHttpRequest' } };
              const paths = ['/menu-engineering/ingredients','/menu-engineering/recipes','/menu-engineering/category-variation'];
              const out = [];
              for (const p of paths) {
                const r = await fetch(p, opts);
                out.push({ path: p, status: r.status, ok: r.ok });
              }
              return out;
            }"""
        )
        print("--- APIs (fetch no browser) ---")
        for item in api_results:
            print(f"  {item['path']} -> {item['status']} {'OK' if item['ok'] else 'FALHA'}")

        if errors:
            print("--- ERROS JS ---")
            for e in errors[:10]:
                print(f"  {e}")

        browser.close()

    api_ok = all(x["ok"] for x in api_results)
    ui_ok = all(checks.values())
    if ui_ok and api_ok and not errors:
        print("\nRESULTADO: SUCESSO no browser")
        return 0
    print("\nRESULTADO: FALHA no browser")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
