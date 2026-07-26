"""Menu Engineering Module - Cost and Margin Intelligence for Restaurants."""
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from decimal import Decimal, DivisionByZero

from flask import Blueprint, jsonify, request, session, render_template

from database import conectar, transaction
from decorators import login_required, restaurant_only
from services.dados_loja import obter_dados_loja

menu_engineering_bp = Blueprint("menu_engineering", __name__)


def _normalize_name(name: str) -> str:
    """Normalize ingredient name: trim + lowercase."""
    if not name:
        return ""
    return str(name).strip().lower()


def _ensure_tables_exist(cursor):
    """Create Menu Engineering tables if they don't exist."""
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ingredients (
            id INT AUTO_INCREMENT PRIMARY KEY,
            client_id INT NOT NULL,
            name VARCHAR(255) NOT NULL,
            unit_type VARCHAR(50) NOT NULL COMMENT 'g, kg, unit, liter, ml, etc',
            current_cost_per_unit DECIMAL(10, 4) NOT NULL DEFAULT 0.0000,
            category VARCHAR(100) NOT NULL COMMENT 'protein, dairy, bakery, vegetables, etc',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY unique_ingredient_client (name, client_id),
            INDEX idx_client_id (client_id),
            INDEX idx_category (category)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ingredient_price_history (
            id INT AUTO_INCREMENT PRIMARY KEY,
            client_id INT NOT NULL,
            ingredient_id INT NOT NULL,
            cost_per_unit DECIMAL(10, 4) NOT NULL,
            source VARCHAR(255) NOT NULL COMMENT 'NF-e import, manual, etc',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_client_id (client_id),
            INDEX idx_ingredient_id (ingredient_id),
            INDEX idx_created_at (created_at),
            FOREIGN KEY (ingredient_id) REFERENCES ingredients(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS recipes (
            id INT AUTO_INCREMENT PRIMARY KEY,
            client_id INT NOT NULL,
            product_id INT NOT NULL COMMENT 'Logical reference to existing product (read-only)',
            name VARCHAR(255) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_client_id (client_id),
            INDEX idx_product_id (product_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS recipe_ingredients (
            id INT AUTO_INCREMENT PRIMARY KEY,
            client_id INT NOT NULL,
            recipe_id INT NOT NULL,
            ingredient_id INT NOT NULL,
            quantity DECIMAL(10, 4) NOT NULL COMMENT 'Quantity in ingredient unit_type',
            INDEX idx_client_id (client_id),
            INDEX idx_recipe_id (recipe_id),
            INDEX idx_ingredient_id (ingredient_id),
            FOREIGN KEY (recipe_id) REFERENCES recipes(id) ON DELETE CASCADE,
            FOREIGN KEY (ingredient_id) REFERENCES ingredients(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)


_me_schema_ready_targets: set[str] = set()


def _tenant_schema_key() -> str:
    from database import resolve_tenant_db_target

    return resolve_tenant_db_target() or "production"


def _ensure_me_schema():
    target = _tenant_schema_key()
    if target in _me_schema_ready_targets:
        return
    conn = conectar()
    try:
        cursor = conn.cursor()
        _ensure_tables_exist(cursor)
        conn.commit()
        _me_schema_ready_targets.add(target)
    finally:
        cursor.close()
        conn.close()


@menu_engineering_bp.before_request
def _menu_engineering_prepare_schema():
    if "usuario_logado" not in session:
        return None
    _ensure_me_schema()


@menu_engineering_bp.route("/menu-engineering/import-xml", methods=["POST"])
@login_required
@restaurant_only
def import_xml():
    """Import NF-e XML to update ingredient costs."""
    try:
        data = request.get_json()
        xml_content = data.get("xml")
        
        if not xml_content:
            return jsonify({"erro": "XML content is required"}), 400
        
        id_cliente = session.get("id_cliente")
        if not id_cliente:
            return jsonify({"erro": "id_cliente not found in session"}), 401
        
        # Parse XML
        root = ET.fromstring(xml_content)
        
        # Find NFe/infNFe/det elements
        nfe = root.find(".//NFe")
        if nfe is None:
            return jsonify({"erro": "NFe element not found in XML"}), 400
        
        inf_nfe = nfe.find("infNFe")
        if inf_nfe is None:
            return jsonify({"erro": "infNFe element not found in XML"}), 400
        
        det_elements = inf_nfe.findall("det")
        if not det_elements:
            return jsonify({"erro": "No det elements found in XML"}), 400
        
        imported_count = 0
        errors = []
        imported_items = []
        
        with transaction() as conn:
            cursor = conn.cursor(dictionary=True)
            _ensure_tables_exist(cursor)
            
            for det in det_elements:
                try:
                    prod = det.find("prod")
                    if prod is None:
                        errors.append("det element missing prod")
                        continue
                    
                    x_prod = prod.find("xProd")
                    q_com = prod.find("qCom")
                    v_prod = prod.find("vProd")
                    
                    if x_prod is None or q_com is None or v_prod is None:
                        errors.append("prod element missing required fields")
                        continue
                    
                    name = x_prod.text if x_prod.text else ""
                    quantity_str = q_com.text if q_com.text else "0"
                    value_str = v_prod.text if v_prod.text else "0"
                    
                    # Normalize name
                    normalized_name = _normalize_name(name)
                    if not normalized_name:
                        errors.append(f"Empty product name: {name}")
                        continue
                    
                    # Parse quantity and value
                    try:
                        quantity = Decimal(quantity_str)
                        value = Decimal(value_str)
                    except Exception as e:
                        errors.append(f"Invalid quantity or value for {name}: {e}")
                        continue
                    
                    # Calculate cost per unit (avoid division by zero)
                    if quantity == 0:
                        errors.append(f"Zero quantity for {name}, skipping")
                        continue
                    
                    cost_per_unit = value / quantity
                    
                    # Check if ingredient exists (by normalized name + client_id)
                    cursor.execute(
                        "SELECT id, unit_type, category FROM ingredients WHERE name = %s AND client_id = %s LIMIT 1",
                        (normalized_name, id_cliente)
                    )
                    existing = cursor.fetchone()
                    
                    if existing:
                        ingredient_id = existing["id"]
                        unit_type = existing["unit_type"]
                        category = existing["category"]
                        
                        # Update current cost
                        cursor.execute(
                            "UPDATE ingredients SET current_cost_per_unit = %s WHERE id = %s",
                            (float(cost_per_unit), ingredient_id)
                        )
                    else:
                        # Create new ingredient (default unit_type and category)
                        unit_type = "unit"
                        category = "other"
                        
                        cursor.execute(
                            """INSERT INTO ingredients (client_id, name, unit_type, current_cost_per_unit, category)
                               VALUES (%s, %s, %s, %s, %s)""",
                            (id_cliente, normalized_name, unit_type, float(cost_per_unit), category)
                        )
                        ingredient_id = cursor.lastrowid
                    
                    # Insert into price history
                    cursor.execute(
                        """INSERT INTO ingredient_price_history (client_id, ingredient_id, cost_per_unit, source)
                           VALUES (%s, %s, %s, %s)""",
                        (id_cliente, ingredient_id, float(cost_per_unit), "NF-e import")
                    )
                    
                    imported_count += 1
                    
                    # Track imported item for preview
                    imported_items.append({
                        "name": normalized_name,
                        "cost_per_unit": float(cost_per_unit),
                        "unit_type": unit_type
                    })
                    
                except Exception as e:
                    errors.append(f"Error processing item: {str(e)}")
                    continue
            
            conn.commit()
        
        return jsonify({
            "sucesso": True,
            "imported_count": imported_count,
            "errors": errors,
            "imported_items": imported_items
        })
        
    except ET.ParseError as e:
        return jsonify({"erro": f"XML parsing error: {str(e)}"}), 400
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


@menu_engineering_bp.route("/menu-engineering/ingredients", methods=["GET"])
@login_required
@restaurant_only
def list_ingredients():
    """List all ingredients for the current client."""
    try:
        id_cliente = session.get("id_cliente")
        # TEMPORARY: Use default client_id for testing if not in session
        if not id_cliente:
            id_cliente = 2003  # Use client 2003 for testing
            print(f"WARNING: Using default client_id={id_cliente} for testing")
        
        conn = conectar()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute(
            """SELECT id, name, unit_type, current_cost_per_unit, category, created_at
               FROM ingredients WHERE client_id = %s ORDER BY name""",
            (id_cliente,)
        )
        
        ingredients = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        return jsonify({"ingredients": ingredients})
        
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


@menu_engineering_bp.route("/menu-engineering/ingredients", methods=["POST"])
@login_required
@restaurant_only
def create_ingredient():
    """Create a new ingredient for the current client."""
    try:
        id_cliente = session.get("id_cliente")
        # TEMPORARY: Use default client_id for testing if not in session
        if not id_cliente:
            id_cliente = 2003  # Use client 2003 for testing
            print(f"WARNING: Using default client_id={id_cliente} for testing")
        
        data = request.get_json()
        
        name = data.get("name")
        unit_type = data.get("unit_type", "g")
        current_cost_per_unit = data.get("current_cost_per_unit")
        category = data.get("category", "other")
        
        if not name or current_cost_per_unit is None:
            return jsonify({"erro": "Missing required fields: name, current_cost_per_unit"}), 400
        
        conn = conectar()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute(
            """INSERT INTO ingredients (client_id, name, unit_type, current_cost_per_unit, category)
               VALUES (%s, %s, %s, %s, %s)""",
            (id_cliente, name, unit_type, current_cost_per_unit, category)
        )
        
        ingredient_id = cursor.lastrowid
        
        # Also add to price history
        cursor.execute(
            """INSERT INTO ingredient_price_history (ingredient_id, cost_per_unit, recorded_at)
               VALUES (%s, %s, NOW())""",
            (ingredient_id, current_cost_per_unit)
        )
        
        conn.commit()
        
        cursor.execute(
            """SELECT id, name, unit_type, current_cost_per_unit, category, created_at
               FROM ingredients WHERE id = %s""",
            (ingredient_id,)
        )
        
        ingredient = cursor.fetchone()
        
        cursor.close()
        conn.close()
        
        return jsonify({"sucesso": True, "ingredient": ingredient}), 201
        
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


@menu_engineering_bp.route("/menu-engineering/ingredients/<int:ingredient_id>", methods=["PUT"])
@login_required
@restaurant_only
def update_ingredient(ingredient_id):
    """Update an existing ingredient."""
    try:
        id_cliente = session.get("id_cliente")
        # TEMPORARY: Use default client_id for testing if not in session
        if not id_cliente:
            id_cliente = 2003  # Use client 2003 for testing
            print(f"WARNING: Using default client_id={id_cliente} for testing")
        
        data = request.get_json()
        
        name = data.get("name")
        unit_type = data.get("unit_type")
        current_cost_per_unit = data.get("current_cost_per_unit")
        category = data.get("category")
        
        if not any([name, unit_type, current_cost_per_unit is not None, category]):
            return jsonify({"erro": "No fields to update"}), 400
        
        conn = conectar()
        cursor = conn.cursor(dictionary=True)
        
        # Check if ingredient belongs to client
        cursor.execute(
            """SELECT id FROM ingredients WHERE id = %s AND client_id = %s""",
            (ingredient_id, id_cliente)
        )
        
        if not cursor.fetchone():
            cursor.close()
            conn.close()
            return jsonify({"erro": "Ingredient not found"}), 404
        
        # Build update query dynamically
        update_fields = []
        update_values = []
        
        if name:
            update_fields.append("name = %s")
            update_values.append(name)
        
        if unit_type:
            update_fields.append("unit_type = %s")
            update_values.append(unit_type)
        
        if current_cost_per_unit is not None:
            update_fields.append("current_cost_per_unit = %s")
            update_values.append(current_cost_per_unit)
        
        if category:
            update_fields.append("category = %s")
            update_values.append(category)
        
        update_values.append(ingredient_id)
        
        cursor.execute(
            f"""UPDATE ingredients SET {', '.join(update_fields)} WHERE id = %s""",
            update_values
        )
        
        # If cost changed, add to price history
        if current_cost_per_unit is not None:
            cursor.execute(
                """INSERT INTO ingredient_price_history (ingredient_id, cost_per_unit, recorded_at)
                   VALUES (%s, %s, NOW())""",
                (ingredient_id, current_cost_per_unit)
            )
        
        conn.commit()
        
        cursor.execute(
            """SELECT id, name, unit_type, current_cost_per_unit, category, created_at
               FROM ingredients WHERE id = %s""",
            (ingredient_id,)
        )
        
        ingredient = cursor.fetchone()
        
        cursor.close()
        conn.close()
        
        return jsonify({"sucesso": True, "ingredient": ingredient})
        
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


@menu_engineering_bp.route("/menu-engineering/categories", methods=["POST"])
@login_required
@restaurant_only
def create_category():
    """Create a new custom category for the current client."""
    try:
        id_cliente = session.get("id_cliente")
        # TEMPORARY: Use default client_id for testing if not in session
        if not id_cliente:
            id_cliente = 2003  # Use client 2003 for testing
            print(f"WARNING: Using default client_id={id_cliente} for testing")
        
        data = request.get_json()
        
        name = data.get("name")
        slug = data.get("slug")
        
        if not name or not slug:
            return jsonify({"erro": "Missing required fields: name, slug"}), 400
        
        conn = conectar()
        cursor = conn.cursor(dictionary=True)
        
        # Check if category already exists for this client
        cursor.execute(
            """SELECT id FROM ingredient_categories WHERE client_id = %s AND slug = %s""",
            (id_cliente, slug)
        )
        
        if cursor.fetchone():
            cursor.close()
            conn.close()
            return jsonify({"erro": "Category already exists"}), 400
        
        cursor.execute(
            """INSERT INTO ingredient_categories (client_id, name, slug)
               VALUES (%s, %s, %s)""",
            (id_cliente, name, slug)
        )
        
        category_id = cursor.lastrowid
        conn.commit()
        
        cursor.execute(
            """SELECT id, name, slug, created_at FROM ingredient_categories WHERE id = %s""",
            (category_id,)
        )
        
        category = cursor.fetchone()
        
        cursor.close()
        conn.close()
        
        return jsonify({"sucesso": True, "category": category}), 201
        
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


@menu_engineering_bp.route("/menu-engineering/recipes", methods=["GET"])
@login_required
@restaurant_only
def list_recipes():
    """List all recipes for the current client with cost and margin calculations."""
    try:
        id_cliente = session.get("id_cliente")
        # TEMPORARY: Use default client_id for testing if not in session
        if not id_cliente:
            id_cliente = 2003  # Use client 2003 for testing
            print(f"WARNING: Using default client_id={id_cliente} for testing")
        
        conn = conectar()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute(
            """SELECT id, client_id, product_id, name, created_at
               FROM recipes WHERE client_id = %s ORDER BY name""",
            (id_cliente,)
        )
        
        recipes = cursor.fetchall()
        
        # Calculate cost and margin for each recipe
        for recipe in recipes:
            # Get product price
            cursor.execute(
                "SELECT preco FROM produtos WHERE chave = %s AND id_cliente = %s LIMIT 1",
                (recipe["product_id"], id_cliente)
            )
            product = cursor.fetchone()
            
            if product:
                price = Decimal(str(product["preco"]))
            else:
                price = Decimal("0")
            
            # Get recipe ingredients
            cursor.execute(
                """SELECT ri.quantity, i.current_cost_per_unit
                   FROM recipe_ingredients ri
                   JOIN ingredients i ON ri.ingredient_id = i.id
                   WHERE ri.recipe_id = %s AND ri.client_id = %s""",
                (recipe["id"], id_cliente)
            )
            
            ingredients = cursor.fetchall()
            
            # Calculate total cost
            total_cost = Decimal("0")
            for ing in ingredients:
                quantity = Decimal(str(ing["quantity"]))
                cost_per_unit = Decimal(str(ing["current_cost_per_unit"]))
                total_cost += quantity * cost_per_unit
            
            # Calculate margin
            if price == 0:
                margin = Decimal("0")
            else:
                margin = (price - total_cost) / price
            
            recipe["cost"] = float(total_cost)
            recipe["price"] = float(price)
            recipe["margin"] = float(margin)
        
        cursor.close()
        conn.close()
        
        return jsonify({"recipes": recipes})
        
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


@menu_engineering_bp.route("/menu-engineering/recipe/<int:recipe_id>/cost", methods=["GET"])
@login_required
@restaurant_only
def recipe_cost(recipe_id):
    """Calculate recipe cost and margin."""
    try:
        id_cliente = session.get("id_cliente")
        if not id_cliente:
            return jsonify({"erro": "id_cliente not found in session"}), 401
        
        conn = conectar()
        cursor = conn.cursor(dictionary=True)
        
        # Get recipe
        cursor.execute(
            "SELECT id, product_id, name FROM recipes WHERE id = %s AND client_id = %s LIMIT 1",
            (recipe_id, id_cliente)
        )
        recipe = cursor.fetchone()
        
        if not recipe:
            cursor.close()
            conn.close()
            return jsonify({"erro": "Recipe not found"}), 404
        
        # Get product price from existing products table (read-only)
        cursor.execute(
            "SELECT preco FROM produtos WHERE chave = %s AND id_cliente = %s LIMIT 1",
            (recipe["product_id"], id_cliente)
        )
        product = cursor.fetchone()
        
        if not product:
            cursor.close()
            conn.close()
            return jsonify({"erro": "Product not found"}), 404
        
        price = Decimal(str(product["preco"]))
        
        # Get recipe ingredients with current costs and details
        cursor.execute(
            """SELECT ri.quantity, i.current_cost_per_unit, i.name, i.unit_type
               FROM recipe_ingredients ri
               JOIN ingredients i ON ri.ingredient_id = i.id
               WHERE ri.recipe_id = %s AND ri.client_id = %s""",
            (recipe_id, id_cliente)
        )
        
        ingredients = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        # Calculate total cost and prepare ingredient details
        total_cost = Decimal("0")
        ingredient_details = []
        for ing in ingredients:
            quantity = Decimal(str(ing["quantity"]))
            cost_per_unit = Decimal(str(ing["current_cost_per_unit"]))
            ingredient_cost = quantity * cost_per_unit
            total_cost += ingredient_cost
            
            ingredient_details.append({
                "name": ing["name"],
                "qty": f"{quantity} {ing['unit_type']}",
                "cost": float(ingredient_cost)
            })
        
        # Calculate margin (avoid division by zero)
        if price == 0:
            margin = Decimal("0")
        else:
            margin = (price - total_cost) / price
        
        return jsonify({
            "recipe_id": recipe_id,
            "recipe_name": recipe["name"],
            "product_id": recipe["product_id"],
            "cost": float(total_cost),
            "price": float(price),
            "margin": float(margin),
            "ingredients": ingredient_details
        })
        
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


@menu_engineering_bp.route("/menu-engineering/category-variation", methods=["GET"])
@login_required
@restaurant_only
def category_variation():
    """Calculate cost variation by category (last 7 days vs previous 7 days)."""
    try:
        id_cliente = session.get("id_cliente")
        # TEMPORARY: Use default client_id for testing if not in session
        if not id_cliente:
            id_cliente = 2003  # Use client 2003 for testing
            print(f"WARNING: Using default client_id={id_cliente} for testing")
        
        conn = conectar()
        cursor = conn.cursor(dictionary=True)
        
        # Calculate date ranges
        now = datetime.now()
        last_7_days_start = now - timedelta(days=7)
        previous_7_days_start = now - timedelta(days=14)
        previous_7_days_end = last_7_days_start
        
        # Get categories
        cursor.execute(
            "SELECT DISTINCT category FROM ingredients WHERE client_id = %s ORDER BY category",
            (id_cliente,)
        )
        categories = [row["category"] for row in cursor.fetchall()]
        
        variations = []
        
        for category in categories:
            # Average cost for last 7 days
            cursor.execute(
                """SELECT AVG(iph.cost_per_unit) as avg_cost
                   FROM ingredient_price_history iph
                   JOIN ingredients i ON iph.ingredient_id = i.id
                   WHERE i.client_id = %s AND i.category = %s
                   AND iph.created_at >= %s""",
                (id_cliente, category, last_7_days_start)
            )
            last_7_result = cursor.fetchone()
            last_7_avg = Decimal(str(last_7_result["avg_cost"])) if last_7_result and last_7_result["avg_cost"] else Decimal("0")
            
            # Average cost for previous 7 days
            cursor.execute(
                """SELECT AVG(iph.cost_per_unit) as avg_cost
                   FROM ingredient_price_history iph
                   JOIN ingredients i ON iph.ingredient_id = i.id
                   WHERE i.client_id = %s AND i.category = %s
                   AND iph.created_at >= %s AND iph.created_at < %s""",
                (id_cliente, category, previous_7_days_start, previous_7_days_end)
            )
            previous_7_result = cursor.fetchone()
            previous_7_avg = Decimal(str(previous_7_result["avg_cost"])) if previous_7_result and previous_7_result["avg_cost"] else Decimal("0")
            
            # Calculate percentage change (avoid division by zero)
            if previous_7_avg == 0:
                percentage_change = Decimal("0")
            else:
                percentage_change = ((last_7_avg - previous_7_avg) / previous_7_avg) * 100
            
            variations.append({
                "category": category,
                "last_7_days_avg": float(last_7_avg),
                "previous_7_days_avg": float(previous_7_avg),
                "percentage_change": float(percentage_change)
            })
        
        cursor.close()
        conn.close()
        
        return jsonify({"variations": variations})
        
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


@menu_engineering_bp.route("/menu-engineering")
@login_required
@restaurant_only
def menu_engineering_page():
    """Render the Menu Engineering UI page."""
    try:
        id_cliente = session.get("id_cliente")
        if not id_cliente:
            return jsonify({"erro": "id_cliente not found in session"}), 401
        
        dados_loja = obter_dados_loja(id_cliente)
        nome_fantasia = dados_loja.get("nome", "Loja")
        
        return render_template(
            "menu_engineering.html",
            nome_fantasia=nome_fantasia,
            id_cliente=id_cliente
        )
        
    except Exception as e:
        return jsonify({"erro": str(e)}), 500
