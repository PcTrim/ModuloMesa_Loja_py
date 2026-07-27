"""Validação read-only do preview de arquivamento (não executa fechamento)."""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from services import fechamento_periodo
from services.loja_ambiente import fetch_loja_ambiente_for_cliente
from database import conectar_admin


def main():
    for lid in (2001, 1739):
        target = fetch_loja_ambiente_for_cliente(lid)
        conn = conectar_admin(target)
        cur = conn.cursor(dictionary=True)
        print(f"=== LOJA {lid} ({target}) ===")
        periods = [
            ("2026-07-24", "2026-07-24"),
            ("2026-07-25", "2026-07-26"),
            ("2026-07-27", "2026-07-27"),
        ]
        for di, df in periods:
            d0, d1 = fechamento_periodo.intervalo_datetimes(di, df)
            wf, pf = fechamento_periodo._where_fechamento(lid, d0, d1)
            wa, pa = fechamento_periodo._where_fechamento_arquivamento(lid, d0, d1)
            cur.execute(f"SELECT COUNT(*) AS n FROM pedido_diarios WHERE {wf}", pf)
            fin = int((cur.fetchone() or {}).get("n") or 0)
            cur.execute(f"SELECT COUNT(*) AS n FROM pedido_diarios WHERE {wa}", pa)
            arq = int((cur.fetchone() or {}).get("n") or 0)
            cur.execute(
                """
                SELECT COUNT(*) AS n FROM pedido_diarios
                WHERE id_cliente = %s AND origem IN ('DELIVERY','BALCAO')
                """,
                (lid,),
            )
            diario = int((cur.fetchone() or {}).get("n") or 0)
            cur.execute("SELECT contador FROM contadorpedido WHERE id_cliente = %s", (lid,))
            rowc = cur.fetchone()
            cont = rowc.get("contador") if rowc else None
            reset_ok = "sim" if diario == 0 else "nao (restam no diario)"
            print(
                f"  {di}..{df}: financeiro={fin} arquivamento={arq} "
                f"diario={diario} contador={cont} reset_pos_arq={reset_ok}"
            )
        prev = fechamento_periodo.preview_fechamento(lid, "2026-07-24", "2026-07-24")
        print("  preview 24/07:", prev.get("linhas"), prev.get("por_status"))
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
