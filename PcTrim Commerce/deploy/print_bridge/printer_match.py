"""Resolução de nome de impressora Windows (case-insensitive, UNC)."""
from __future__ import annotations

import re
import unicodedata


def normalize_printer_name(value: str) -> str:
    s = str(value or "").strip()
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _candidates_from_cadastro(desired_raw: str) -> list[str]:
    raw = str(desired_raw or "").strip()
    if not raw:
        return []
    out: list[str] = []
    seen: set[str] = set()

    def add(v: str) -> None:
        v = str(v or "").strip()
        if not v:
            return
        lk = v.lower()
        if lk in seen:
            return
        seen.add(lk)
        out.append(v)

    add(raw)
    if raw.startswith("\\\\") or raw.startswith("//"):
        parts = [p for p in re.split(r"[\\/]+", raw) if p]
        if parts:
            add(parts[-1])
    else:
        for part in re.split(r"[\\/]+", raw):
            if part:
                add(part)
    return out


def find_best_printer_match(desired_name: str, available_names: list[str]) -> str | None:
    desired_raw = str(desired_name or "").strip()
    if not desired_raw or not available_names:
        return None

    avail = [str(n or "").strip() for n in available_names if str(n or "").strip()]
    if not avail:
        return None

    lower_map = {n.lower(): n for n in avail}

    for candidate in _candidates_from_cadastro(desired_raw):
        hit = lower_map.get(candidate.lower())
        if hit:
            return hit

    norm_pairs = [(n, normalize_printer_name(n)) for n in avail]
    norm_pairs = [(n, nn) for n, nn in norm_pairs if nn]

    for candidate in _candidates_from_cadastro(desired_raw):
        cn = normalize_printer_name(candidate)
        if not cn:
            continue
        for n, nn in norm_pairs:
            if nn == cn:
                return n

    for candidate in _candidates_from_cadastro(desired_raw):
        cn = normalize_printer_name(candidate)
        if not cn:
            continue
        contains = [(n, nn) for n, nn in norm_pairs if cn in nn]
        if not contains:
            contains = [(n, nn) for n, nn in norm_pairs if nn and nn in cn]
        if contains:
            contains.sort(key=lambda x: (len(x[1]), x[0].lower()))
            return contains[0][0]

    return None


def resolve_windows_printer(
    cadastro_name: str, available_names: list[str] | None = None
) -> tuple[str | None, str]:
    """Retorna (nome_windows, motivo). motivo: exact | unc_tail | normalized | contains | none."""
    raw = str(cadastro_name or "").strip()
    if not raw:
        return None, "none"

    avail = [str(n or "").strip() for n in (available_names or []) if str(n or "").strip()]
    if not avail:
        return None, "none"

    lower_map = {n.lower(): n for n in avail}
    cands = _candidates_from_cadastro(raw)

    if len(cands) == 1 and cands[0].lower() in lower_map:
        return lower_map[cands[0].lower()], "exact"

    for i, candidate in enumerate(cands):
        hit = lower_map.get(candidate.lower())
        if hit:
            if i > 0 and raw.startswith(("\\\\", "//")):
                return hit, "unc_tail"
            return hit, "exact"

    norm_pairs = [(n, normalize_printer_name(n)) for n in avail]
    norm_pairs = [(n, nn) for n, nn in norm_pairs if nn]

    for candidate in cands:
        cn = normalize_printer_name(candidate)
        if not cn:
            continue
        for n, nn in norm_pairs:
            if nn == cn:
                return n, "normalized"

    for candidate in cands:
        cn = normalize_printer_name(candidate)
        if not cn:
            continue
        contains = [(n, nn) for n, nn in norm_pairs if cn in nn]
        if not contains:
            contains = [(n, nn) for n, nn in norm_pairs if nn and nn in cn]
        if contains:
            contains.sort(key=lambda x: (len(x[1]), x[0].lower()))
            return contains[0][0], "contains"

    return None, "none"
