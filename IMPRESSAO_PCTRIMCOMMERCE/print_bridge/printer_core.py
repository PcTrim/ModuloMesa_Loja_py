"""Impressão Windows (win32print) — sem importar app.py do LojaOnline."""

from __future__ import annotations



import sys



from printer_match import find_best_printer_match, resolve_windows_printer



win32print = None

try:

    import win32print as _win32print

    win32print = _win32print

except Exception:

    pass





def list_installed_printers():

    global win32print

    if sys.platform != "win32":

        return []

    if win32print is None:

        return []

    nomes = []

    try:

        flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS

        for p in win32print.EnumPrinters(flags):

            if len(p) >= 3 and p[2]:

                nomes.append(str(p[2]).strip())

        vistos = set()

        unicos = []

        for n in nomes:

            lk = n.lower()

            if lk not in vistos:

                vistos.add(lk)

                unicos.append(n)

        return unicos

    except Exception:

        return []





def send_to_printer(conteudo, printer_name=None, marca_impressora=None):

    global win32print

    if sys.platform != "win32":

        return False, f"Sistema atual sem suporte para impressão silenciosa: {sys.platform}"

    if win32print is None:

        return False, "pywin32 não instalado. Rode: pip install pywin32"

    try:

        nome_pedido = str(printer_name or win32print.GetDefaultPrinter() or "").strip()

        if not nome_pedido:

            return False, "Nenhuma impressora disponível no Windows."

        disponiveis = list_installed_printers()

        nome = nome_pedido

        if disponiveis and nome_pedido.lower() not in {x.lower() for x in disponiveis}:

            melhor, _motivo = resolve_windows_printer(nome_pedido, disponiveis)

            if not melhor:

                melhor = find_best_printer_match(nome_pedido, disponiveis)

            if not melhor:

                return False, f"Impressora não encontrada no Windows: {nome_pedido}"

            nome = melhor

        hPrinter = win32print.OpenPrinter(nome)

        try:
            hJob = win32print.StartDocPrinter(hPrinter, 1, ("Pedido", None, "RAW"))

            try:

                win32print.StartPagePrinter(hPrinter)

                if isinstance(conteudo, bytes):

                    data = conteudo

                else:
                    data = str(conteudo).encode("cp1252", errors="replace")
                    data += b"\x1B\x64\x03"
                    if marca_impressora:
                        marca = marca_impressora.strip().lower()
                        if "bematech" in marca or "daruma" in marca:
                            data += b"\x1B\x6D"
                        elif "epson" in marca:
                            data += b"\x1B\x69"
                        elif "elgin" in marca or "tanca" in marca or "diebold" in marca:
                            data += b"\x1D\x56\x00"
                        else:
                            data += b"\x1B\x6D"
                    else:
                        data += b"\x1B\x6D"

                win32print.WritePrinter(hPrinter, data)

                win32print.EndPagePrinter(hPrinter)

            finally:

                win32print.EndDocPrinter(hPrinter)

        finally:

            win32print.ClosePrinter(hPrinter)

        return True, None

    except Exception as e:

        return False, str(e)





def send_to_printer_resolved(conteudo, printer_name=None, marca_impressora=None):

    """Como send_to_printer, mas retorna (ok, erro, nome_windows_usado)."""

    global win32print

    if sys.platform != "win32":

        return False, f"Sistema atual sem suporte para impressão silenciosa: {sys.platform}", None

    if win32print is None:

        return False, "pywin32 não instalado. Rode: pip install pywin32", None

    nome_pedido = str(printer_name or "").strip()

    if not nome_pedido:

        return False, "Impressora não informada.", None

    disponiveis = list_installed_printers()

    resolved, motivo = resolve_windows_printer(nome_pedido, disponiveis)

    if not resolved:

        return False, f"Impressora não encontrada no Windows: {nome_pedido}", None

    ok, err = send_to_printer(conteudo, resolved, marca_impressora)

    if ok:

        return True, None, resolved

    return False, err, resolved


