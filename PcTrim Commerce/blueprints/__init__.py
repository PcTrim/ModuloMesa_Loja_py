"""Domain-oriented Flask blueprints."""

from .catalog import catalog_bp
from .financeiro import financeiro_bp
from .mesa_shop import mesa_shop_bp
from .platform_admin import platform_admin_bp
from .retail_catalog import retail_catalog_bp


def register_domain_blueprints(app):
    app.register_blueprint(mesa_shop_bp)
    app.register_blueprint(catalog_bp)
    app.register_blueprint(retail_catalog_bp)
    app.register_blueprint(platform_admin_bp)
    app.register_blueprint(financeiro_bp)
