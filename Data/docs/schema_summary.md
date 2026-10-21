# Order-management semantic schema guide

This file is advisory retrieval context. Live SQLite metadata is authoritative for every table and column.

## Preferred curated analysis views

- 모델은 아래 View가 질문에 필요한 컬럼을 직접 제공하면 원본 OCEL 테이블보다 먼저 사용합니다.
- 물리 컬럼명은 SQL 도구 호환성을 위해 영문 `snake_case`로 유지하며, 아래 한글 설명이 사용자 용어와 연결됩니다.

## analysis_failed_delivery_orders

- Business meaning: 배송 실패가 발생한 주문만 모은 분석 View.
- Korean keywords: 배송 실패 주문, 실패 주문, 배송 실패 건수.
- Row grain: 배송 실패 이벤트와 주문의 고유 연결 한 건.
- Columns: `failure_event_id`=배송 실패 이벤트 ID, `failed_at`=배송 실패 시각, `order_id`=주문 ID, `package_id`=패키지 ID, `courier_id`=배송 기사, `customer_id`=고객 ID.
- Counting: 배송 실패 주문 수는 `COUNT(DISTINCT order_id)`.

## analysis_order_item_products

- Business meaning: 주문에 포함된 개별 물품과 사람이 읽을 수 있는 상품명의 연결 View.
- Korean keywords: 주문 물품, 물품명, 상품명, 주문별 상품.
- Row grain: 주문에 포함된 개별 물품 한 건.
- Columns: `order_id`=주문 ID, `item_id`=개별 물품 내부 ID, `product_name`=상품명/물품명.
- Important: 사용자가 물품명 또는 상품명을 요청하면 `product_name`을 반환하고 `item_id`를 이름으로 대체하지 않습니다.

## analysis_failed_delivery_items

- Business meaning: 배송 실패 주문에 포함된 개별 물품과 상품명을 바로 조회하는 분석 View.
- Korean keywords: 배송 실패 물품, 실패 주문의 물품명, 배송 실패 상품명.
- Row grain: 배송 실패 주문에 포함된 개별 물품 한 건.
- Columns: `failure_event_id`=배송 실패 이벤트 ID, `failed_at`=배송 실패 시각, `order_id`=주문 ID, `package_id`=패키지 ID, `customer_id`=고객 ID, `item_id`=개별 물품 ID, `product_name`=상품명/물품명.
- Names: 이름 목록은 `SELECT DISTINCT product_name`; 내부 물품 ID 목록은 사용자가 ID를 명시적으로 요청한 경우에만 `item_id`를 사용합니다.
- Time: 최근 N일 조건은 `failed_at`을 데이터셋 기준 anchor와 비교합니다.

## analysis_shipment_status_orders

- Business meaning: shipment status events connected to orders, packages, couriers, and customers.
- Korean keywords: 배송 상태, 배송 실패, 배송 완료, 실패 주문, 택배, 배송 기사.
- Row grain: one shipment status event linked to one order.
- Filters: 배송 실패 maps to `event_type = 'failed delivery'`; 배송 완료 maps to `event_type = 'package delivered'`.
- Counting: order counts use `COUNT(DISTINCT order_id)` and customer counts use `COUNT(DISTINCT customer_id)`.
- Time: `status_at` participates in the shared dataset timeline configured in `analysis_semantics.json`.

## analysis_order_events

- Business meaning: order-level lifecycle events connected to an order and customer.
- Korean keywords: 주문, 주문 생명주기, 주문 생성, 주문 확정, 결제, 결제 알림, 배송 실패, 배송 완료.
- Row grain: one order event linked to one order.
- Filters: 결제 maps to `event_type = 'pay order'`; 결제 알림 maps to `event_type = 'payment reminder'`; 주문 생성 maps to `event_type = 'place order'`; 배송 실패 maps to `event_type = 'failed delivery'`; 배송 완료 maps to `event_type = 'package delivered'`.
- Counting: order counts use `COUNT(DISTINCT order_id)`.
- Population time: when the question asks for orders created/placed in a period, filter `event_type = 'place order'` and use `event_time`; do not count an order merely because another lifecycle event occurred in the period.

## analysis_item_events

- Business meaning: item-level events connected to items, orders, products, and customers.
- Korean keywords: 물품, 상품, 재고 부족, 피킹, 재주문, 포장, 상품명, 물품 수.
- Row grain: one item event linked to one item.
- Filters: 재고 부족 maps to `event_type = 'item out of stock'`; 피킹 maps to `event_type = 'pick item'`; 재주문 maps to `event_type = 'reorder item'`; 포장 생성 maps to `event_type = 'create package'`.
- Counting: item counts use `COUNT(DISTINCT item_id)` and product grouping uses `product_id`.
- Important: do not add an item-event filter when a follow-up only asks for items directly connected to a previously selected event set.

## analysis_order_customers

- Business meaning: direct order-to-customer mapping.
- Korean keywords: 고객별 주문, 주문 고객, 고객명, 고객 주문 수.
- Row grain: one order-customer relationship.
- Counting: orders per customer use `COUNT(DISTINCT order_id)` grouped by `customer_id`.

## analysis_daily_event_counts

- Business meaning: pre-aggregated daily event, order, and customer counts.
- Korean keywords: 일별 추이, 날짜별, 일간 통계, 일별 주문 수, 일별 고객 수.
- Row grain: one `event_type` per `event_date`.
- Use for daily trends when the requested dimensions are available directly.

## event_object

- Business meaning: exact links from an event to the objects participating in that event.
- Korean keywords: 이벤트에 직접 연결된 물품, 실패 이벤트 물품, 이벤트 상품, 이벤트-객체 관계.
- Join: `ocel_event_id` links to an event identifier; `ocel_object_id` is the linked object identifier.
- Qualifiers distinguish item, product, order, customer, package, and employee roles.
- Prefer this event-level mapping over a broader order-level join when the question asks what was directly part of an event.

## object_object

- Business meaning: links between business objects such as order-item, item-product, customer-order, and package-item.
- Korean keywords: 주문의 물품, 물품의 상품, 고객의 주문, 패키지의 물품, 객체 관계.
- Inspect `ocel_qualifier` and both endpoint object types before using a join.
- Determine the requested base population before subtracting later completion events. If the user says “those directly failed items,” retain that direct-event population; if the user asks for every item in failed orders, use the full `comprises` membership instead.
- Shared events may link several orders. When a selected order/customer scope is present, intersect event-linked items with the selected orders' `comprises` membership before grouping products.

## Raw OCEL fallback tables

- Tables: `event`, `event_*`, `object`, `object_*`, `event_object`, and `object_object`.
- Prefer suitable `analysis_*` tables first. Use raw OCEL tables when an analysis table lacks the exact event-object relationship or requested attribute.
