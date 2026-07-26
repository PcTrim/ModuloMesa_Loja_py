# Menu Engineering Module

## Overview

Menu Engineering is an isolated module for cost and margin intelligence in restaurant products, based on NF-e (Nota Fiscal Eletrônica) XML imports.

## Features

- **Multi-tenant**: All tables and queries filter by `client_id`
- **Isolated**: Deleting this module folder will not break the existing system
- **XML Import**: Parse Brazilian NF-e XML to extract ingredient costs
- **Cost Calculation**: Calculate recipe costs based on ingredient quantities
- **Margin Analysis**: Calculate profit margins (price - cost) / price
- **Category Variation**: Track cost changes by category over time

## Database Schema

### Tables

1. **ingredients**
   - `id` (PK)
   - `client_id` (multi-tenant)
   - `name` (normalized, unique per client)
   - `unit_type` (g, kg, unit, liter, ml, etc)
   - `current_cost_per_unit` (DECIMAL(10,4))
   - `category` (protein, dairy, bakery, vegetables, etc)
   - `created_at`

2. **ingredient_price_history**
   - `id` (PK)
   - `client_id` (multi-tenant)
   - `ingredient_id` (FK → ingredients)
   - `cost_per_unit` (DECIMAL(10,4))
   - `source` (NF-e import, manual, etc)
   - `created_at`

3. **recipes**
   - `id` (PK)
   - `client_id` (multi-tenant)
   - `product_id` (logical reference to existing product)
   - `name`
   - `created_at`

4. **recipe_ingredients**
   - `id` (PK)
   - `client_id` (multi-tenant)
   - `recipe_id` (FK → recipes)
   - `ingredient_id` (FK → ingredients)
   - `quantity` (DECIMAL(10,4))

## API Endpoints

### POST /menu-engineering/import-xml
Import NF-e XML to update ingredient costs.

**Request:**
```json
{
  "xml": "<?xml version=\"1.0\" encoding=\"UTF-8\"?>..."
}
```

**Response:**
```json
{
  "sucesso": true,
  "imported_count": 3,
  "errors": []
}
```

### GET /menu-engineering/ingredients
List all ingredients for the current client.

**Response:**
```json
{
  "ingredients": [
    {
      "id": 1,
      "name": "carne moída",
      "unit_type": "g",
      "current_cost_per_unit": 0.2500,
      "category": "protein",
      "created_at": "2026-07-26T10:00:00"
    }
  ]
}
```

### GET /menu-engineering/recipes
List all recipes for the current client.

**Response:**
```json
{
  "recipes": [
    {
      "id": 1,
      "client_id": 2003,
      "product_id": 9999,
      "name": "Burger Classic",
      "created_at": "2026-07-26T10:00:00"
    }
  ]
}
```

### GET /menu-engineering/recipe/:id/cost
Calculate recipe cost and margin.

**Response:**
```json
{
  "recipe_id": 1,
  "recipe_name": "Burger Classic",
  "product_id": 9999,
  "cost": 48.50,
  "price": 25.00,
  "margin": -0.94
}
```

### GET /menu-engineering/category-variation
Calculate cost variation by category (last 7 days vs previous 7 days).

**Response:**
```json
{
  "variations": [
    {
      "category": "protein",
      "last_7_days_avg": 0.2500,
      "previous_7_days_avg": 0.2300,
      "percentage_change": 8.70
    }
  ]
}
```

## Installation

1. The module is already registered in `blueprints/__init__.py`
2. Tables are created automatically on first use
3. No migration scripts needed - tables are self-contained

## Seed Data

Run the seed script to populate test data for `client_id=2003`:

```bash
python seed_menu_engineering.py
```

**Environment**: Homologation (pctrim_commerce_hml)

**Safety**: The script includes a safety check to prevent running in production.

## Testing

Run the unit tests:

```bash
python test_menu_engineering.py
```

Tests cover:
- XML parsing with the provided validation XML
- Name normalization
- Division by zero handling

## Validation XML

The module has been tested with this exact XML:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<nfeProc>
  <NFe>
    <infNFe>
      <det nItem="1">
        <prod>
          <xProd>Carne Moída</xProd>
          <qCom>1.0000</qCom>
          <vProd>30.00</vProd>
        </prod>
      </det>
      <det nItem="2">
        <prod>
          <xProd>Queijo</xProd>
          <qCom>0.5000</qCom>
          <vProd>20.00</vProd>
        </prod>
      </det>
      <det nItem="3">
        <prod>
          <xProd>Pão</xProd>
          <qCom>10.0000</qCom>
          <vProd>15.00</vProd>
        </prod>
      </det>
    </infNFe>
  </NFe>
</nfeProc>
```

**Expected Results:**
- Carne Moída: R$ 30.00 per unit
- Queijo: R$ 40.00 per unit (20.00 / 0.5)
- Pão: R$ 1.50 per unit (15.00 / 10)

## Key Design Decisions

1. **Isolation**: Module is completely isolated - no modifications to existing tables or business logic
2. **Multi-tenant**: All queries include `client_id` filter
3. **Simplicity**: MVP implementation without complex edge cases
4. **Transaction Safety**: XML import uses transactions to ensure consistency
5. **Division by Zero**: All division operations check for zero before calculating
6. **Name Normalization**: Ingredient names are normalized (trim + lowercase) to prevent duplicates

## Files

- `blueprints/menu_engineering.py` - Main blueprint with API endpoints
- `menu_engineering_schema.sql` - Database schema (for reference)
- `seed_menu_engineering.py` - Seed data script
- `test_menu_engineering.py` - Unit tests
- `MENU_ENGINEERING_README.md` - This file

## Integration Notes

- The module uses the existing `database.py` connection functions
- Uses existing `login_required` decorator from `decorators.py`
- Product prices are read from the existing `produtos` table (read-only)
- No changes to existing authentication or authorization logic
