"""
Seed script for Menu Engineering Module - Custom Client ID
This script creates test data for a specific client_id.
"""

import os
import sys
from datetime import datetime, timedelta
from decimal import Decimal

import mysql.connector
from dotenv import load_dotenv

load_dotenv()


def get_hml_connection():
    """Get connection to homologation database."""
    host = os.getenv("MYSQL_HOST", "92.113.33.100")
    user = os.getenv("MYSQL_USER_HML") or os.getenv("MYSQL_USER", "pctrim_hml")
    password = os.getenv("MYSQL_PASSWORD_HML") or os.getenv("MYSQL_PASSWORD", "")
    port = int(os.getenv("MYSQL_PORT", "3308"))
    database = os.getenv("MYSQL_DATABASE_HML", "pctrim_commerce_hml")
    
    return mysql.connector.connect(
        host=host,
        user=user,
        password=password,
        port=port,
        database=database,
        autocommit=False
    )


def seed_menu_engineering(client_id):
    """Seed Menu Engineering data for a specific client_id."""
    # Configurable product_id for recipe (use existing or fictitious)
    PRODUCT_ID = 9999  # Change this to an existing product_id if needed
    
    conn = None
    cursor = None
    
    try:
        conn = get_hml_connection()
        cursor = conn.cursor(dictionary=True)
        
        print(f"Connected to database: {conn.database}")
        print(f"Seeding data for client_id: {client_id}")
        
        # Clean existing data for this client
        print("Cleaning existing data...")
        cursor.execute("DELETE FROM recipe_ingredients WHERE client_id = %s", (client_id,))
        cursor.execute("DELETE FROM recipes WHERE client_id = %s", (client_id,))
        cursor.execute("DELETE FROM ingredient_price_history WHERE client_id = %s", (client_id,))
        cursor.execute("DELETE FROM ingredients WHERE client_id = %s", (client_id,))
        
        # Insert ingredients
        print("Inserting ingredients...")
        ingredients_data = [
            ("carne moída", "g", "protein", 0.2500),  # R$ 0.25 per gram
            ("queijo", "g", "dairy", 0.6667),       # R$ 0.6667 per gram
            ("pão", "unit", "bakery", 1.5000),      # R$ 1.50 per unit
            ("alface", "g", "vegetables", 0.0500), # R$ 0.05 per gram
            ("tomate", "g", "vegetables", 0.0800)  # R$ 0.08 per gram
        ]
        
        ingredient_ids = {}
        for name, unit_type, category, cost in ingredients_data:
            cursor.execute(
                """INSERT INTO ingredients (client_id, name, unit_type, current_cost_per_unit, category)
                   VALUES (%s, %s, %s, %s, %s)""",
                (client_id, name, unit_type, cost, category)
            )
            ingredient_ids[name] = cursor.lastrowid
            print(f"  - Created ingredient: {name} (ID: {ingredient_ids[name]})")
        
        # Insert price history (2 records per ingredient over last 14 days)
        print("Inserting price history...")
        now = datetime.now()
        
        history_data = [
            ("carne moída", 0.2500, -1),   # 1 day ago
            ("carne moída", 0.2300, -8),   # 8 days ago
            ("queijo", 0.6667, -2),        # 2 days ago
            ("queijo", 0.6000, -10),       # 10 days ago
            ("pão", 1.5000, -3),           # 3 days ago
            ("pão", 1.4000, -12),          # 12 days ago
            ("alface", 0.0500, -1),        # 1 day ago
            ("alface", 0.0450, -7),        # 7 days ago
            ("tomate", 0.0800, -2),        # 2 days ago
            ("tomate", 0.0750, -9),        # 9 days ago
        ]
        
        for name, cost, days_offset in history_data:
            ingredient_id = ingredient_ids[name]
            created_at = now + timedelta(days=days_offset)
            cursor.execute(
                """INSERT INTO ingredient_price_history (client_id, ingredient_id, cost_per_unit, source, created_at)
                   VALUES (%s, %s, %s, %s, %s)""",
                (client_id, ingredient_id, cost, "seed", created_at)
            )
            print(f"  - Price history for {name}: R$ {cost} ({days_offset} days)")
        
        # Get existing product_ids for this client
        print("Getting existing product_ids...")
        cursor.execute(
            "SELECT chave FROM produtos WHERE id_cliente = %s LIMIT 10",
            (client_id,)
        )
        products = cursor.fetchall()
        
        if not products:
            print("  WARNING: No products found for this client!")
            print("  Creating recipes with fictitious product_ids (will fail in cost calculation)")
            product_ids = [10000, 10001, 10002]
        else:
            product_ids = [p['chave'] for p in products]
            print(f"  Found {len(product_ids)} existing products")
        
        # Insert recipes using real product_ids
        print("Inserting recipes...")
        recipes_data = []
        if len(product_ids) >= 3:
            recipes_data = [
                (product_ids[0], "Produto 1 - Receita"),
                (product_ids[1], "Produto 2 - Receita"),
                (product_ids[2], "Produto 3 - Receita")
            ]
        elif len(product_ids) >= 1:
            recipes_data = [
                (product_ids[0], "Produto 1 - Receita")
            ]
        else:
            recipes_data = [
                (10000, "Receita Teste (sem produto)")
            ]
        
        recipe_ids = {}
        for prod_id, name in recipes_data:
            cursor.execute(
                """INSERT INTO recipes (client_id, product_id, name)
                   VALUES (%s, %s, %s)""",
                (client_id, prod_id, name)
            )
            recipe_id = cursor.lastrowid
            recipe_ids[name] = recipe_id
            print(f"  - Created recipe: {name} (ID: {recipe_id}, product_id: {prod_id})")
        
        # Insert recipe ingredients
        print("Inserting recipe ingredients...")
        recipe_ingredients_data = [
            ("Burger Classic", "carne moída", 120.0),  # 120g
            ("Burger Classic", "queijo", 30.0),        # 30g
            ("Burger Classic", "pão", 1.0),            # 1 unit
            ("X-Salada", "carne moída", 100.0),        # 100g
            ("X-Salada", "queijo", 25.0),              # 25g
            ("X-Salada", "alface", 20.0),              # 20g
            ("X-Salada", "tomate", 25.0),              # 25g
            ("X-Salada", "pão", 1.0),                  # 1 unit
            ("Suco Natural", "alface", 50.0),         # 50g
            ("Suco Natural", "tomate", 100.0),        # 100g
        ]
        
        for recipe_name, ingredient_name, quantity in recipe_ingredients_data:
            recipe_id = recipe_ids[recipe_name]
            ingredient_id = ingredient_ids[ingredient_name]
            cursor.execute(
                """INSERT INTO recipe_ingredients (client_id, recipe_id, ingredient_id, quantity)
                   VALUES (%s, %s, %s, %s)""",
                (client_id, recipe_id, ingredient_id, quantity)
            )
            print(f"  - Added {ingredient_name} to {recipe_name}: {quantity}")
        
        conn.commit()
        print("\n✓ Seed completed successfully!")
        print(f"\nSummary:")
        print(f"  - Ingredients: {len(ingredients_data)}")
        print(f"  - Price history records: {len(history_data)}")
        print(f"  - Recipes: {len(recipes_data)}")
        print(f"  - Recipe ingredients: {len(recipe_ingredients_data)}")
        
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"\n✗ Error during seeding: {e}")
        raise
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


if __name__ == "__main__":
    print("=" * 60)
    print("Menu Engineering Seed Script - Custom Client")
    print("Environment: Homologation (pctrim_commerce_hml)")
    print("=" * 60)
    print()
    
    # Get client_id from command line or prompt
    if len(sys.argv) > 1:
        try:
            client_id = int(sys.argv[1])
        except ValueError:
            print("Invalid client_id. Must be a number.")
            sys.exit(1)
    else:
        try:
            client_id = int(input("Enter client_id: "))
        except ValueError:
            print("Invalid client_id. Must be a number.")
            sys.exit(1)
    
    # Safety check
    db = os.getenv("MYSQL_DATABASE_HML", "pctrim_commerce_hml")
    if "hml" not in db.lower() and "homolog" not in db.lower():
        print("WARNING: Database name does not appear to be homologation!")
        print(f"Current database: {db}")
        response = input("Continue anyway? (yes/no): ")
        if response.lower() != "yes":
            print("Aborted.")
            sys.exit(1)
    
    try:
        seed_menu_engineering(client_id)
    except Exception as e:
        print(f"Script failed: {e}")
        sys.exit(1)
