-- Supabase starter schema for the inventory system.
-- Run this later in the Supabase SQL editor when you are ready to move from
-- browser-only Vercel storage to a shared cloud database.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS products (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  barcode text NOT NULL UNIQUE,
  name text NOT NULL,
  sku text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS locations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL UNIQUE,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS stock_levels (
  product_id uuid NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  location_id uuid NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
  quantity integer NOT NULL DEFAULT 0 CHECK (quantity >= 0),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (product_id, location_id)
);

CREATE TABLE IF NOT EXISTS stock_movements (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  movement_type text NOT NULL CHECK (
    movement_type IN ('STOCK_IN', 'STOCK_OUT', 'TRANSFER')
  ),
  product_id uuid NOT NULL REFERENCES products(id),
  from_location_id uuid REFERENCES locations(id),
  to_location_id uuid REFERENCES locations(id),
  quantity integer NOT NULL CHECK (quantity > 0),
  note text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS stock_movements_created_at_idx
  ON stock_movements(created_at DESC);

CREATE OR REPLACE VIEW current_stock AS
SELECT
  products.barcode,
  products.name AS product_name,
  locations.name AS location,
  stock_levels.quantity
FROM stock_levels
JOIN products ON products.id = stock_levels.product_id
JOIN locations ON locations.id = stock_levels.location_id
WHERE stock_levels.quantity > 0
ORDER BY products.name, locations.name;

CREATE OR REPLACE VIEW movement_history AS
SELECT
  stock_movements.id,
  stock_movements.movement_type,
  products.barcode,
  products.name AS product_name,
  from_locations.name AS from_location,
  to_locations.name AS to_location,
  stock_movements.quantity,
  stock_movements.note,
  stock_movements.created_at
FROM stock_movements
JOIN products ON products.id = stock_movements.product_id
LEFT JOIN locations AS from_locations
  ON from_locations.id = stock_movements.from_location_id
LEFT JOIN locations AS to_locations
  ON to_locations.id = stock_movements.to_location_id
ORDER BY stock_movements.created_at DESC;

CREATE OR REPLACE FUNCTION stock_in(
  p_barcode text,
  p_product_name text,
  p_location text,
  p_quantity integer,
  p_note text DEFAULT ''
) RETURNS uuid
LANGUAGE plpgsql
AS $$
DECLARE
  v_barcode text := trim(p_barcode);
  v_location text := trim(p_location);
  v_product_id uuid;
  v_location_id uuid;
  v_movement_id uuid;
BEGIN
  IF v_barcode = '' THEN
    RAISE EXCEPTION 'barcode is required';
  END IF;
  IF v_location = '' THEN
    RAISE EXCEPTION 'location is required';
  END IF;
  IF p_quantity <= 0 THEN
    RAISE EXCEPTION 'quantity must be greater than zero';
  END IF;

  INSERT INTO products (barcode, name)
  VALUES (
    v_barcode,
    COALESCE(NULLIF(trim(p_product_name), ''), 'Item ' || v_barcode)
  )
  ON CONFLICT (barcode) DO UPDATE
    SET name = COALESCE(NULLIF(trim(p_product_name), ''), products.name)
  RETURNING id INTO v_product_id;

  INSERT INTO locations (name)
  VALUES (v_location)
  ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
  RETURNING id INTO v_location_id;

  INSERT INTO stock_levels (product_id, location_id, quantity)
  VALUES (v_product_id, v_location_id, p_quantity)
  ON CONFLICT (product_id, location_id) DO UPDATE
    SET quantity = stock_levels.quantity + EXCLUDED.quantity,
        updated_at = now();

  INSERT INTO stock_movements (
    movement_type,
    product_id,
    from_location_id,
    to_location_id,
    quantity,
    note
  )
  VALUES (
    'STOCK_IN',
    v_product_id,
    NULL,
    v_location_id,
    p_quantity,
    COALESCE(p_note, '')
  )
  RETURNING id INTO v_movement_id;

  RETURN v_movement_id;
END;
$$;

CREATE OR REPLACE FUNCTION stock_out(
  p_barcode text,
  p_location text,
  p_quantity integer,
  p_note text DEFAULT ''
) RETURNS uuid
LANGUAGE plpgsql
AS $$
DECLARE
  v_barcode text := trim(p_barcode);
  v_location text := trim(p_location);
  v_product_id uuid;
  v_location_id uuid;
  v_current_quantity integer := 0;
  v_movement_id uuid;
BEGIN
  IF v_barcode = '' THEN
    RAISE EXCEPTION 'barcode is required';
  END IF;
  IF v_location = '' THEN
    RAISE EXCEPTION 'location is required';
  END IF;
  IF p_quantity <= 0 THEN
    RAISE EXCEPTION 'quantity must be greater than zero';
  END IF;

  SELECT id INTO v_product_id FROM products WHERE barcode = v_barcode;
  IF v_product_id IS NULL THEN
    RAISE EXCEPTION 'No product found for barcode %', v_barcode;
  END IF;

  SELECT id INTO v_location_id FROM locations WHERE name = v_location;
  IF v_location_id IS NULL THEN
    RAISE EXCEPTION 'Location % was not found', v_location;
  END IF;

  SELECT quantity INTO v_current_quantity
  FROM stock_levels
  WHERE product_id = v_product_id AND location_id = v_location_id
  FOR UPDATE;

  v_current_quantity := COALESCE(v_current_quantity, 0);
  IF v_current_quantity < p_quantity THEN
    RAISE EXCEPTION 'Only % units available at this location', v_current_quantity;
  END IF;

  UPDATE stock_levels
  SET quantity = quantity - p_quantity,
      updated_at = now()
  WHERE product_id = v_product_id AND location_id = v_location_id;

  INSERT INTO stock_movements (
    movement_type,
    product_id,
    from_location_id,
    to_location_id,
    quantity,
    note
  )
  VALUES (
    'STOCK_OUT',
    v_product_id,
    v_location_id,
    NULL,
    p_quantity,
    COALESCE(p_note, '')
  )
  RETURNING id INTO v_movement_id;

  RETURN v_movement_id;
END;
$$;

CREATE OR REPLACE FUNCTION transfer_stock(
  p_barcode text,
  p_from_location text,
  p_to_location text,
  p_quantity integer,
  p_note text DEFAULT ''
) RETURNS uuid
LANGUAGE plpgsql
AS $$
DECLARE
  v_barcode text := trim(p_barcode);
  v_from_location text := trim(p_from_location);
  v_to_location text := trim(p_to_location);
  v_product_id uuid;
  v_from_location_id uuid;
  v_to_location_id uuid;
  v_current_quantity integer := 0;
  v_movement_id uuid;
BEGIN
  IF v_barcode = '' THEN
    RAISE EXCEPTION 'barcode is required';
  END IF;
  IF v_from_location = '' THEN
    RAISE EXCEPTION 'from_location is required';
  END IF;
  IF v_to_location = '' THEN
    RAISE EXCEPTION 'to_location is required';
  END IF;
  IF lower(v_from_location) = lower(v_to_location) THEN
    RAISE EXCEPTION 'Source and destination locations must differ';
  END IF;
  IF p_quantity <= 0 THEN
    RAISE EXCEPTION 'quantity must be greater than zero';
  END IF;

  SELECT id INTO v_product_id FROM products WHERE barcode = v_barcode;
  IF v_product_id IS NULL THEN
    RAISE EXCEPTION 'No product found for barcode %', v_barcode;
  END IF;

  SELECT id INTO v_from_location_id FROM locations WHERE name = v_from_location;
  IF v_from_location_id IS NULL THEN
    RAISE EXCEPTION 'Location % was not found', v_from_location;
  END IF;

  INSERT INTO locations (name)
  VALUES (v_to_location)
  ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
  RETURNING id INTO v_to_location_id;

  SELECT quantity INTO v_current_quantity
  FROM stock_levels
  WHERE product_id = v_product_id AND location_id = v_from_location_id
  FOR UPDATE;

  v_current_quantity := COALESCE(v_current_quantity, 0);
  IF v_current_quantity < p_quantity THEN
    RAISE EXCEPTION 'Only % units available at this location', v_current_quantity;
  END IF;

  UPDATE stock_levels
  SET quantity = quantity - p_quantity,
      updated_at = now()
  WHERE product_id = v_product_id AND location_id = v_from_location_id;

  INSERT INTO stock_levels (product_id, location_id, quantity)
  VALUES (v_product_id, v_to_location_id, p_quantity)
  ON CONFLICT (product_id, location_id) DO UPDATE
    SET quantity = stock_levels.quantity + EXCLUDED.quantity,
        updated_at = now();

  INSERT INTO stock_movements (
    movement_type,
    product_id,
    from_location_id,
    to_location_id,
    quantity,
    note
  )
  VALUES (
    'TRANSFER',
    v_product_id,
    v_from_location_id,
    v_to_location_id,
    p_quantity,
    COALESCE(p_note, '')
  )
  RETURNING id INTO v_movement_id;

  RETURN v_movement_id;
END;
$$;

-- Enable Row Level Security before using this in a real business app.
-- Add policies that fit your authentication model. For example, after adding
-- Supabase Auth users, grant read/RPC access to authenticated users only.
ALTER TABLE products ENABLE ROW LEVEL SECURITY;
ALTER TABLE locations ENABLE ROW LEVEL SECURITY;
ALTER TABLE stock_levels ENABLE ROW LEVEL SECURITY;
ALTER TABLE stock_movements ENABLE ROW LEVEL SECURITY;
