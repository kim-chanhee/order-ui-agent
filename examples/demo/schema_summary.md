# Synthetic demo schema

This dataset is fully fictional; no participant or original order records are used.

`orders` has one row per order. Count orders with COUNT(*) or COUNT(DISTINCT order_id).

| Column | Meaning |
|---|---|
| order_id | Unique order ID |
| customer_id | Fictional customer ID |
| product_name | Fictional product (Alpha, Beta, Gamma) |
| status | delivered (배송 완료), failed (배송 실패), pending (대기) |
| created_at | Order date in ISO YYYY-MM-DD format |
| amount | Order amount in KRW |

Latest date: 2026-10-20. Relative periods are anchored to MAX(created_at) over all orders before status filtering. status='failed' means delivery failed. No joins or migrations are needed. These tables differ from the research dataset.
