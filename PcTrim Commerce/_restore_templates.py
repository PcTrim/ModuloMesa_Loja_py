import subprocess
from pathlib import Path

repo = Path(__file__).resolve().parent.parent
commerce = Path(__file__).resolve().parent

# Restore clean UTF-8 templates from HEAD
files = [
    "PcTrim Commerce/templates/configuracoes_dados.html",
    "PcTrim Commerce/templates/index.html",
    "PcTrim Commerce/templates/mesa.html",
    "PcTrim Commerce/templates/painel_menu.html",
]

for rel in files:
    data = subprocess.check_output(["git", "show", f"HEAD:{rel}"], cwd=repo)
    # drop BOM if present
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    out = commerce / "templates" / Path(rel).name
    out.write_bytes(data)
    text = data.decode("utf-8")
    print(rel, "restored", "mojibake=" + str(("Ã" in text or "â€" in text)), "bytes", len(data))

cfg = (commerce / "templates/configuracoes_dados.html").read_text(encoding="utf-8")
i = cfg.find("caminhos Windows")
print("sample:", repr(cfg[i : i + 70]))
