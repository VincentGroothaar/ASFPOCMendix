"""Mock of SAP's purchase requisition API (`API_PURCHASEREQ_PROCESS_SRV`, OData V2).

The paths, the APIKey header, the CSRF handshake, the error bodies and the response bodies
follow SAP, so a client switches between this mock and a real S/4 system by changing only
the base URL. Start it with (see mock_pr/README.md):

    uv run --env-file .env uvicorn mock_pr.main:create_app_from_env --factory
"""

import json
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException

from mock_pr.csrf import is_valid_token, new_token, same_text
from mock_pr.metadata import (
    HEADER_TYPE,
    ITEM_TYPE,
    load_metadata_xml,
    parse_entity_sets,
    parse_entity_types,
)
from mock_pr.store import DEFAULT_SCHEMA, RequisitionStore
from mock_pr.validation import ITEMS_NAVIGATION, InvalidRequisition, validate_requisition

SERVICE = "API_PURCHASEREQ_PROCESS_SRV"
SERVICE_PATH = f"/sap/opu/odata/sap/{SERVICE}"
HEADER_SET = "A_PurchaseRequisitionHeader"
ITEM_SET = "A_PurchaseRequisitionItem"
CSRF_HEADER = "X-CSRF-Token"
CSRF_COOKIE = "sap-XSRF_mock"
ITEM_NUMBER_STEP = 10  # SAP numbers items 10, 20, 30, ...


def create_app_from_env() -> FastAPI:
    """Build the app from the environment variables DATABASE_URL and MOCK_API_KEY."""
    database_url = os.environ.get("DATABASE_URL", "").strip()
    api_key = os.environ.get("MOCK_API_KEY", "").strip()
    if not database_url or not api_key:
        raise RuntimeError("Set DATABASE_URL and MOCK_API_KEY before starting the mock.")
    return create_app(database_url, api_key)


def create_app(database_url: str, api_key: str, schema: str = DEFAULT_SCHEMA) -> FastAPI:
    """Build the mock app. Tests pass their own schema so they never touch `mock_pr`."""
    store = RequisitionStore(database_url, schema)
    metadata_xml = load_metadata_xml()
    entity_types = parse_entity_types(metadata_xml)
    header_type, item_type = entity_types[HEADER_TYPE], entity_types[ITEM_TYPE]

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store.create_tables()
        yield

    app = FastAPI(
        title="Purchase requisition mock", lifespan=lifespan, docs_url=None, redoc_url=None
    )

    @app.middleware("http")
    async def check_api_key_and_hand_out_csrf_token(request: Request, call_next):
        """Every request needs the API key. A GET can also fetch a CSRF token."""
        if not same_text(request.headers.get("APIKey", ""), api_key):
            return odata_error(401, "UNAUTHORIZED", "Missing or invalid APIKey header.")
        response = await call_next(request)
        if request.method == "GET" and request.headers.get(CSRF_HEADER, "").lower() == "fetch":
            token = new_token(api_key)
            response.headers[CSRF_HEADER] = token
            response.set_cookie(CSRF_COOKIE, token, httponly=True, secure=True, samesite="none")
        return response

    @app.exception_handler(HTTPException)
    async def http_error_as_odata(request: Request, error: HTTPException) -> JSONResponse:
        """Answer unknown paths and methods with an OData error body, as SAP does."""
        return odata_error(error.status_code, "HTTP_ERROR", str(error.detail))

    @app.get(f"{SERVICE_PATH}/")
    def service_document() -> JSONResponse:
        """The OData service document: the list of entity sets."""
        return JSONResponse({"d": {"EntitySets": parse_entity_sets(metadata_xml)}})

    @app.get(f"{SERVICE_PATH}/$metadata")
    def metadata() -> Response:
        """SAP's real $metadata, as saved from the sandbox."""
        return Response(metadata_xml, media_type="application/xml")

    @app.post(f"{SERVICE_PATH}/{HEADER_SET}")
    async def create_requisition(request: Request) -> JSONResponse:
        """Deep insert: one header with its items in `to_PurchaseReqnItem`."""
        if not is_valid_token(request.headers.get(CSRF_HEADER), api_key):
            return odata_error(
                403,
                "CSRF_TOKEN_REQUIRED",
                "CSRF token validation failed.",
                {CSRF_HEADER: "Required"},
            )
        try:
            body = json.loads(await request.body())
            requisition = validate_requisition(body, header_type, item_type)
        except (ValueError, RecursionError):
            # ValueError covers bad JSON, bytes that are not UTF-8 and over-long numbers;
            # RecursionError covers JSON nested too deeply.
            return odata_error(400, "INVALID_JSON", "The request body is not valid JSON.")
        except InvalidRequisition as error:
            return odata_error(400, "INVALID_REQUISITION", str(error))

        number = store.next_number()
        stored = build_stored_body(number, requisition.header, requisition.items)
        store.save(number, stored)
        base_url = service_url(request)
        return JSONResponse(
            {"d": with_metadata(stored, base_url)},
            status_code=201,
            headers={"Location": header_uri(base_url, number)},
        )

    @app.get(f"{SERVICE_PATH}/{HEADER_SET}('{{number}}')")
    def read_requisition(number: str, request: Request) -> JSONResponse:
        """Read one requisition back, always with its items."""
        stored = store.load(number)
        if stored is None:
            return odata_error(404, "NOT_FOUND", f"Purchase requisition {number} does not exist.")
        return JSONResponse({"d": with_metadata(stored, service_url(request))})

    return app


def build_stored_body(number: str, header: dict, items: list[dict]) -> dict:
    """Give the header and its items their numbers, in the shape SAP returns them."""
    numbered_items = []
    for position, item in enumerate(items, start=1):
        numbered_items.append(
            {
                **item,
                "PurchaseRequisition": number,
                "PurchaseRequisitionItem": str(position * ITEM_NUMBER_STEP),
            }
        )
    return {**header, "PurchaseRequisition": number, ITEMS_NAVIGATION: {"results": numbered_items}}


def with_metadata(stored: dict, base_url: str) -> dict:
    """Add the OData `__metadata` block (id, uri, type) to the header and every item."""
    number = stored["PurchaseRequisition"]
    header_link = header_uri(base_url, number)
    items = []
    for item in stored[ITEMS_NAVIGATION]["results"]:
        item_link = (
            f"{base_url}/{ITEM_SET}(PurchaseRequisition='{number}',"
            f"PurchaseRequisitionItem='{item['PurchaseRequisitionItem']}')"
        )
        items.append({"__metadata": _metadata_block(item_link, ITEM_TYPE), **item})
    return {
        "__metadata": _metadata_block(header_link, HEADER_TYPE),
        **stored,
        ITEMS_NAVIGATION: {"results": items},
    }


def _metadata_block(uri: str, entity_type: str) -> dict:
    """The `__metadata` block OData V2 puts on every entity."""
    return {"id": uri, "uri": uri, "type": f"{SERVICE}.{entity_type}"}


def service_url(request: Request) -> str:
    """The service root as the client called it, e.g. https://host/sap/opu/odata/sap/API_..."""
    return str(request.base_url).rstrip("/") + SERVICE_PATH


def header_uri(base_url: str, number: str) -> str:
    """The link to one requisition, e.g. .../A_PurchaseRequisitionHeader('10000000')."""
    return f"{base_url}/{HEADER_SET}('{number}')"


def odata_error(
    status_code: int, code: str, message: str, headers: dict | None = None
) -> JSONResponse:
    """An OData V2 error response in SAP's shape."""
    body = {"error": {"code": code, "message": {"lang": "en", "value": message}}}
    return JSONResponse(body, status_code=status_code, headers=headers)
