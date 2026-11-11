# sap

Client for the SAP OData V2 sandbox APIs (production orders, material stock, product).
In Mendix terms, this is the consumed OData service.

| File | What it does |
|---|---|
| `client.py` | `ODataClient`: GET with the `APIKey` header, `$filter`/`$expand`/`$select`/`$orderby`, paging with `$top`/`$skip` (and SAP's `__next` link, if it ever sends one), 10 s timeout. Every failure becomes `SapUnavailable`; unusable data becomes `SapDataError`, a kind of `SapUnavailable`. |
| `production_orders.py` | `read_released_orders(client, plant)`: released open orders with their components. |
| `stock.py` | `read_unrestricted_stock(client, plant, materials)`: unrestricted-use, non-special stock, summed over storage locations. |
| `products.py` | `read_descriptions(client, materials)`: English material descriptions. |

Each read function returns plain frozen dataclasses (or a dict) with `Decimal` quantities, so the
rest of the app never sees SAP's JSON. Field names and filters come from
[docs/sandbox/findings.md](../docs/sandbox/findings.md) as frozen in spec.md "SAP reads".

```python
from sap.client import ODataClient
from sap.production_orders import read_released_orders

client = ODataClient.from_settings()
orders = read_released_orders(client, "AUC1")
```

Rules:

- The base URL comes only from `settings.SAP_BASE_URL`.
- The API key comes only from `settings.SAP_API_KEY` (set via the environment).
- Read only. The client has no method that writes to SAP (INV-4).

Tests are in `sap/tests/`. They use a fake HTTP layer (`fake_http.py`), except
`test_sandbox_smoke.py`, which reads plant AUC1 from the live sandbox and is skipped when
`SAP_API_KEY` is not set (as in CI).
