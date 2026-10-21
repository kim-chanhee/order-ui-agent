-- Curated, read-only semantic views for Text2SQL.
-- Raw OCEL tables remain unchanged; these views expose one clear business grain.

CREATE VIEW IF NOT EXISTS analysis_order_item_products AS
SELECT
    order_item.ocel_source_id AS order_id,
    order_item.ocel_target_id AS item_id,
    item_product.ocel_target_id AS product_name
FROM object_object AS order_item
JOIN object_object AS item_product
  ON item_product.ocel_source_id = order_item.ocel_target_id
 AND item_product.ocel_qualifier = 'is a'
WHERE order_item.ocel_qualifier = 'comprises';

CREATE VIEW IF NOT EXISTS analysis_failed_delivery_orders AS
SELECT DISTINCT
    event_id AS failure_event_id,
    status_at AS failed_at,
    order_id,
    package_id,
    courier_id,
    customer_id
FROM analysis_shipment_status_orders
WHERE event_type = 'failed delivery';

CREATE VIEW IF NOT EXISTS analysis_failed_delivery_items AS
SELECT DISTINCT
    failed.failure_event_id,
    failed.failed_at,
    failed.order_id,
    failed.package_id,
    failed.customer_id,
    item.item_id,
    item.product_name
FROM analysis_failed_delivery_orders AS failed
JOIN analysis_order_item_products AS item
  ON item.order_id = failed.order_id;
