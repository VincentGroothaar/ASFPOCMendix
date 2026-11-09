# mock_pr: purchase requisition mock

A small, standalone mock of SAP's purchase requisition API, `API_PURCHASEREQ_PROCESS_SRV`
(OData V2). The SAP sandbox is read only, so story 5 ("create a purchase requisition") posts here
instead. Both PoC tracks use the same mock (decision D-21).

This mock is the only POST target in the app. Nothing writes to the SAP sandbox.

It behaves like SAP: the same paths, the `APIKey` header, the CSRF handshake, SAP-style error
bodies, and requisition numbers in SAP's format. A client switches between the mock and a real
S/4 system by changing only the base URL.

The mock is a FastAPI app. It does not use Django, and the Cockpit app does not import it; a
test checks both (`mock_pr/tests/test_independence.py`).

| File | What it does |
|---|---|
| `main.py` | The web app: routes, API key check, CSRF handshake, OData responses |
| `validation.py` | Checks a requisition against SAP's `$metadata` and the required-field list |
| `metadata.py` | Reads field types and lengths from the saved `$metadata` |
| `store.py` | Stores requisitions and hands out numbers in Postgres schema `mock_pr` |
| `csrf.py` | Makes and checks CSRF tokens |

## Run it locally

Postgres must be running (`docker compose up -d` from the repository root), and `.env` must hold
`DATABASE_URL` and `MOCK_API_KEY` (see `.env.example`). Then, from the repository root:

```bash
uv run --env-file .env uvicorn mock_pr.main:create_app_from_env --factory --port 8001
```

The service root is then `http://localhost:8001/sap/opu/odata/sap/API_PURCHASEREQ_PROCESS_SRV/`.
For the Cockpit, set `MOCK_PR_BASE_URL=http://localhost:8001` in `.env`.

Tests: `uv run pytest mock_pr` (they need the same Postgres; they use a separate schema,
`mock_pr_test`, and drop it afterwards).

## Environment variables

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Postgres URL. The mock creates its own schema `mock_pr` in this database on start-up (D-27). |
| `MOCK_API_KEY` | The key every client must send in the `APIKey` header. Use a long random string, e.g. `python -c "import secrets; print(secrets.token_urlsafe(32))"`. Never commit it. |

The mock refuses to start if either is missing.

## Endpoints

All paths start with `/sap/opu/odata/sap/API_PURCHASEREQ_PROCESS_SRV`, as on SAP.

| Method and path | What it does |
|---|---|
| `GET /` | Service document (list of entity sets) |
| `GET /$metadata` | SAP's real `$metadata`, saved from the sandbox in `docs/sandbox/metadata/` (#7) |
| `POST /A_PurchaseRequisitionHeader` | Create a requisition: one header with its items in `to_PurchaseReqnItem` (deep insert) |
| `GET /A_PurchaseRequisitionHeader('<number>')` | Read one requisition back, always with its items |

Every request needs the header `APIKey: <MOCK_API_KEY>`. Without it, or with a wrong key, the
mock answers `401`.

### CSRF handshake

As on SAP, a POST needs a CSRF token:

1. Send any GET with the header `X-CSRF-Token: Fetch`. The response has the token in the
   `X-CSRF-Token` header (and in a cookie).
2. Send the POST with the header `X-CSRF-Token: <token>`.

A POST without a valid token gets `403` with the header `X-CSRF-Token: Required`. The mock checks
only the header; unlike SAP, it does not require the cookie. Tokens do not expire and stay valid
after a restart.

### Responses

| Status | When |
|---|---|
| `201` | Requisition created. Body `{"d": {...}}` echoes the header and items with their numbers; the `Location` header points to the new requisition |
| `200` | Read back, service document, `$metadata` |
| `400` | Body is not JSON, or the requisition is invalid (see below) |
| `401` | `APIKey` missing or wrong |
| `403` | CSRF token missing or invalid |
| `404` | Unknown requisition number or path |

Every error has SAP's OData V2 error body:

```json
{"error": {"code": "INVALID_REQUISITION", "message": {"lang": "en", "value": "Property 'Material' is required (item 1)."}}}
```

**Numbers** follow SAP's format, as the sandbox returns them: requisition numbers are 8 digits
without leading zeros, starting at `10000000`; item numbers are `10`, `20`, `30`, … The numbers
come from a Postgres sequence, so they stay unique across restarts. A rejected request does not
use up a number.

## Validation

1. **Types and lengths.** Every field sent must exist in SAP's `$metadata` for the header
   (`A_PurchaseRequisitionHeaderType`) or the item (`A_PurchaseRequisitionItemType`), and must have
   the right type: text no longer than its maximum length, `true`/`false` for booleans, decimals
   as text (the OData V2 rule, e.g. `"12.5"`) with no more digits than the field allows, and dates
   as `"/Date(<milliseconds since 1970 UTC>)/"` or ISO (`"2026-11-20T00:00:00"`). The mock answers
   with dates in the `/Date(...)/` form, as SAP does. `__metadata` blocks are ignored.
2. **Required fields.** SAP's metadata marks almost nothing as required, but SAP rejects a
   requisition without these. Empty text counts as missing.

   | Where | Required fields |
   |---|---|
   | Header | `PurchaseRequisitionType` |
   | Each item | `Material`, `Plant`, `RequestedQuantity` (greater than 0), `BaseUnit`, `DeliveryDate`, `PurchasingGroup` |

   A requisition needs at least one item.
3. **Not supported:** deep inserts below the item (`to_PurchaseReqnAcctAssgmt`,
   `to_PurchaseReqnDeliveryAddress`, `to_PurchaseReqnItemText`) are rejected with `400`. The mock
   assigns `PurchaseRequisition` and `PurchaseRequisitionItem` itself and ignores values sent for
   them. It does not check that materials, plants or units exist in SAP.

## Header constants for the Cockpit

The Cockpit derives material, plant, quantity, unit and delivery date from the order (spec,
"Requisition payload"). It cannot derive the fields below, so it sends these fixed values. They
come from the SAP sandbox on 2026-11-09: the sandbox has no requisitions for plant AUC1, but among
the 2,000 requisition items it returned (plants 1710, 1010, US20, US30), these were the most
common values.

| Field | Where | Value | Sandbox evidence |
|---|---|---|---|
| `PurchaseRequisitionType` | Header | `NB` | `NB` (standard requisition) on 1,835 of 2,000 items; `NBS` 156, `RV` 9 |
| `PurchasingGroup` | Item | `001` | `001` on 1,540 of 2,000 items; `002` 327, `Z09` 58, `003` 57 |

Leave `PurchasingOrganization`, `CompanyCode`, `AccountAssignmentCategory` and
`PurchasingDocumentItemCategory` out: they were empty or `0` on most sandbox items and SAP fills
them in itself.

## Example

```bash
BASE=http://localhost:8001/sap/opu/odata/sap/API_PURCHASEREQ_PROCESS_SRV

# 1. Fetch a CSRF token
TOKEN=$(curl -s -D - -o /dev/null -H "APIKey: $MOCK_API_KEY" -H "X-CSRF-Token: Fetch" "$BASE/" \
  | awk -F': ' 'tolower($1)=="x-csrf-token" {print $2}' | tr -d '\r')

# 2. Create a requisition
curl -s -H "APIKey: $MOCK_API_KEY" -H "X-CSRF-Token: $TOKEN" -H "Content-Type: application/json" \
  "$BASE/A_PurchaseRequisitionHeader" -d '{
    "PurchaseRequisitionType": "NB",
    "to_PurchaseReqnItem": [{
      "Material": "MZ-RM-C990-01",
      "Plant": "AUC1",
      "RequestedQuantity": "5",
      "BaseUnit": "PC",
      "DeliveryDate": "2026-11-20T00:00:00",
      "PurchasingGroup": "001"
    }]
  }'
```

Response (`201 Created`, `__metadata` shortened):

```json
{"d": {
  "__metadata": {"id": "…/A_PurchaseRequisitionHeader('10000000')", "uri": "…", "type": "API_PURCHASEREQ_PROCESS_SRV.A_PurchaseRequisitionHeaderType"},
  "PurchaseRequisitionType": "NB",
  "PurchaseRequisition": "10000000",
  "to_PurchaseReqnItem": {"results": [{
    "__metadata": {"id": "…/A_PurchaseRequisitionItem(PurchaseRequisition='10000000',PurchaseRequisitionItem='10')", "uri": "…", "type": "API_PURCHASEREQ_PROCESS_SRV.A_PurchaseRequisitionItemType"},
    "Material": "MZ-RM-C990-01", "Plant": "AUC1", "RequestedQuantity": "5", "BaseUnit": "PC",
    "DeliveryDate": "/Date(1795132800000)/", "PurchasingGroup": "001",
    "PurchaseRequisition": "10000000", "PurchaseRequisitionItem": "10"
  }]}
}}
```

Read it back:

```bash
curl -s -H "APIKey: $MOCK_API_KEY" "$BASE/A_PurchaseRequisitionHeader('10000000')"
```

## Deploy on Render

Done by hand (#10 part 3), because it needs a Render account. Create the Postgres database first.

1. **New → Web Service**, repository `ASFPOCMendix`, branch `main`, region Frankfurt, Free plan,
   runtime Python. Render reads the Python version from `.python-version`.
2. **Build command:**
   ```bash
   pip install uv && uv sync --locked --no-dev
   ```
3. **Start command:**
   ```bash
   uv run --no-sync uvicorn mock_pr.main:create_app_from_env --factory --host 0.0.0.0 --port $PORT --forwarded-allow-ips '*'
   ```
   `--forwarded-allow-ips '*'` makes the links in responses use `https`, because Render's proxy
   handles HTTPS in front of the app.
4. **Environment variables:**
   - `DATABASE_URL`: the database's Internal Database URL
   - `MOCK_API_KEY`: a long random string (see above)
5. Deploy, then smoke-test the public URL with the example above: a POST after the CSRF fetch
   returns `201` with a number; a request without `APIKey` returns `401`.

Free services sleep after 15 minutes idle, so the first request after a pause takes about a
minute.
