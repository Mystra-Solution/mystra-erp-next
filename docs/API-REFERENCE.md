# ERPNext API Reference — Inventory, Purchase & GRN

This document describes how to call ERPNext REST APIs for:

- **Create inventory** — Item master, Stock Entry (opening stock / material receipt)
- **Get inventory and stocks** — Item list, Bin (stock per warehouse)
- **Purchase Order** — Create, list, get
- **Purchase Invoice** — Create, list, get
- **Request for Quotation** — Create, list, get
- **GRN (Goods Received Note)** — Purchase Receipt: create, list, get

All examples use **token authentication**. Replace:

- `BASE_URL` — e.g. `http://localhost:8080` (or your site URL)
- `API_KEY:API_SECRET` — from **User → Settings → API Access → Generate Keys**

Common headers for all requests:

```bash
-H "Authorization: token API_KEY:API_SECRET"
-H "Content-Type: application/json"
-H "Accept: application/json"
```

DocType names in ERPNext use **exact spelling and spaces** (e.g. `Purchase Order`, not `PurchaseOrder`). In URLs, spaces are encoded as `%20`.

---

## 1. Create inventory

### 1.1 Create Item (item master)

Items are the master data for products. Create an item first; then you can post stock (Stock Entry) and use it in Purchase Order / Purchase Receipt / Purchase Invoice.

**Endpoint:** `POST /api/resource/Item`

**Example (minimal):**

```bash
curl -X POST "$BASE_URL/api/resource/Item" \
  -H "Authorization: token API_KEY:API_SECRET" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d '{
    "item_code": "ITEM-001",
    "item_name": "Sample Product",
    "item_group": "Products",
    "stock_uom": "Nos",
    "valuation_rate": 100
  }'
```

**Common fields:** `item_code`, `item_name`, `item_group`, `stock_uom`, `valuation_rate`, `description`, `is_stock_item` (1/0).

---

### 1.2 Create opening stock / material receipt (Stock Entry)

Use **Stock Entry** with purpose **Material Receipt** to add quantity to a warehouse (e.g. opening stock or goods received).

**Endpoint:** `POST /api/resource/Stock%20Entry`

**Example (Material Receipt with one item):**

```bash
curl -X POST "$BASE_URL/api/resource/Stock%20Entry" \
  -H "Authorization: token API_KEY:API_SECRET" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d '{
    "purpose": "Material Receipt",
    "company": "Your Company Ltd",
    "to_warehouse": "Stores - X",
    "items": [
      {
        "item_code": "ITEM-001",
        "qty": 100,
        "basic_rate": 100,
        "valuation_rate": 100
      }
    ]
  }'
```

Submit the document after creation (see **Submit document** below) so stock and ledger are updated.

**Common fields:** `purpose` (e.g. `Material Receipt`, `Material Issue`, `Material Transfer`), `company`, `from_warehouse` / `to_warehouse`, `items` (array of `item_code`, `qty`, `basic_rate`, `valuation_rate`). Replace warehouse names with your actual warehouses.

---

## 2. Get inventory and stocks

### 2.1 List Items

**Endpoint:** `GET /api/resource/Item`

**Example (list with fields, pagination):**

```bash
curl -s -H "Authorization: token API_KEY:API_SECRET" \
  -H "Accept: application/json" \
  "$BASE_URL/api/resource/Item?fields=[\"name\",\"item_name\",\"item_group\",\"stock_uom\"]&limit_page_length=20"
```

**With filters (e.g. by item group):**

```bash
curl -s -H "Authorization: token API_KEY:API_SECRET" \
  -H "Accept: application/json" \
  "$BASE_URL/api/resource/Item?fields=[\"name\",\"item_name\",\"item_group\"]&filters=[[\"item_group\",\"=\",\"Products\"]]&limit_page_length=20"
```

**Get a single item:**

```bash
curl -s -H "Authorization: token API_KEY:API_SECRET" \
  -H "Accept: application/json" \
  "$BASE_URL/api/resource/Item/ITEM-001"
```

---

### 2.2 Get stock quantity per warehouse (Bin)

**Bin** holds current quantity per item per warehouse. Use it to get “inventory and stocks”.

**Endpoint:** `GET /api/resource/Bin`

**Example (stock for one item):**

```bash
curl -s -H "Authorization: token API_KEY:API_SECRET" \
  -H "Accept: application/json" \
  "$BASE_URL/api/resource/Bin?fields=[\"item_code\",\"warehouse\",\"actual_qty\",\"reserved_qty\",\"projected_qty\"]&filters=[[\"item_code\",\"=\",\"ITEM-001\"]]&limit_page_length=100"
```

**Example (stock in one warehouse):**

```bash
curl -s -H "Authorization: token API_KEY:API_SECRET" \
  -H "Accept: application/json" \
  "$BASE_URL/api/resource/Bin?fields=[\"item_code\",\"warehouse\",\"actual_qty\",\"valuation_rate\"]&filters=[[\"warehouse\",\"=\",\"Stores - X\"]]&limit_page_length=100"
```

**Query params:** `fields` (JSON array), `filters` (JSON array of `[field, operator, value]`), `limit_page_length`, `limit_start`.

---

## 3. Purchase Order

**DocType:** `Purchase Order`

### 3.1 Create Purchase Order

**Endpoint:** `POST /api/resource/Purchase%20Order`

**Example (minimal: one item, one supplier):**

```bash
curl -X POST "$BASE_URL/api/resource/Purchase%20Order" \
  -H "Authorization: token API_KEY:API_SECRET" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d '{
    "supplier": "Supplier Name",
    "company": "Your Company Ltd",
    "schedule_date": "2025-02-15",
    "items": [
      {
        "item_code": "ITEM-001",
        "qty": 10,
        "rate": 100,
        "warehouse": "Stores - X"
      }
    ]
  }'
```

Replace `supplier`, `company`, `warehouse` with your master data. Then **submit** the document.

### 3.2 List Purchase Orders

```bash
curl -s -H "Authorization: token API_KEY:API_SECRET" \
  -H "Accept: application/json" \
  "$BASE_URL/api/resource/Purchase%20Order?fields=[\"name\",\"supplier\",\"status\",\"grand_total\",\"transaction_date\"]&limit_page_length=20"
```

**With filters (e.g. by supplier):**

```bash
curl -s -H "Authorization: token API_KEY:API_SECRET" \
  -H "Accept: application/json" \
  "$BASE_URL/api/resource/Purchase%20Order?filters=[[\"supplier\",\"=\",\"Supplier Name\"]]&limit_page_length=20"
```

### 3.3 Get one Purchase Order

```bash
curl -s -H "Authorization: token API_KEY:API_SECRET" \
  -H "Accept: application/json" \
  "$BASE_URL/api/resource/Purchase%20Order/PO-00001"
```

---

## 4. Purchase Invoice

**DocType:** `Purchase Invoice`

### 4.1 Create Purchase Invoice

**Endpoint:** `POST /api/resource/Purchase%20Invoice`

**Example (minimal):**

```bash
curl -X POST "$BASE_URL/api/resource/Purchase%20Invoice" \
  -H "Authorization: token API_KEY:API_SECRET" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d '{
    "supplier": "Supplier Name",
    "company": "Your Company Ltd",
    "posting_date": "2025-02-15",
    "items": [
      {
        "item_code": "ITEM-001",
        "qty": 10,
        "rate": 100,
        "expense_account": "Cost of Goods Sold - X",
        "warehouse": "Stores - X"
      }
    ]
  }'
```

You can link to a Purchase Receipt with `update_stock=1` and `items[].purchase_receipt` / `items[].pr_detail` if the invoice is against a GRN.

### 4.2 List Purchase Invoices

```bash
curl -s -H "Authorization: token API_KEY:API_SECRET" \
  -H "Accept: application/json" \
  "$BASE_URL/api/resource/Purchase%20Invoice?fields=[\"name\",\"supplier\",\"status\",\"grand_total\",\"posting_date\"]&limit_page_length=20"
```

### 4.3 Get one Purchase Invoice

```bash
curl -s -H "Authorization: token API_KEY:API_SECRET" \
  -H "Accept: application/json" \
  "$BASE_URL/api/resource/Purchase%20Invoice/PINV-00001"
```

---

## 5. Request for Quotation

**DocType:** `Request for Quotation`

### 5.1 Create Request for Quotation

**Endpoint:** `POST /api/resource/Request%20for%20Quotation`

**Example (minimal):**

```bash
curl -X POST "$BASE_URL/api/resource/Request%20for%20Quotation" \
  -H "Authorization: token API_KEY:API_SECRET" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d '{
    "company": "Your Company Ltd",
    "transaction_date": "2025-02-15",
    "schedule_date": "2025-02-20",
    "items": [
      {
        "item_code": "ITEM-001",
        "qty": 10,
        "warehouse": "Stores - X"
      }
    ]
  }'
```

You add **suppliers** (and optionally email) via child table; check the DocType for `suppliers` / `Request for Quotation Supplier` in the UI or API response.

### 5.2 List Request for Quotation

```bash
curl -s -H "Authorization: token API_KEY:API_SECRET" \
  -H "Accept: application/json" \
  "$BASE_URL/api/resource/Request%20for%20Quotation?fields=[\"name\",\"status\",\"transaction_date\",\"schedule_date\"]&limit_page_length=20"
```

### 5.3 Get one Request for Quotation

```bash
curl -s -H "Authorization: token API_KEY:API_SECRET" \
  -H "Accept: application/json" \
  "$BASE_URL/api/resource/Request%20for%20Quotation/RFQ-00001"
```

---

## 6. GRN (Goods Received Note) — Purchase Receipt

In ERPNext, **GRN** is represented by the **Purchase Receipt** DocType.

**DocType:** `Purchase Receipt`

### 6.1 Create Purchase Receipt (GRN)

**Endpoint:** `POST /api/resource/Purchase%20Receipt`

**Example (minimal; optionally link to Purchase Order):**

```bash
curl -X POST "$BASE_URL/api/resource/Purchase%20Receipt" \
  -H "Authorization: token API_KEY:API_SECRET" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d '{
    "supplier": "Supplier Name",
    "company": "Your Company Ltd",
    "posting_date": "2025-02-15",
    "set_warehouse": "Stores - X",
    "items": [
      {
        "item_code": "ITEM-001",
        "qty": 10,
        "rate": 100,
        "warehouse": "Stores - X"
      }
    ]
  }'
```

To create GRN from a Purchase Order, set `purchase_order` and in `items` set `purchase_order`, `purchase_order_item`, and optionally `against_purchase_order_item` so quantities and rates can be pulled from the PO.

### 6.2 List Purchase Receipts (GRNs)

```bash
curl -s -H "Authorization: token API_KEY:API_SECRET" \
  -H "Accept: application/json" \
  "$BASE_URL/api/resource/Purchase%20Receipt?fields=[\"name\",\"supplier\",\"status\",\"posting_date\",\"set_warehouse\"]&limit_page_length=20"
```

### 6.3 Get one Purchase Receipt (GRN)

```bash
curl -s -H "Authorization: token API_KEY:API_SECRET" \
  -H "Accept: application/json" \
  "$BASE_URL/api/resource/Purchase%20Receipt/PR-00001"
```

---

## Submit document

Most transactional DocTypes (Stock Entry, Purchase Order, Purchase Invoice, Purchase Receipt, etc.) must be **submitted** so that:

- Stock and ledger are updated
- Status becomes **Submitted**
- Document is locked for direct editing

**Endpoint:** `POST /api/method/frappe.client.submit`

**Body:**

```json
{
  "doc": {
    "doctype": "Stock Entry",
    "name": "STE-00001"
  }
}
```

**Example:**

```bash
curl -X POST "$BASE_URL/api/method/frappe.client.submit" \
  -H "Authorization: token API_KEY:API_SECRET" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d '{"doc": {"doctype": "Stock Entry", "name": "STE-00001"}}'
```

Use the same pattern for other DocTypes (e.g. `"doctype": "Purchase Order", "name": "PO-00001"`).

---

## URL encoding

Spaces in DocType names must be encoded in URLs:

| DocType               | Path segment in URL        |
|-----------------------|----------------------------|
| Stock Entry           | `Stock%20Entry`            |
| Purchase Order        | `Purchase%20Order`         |
| Purchase Invoice      | `Purchase%20Invoice`       |
| Request for Quotation | `Request%20for%20Quotation`|
| Purchase Receipt      | `Purchase%20Receipt`       |

In `curl` you can use `%20` or quote the URL.

---

## List query parameters (GET /api/resource/:doctype)

| Parameter           | Description                                      |
|--------------------|---------------------------------------------------|
| `fields`           | JSON array of field names, e.g. `["name","status"]` |
| `filters`          | JSON array of `[field, operator, value]`, e.g. `[["status","=","Submitted"]]` |
| `limit_page_length`| Page size (default 20)                           |
| `limit_start`      | Offset for paging                               |
| `order_by`         | Sort, e.g. `modified%20desc`                     |

**Operators:** `=`, `!=`, `>`, `<`, `>=`, `<=`, `like`, `in`, `not in`, etc.

---

## References

- [Frappe REST API](https://docs.frappe.io/framework/user/en/api/rest)
- [Frappe token authentication](https://docs.frappe.io/framework/user/en/guides/integration/rest_api/token_based_authentication)
- [SETUP.md](../SETUP.md) — run ERPNext with Docker and get API base URL + token
