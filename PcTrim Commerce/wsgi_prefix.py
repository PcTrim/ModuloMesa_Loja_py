"""Middleware WSGI: define SCRIPT_NAME para o app rodar sob subpath (ex.: /LojaOnline)."""


class ScriptNameMiddleware:
    """Apache com ProxyPass /LojaOnline/ -> backend já envia PATH_INFO sem o prefixo."""

    def __init__(self, app, script_name: str):
        self.app = app
        self.script_name = (script_name or "").rstrip("/")

    def __call__(self, environ, start_response):
        if self.script_name:
            environ["SCRIPT_NAME"] = self.script_name
        return self.app(environ, start_response)
