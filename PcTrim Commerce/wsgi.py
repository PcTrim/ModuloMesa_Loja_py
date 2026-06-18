"""Ponto de entrada WSGI para Gunicorn em produção."""

from app import app

from config import Config

from wsgi_prefix import ScriptNameMiddleware

try:
    from impressao_confirm_addon import register_impressao_confirm
    register_impressao_confirm(app)
except Exception as _reg_err:
    import sys
    print("[wsgi] confirmar-impressao addon:", _reg_err, file=sys.stderr)

application = app

if Config.URL_PREFIX:

    application = ScriptNameMiddleware(app, Config.URL_PREFIX)

