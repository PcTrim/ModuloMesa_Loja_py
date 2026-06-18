"""Reexporta matcher do print_bridge (app.py na raiz do projeto)."""
from deploy.print_bridge.printer_match import (  # noqa: F401
    find_best_printer_match,
    normalize_printer_name,
    resolve_windows_printer,
)

__all__ = ["find_best_printer_match", "normalize_printer_name", "resolve_windows_printer"]
