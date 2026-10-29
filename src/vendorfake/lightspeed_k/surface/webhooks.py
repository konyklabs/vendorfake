"""The webhook endpoint CRUD under ``/o/wh/1/webhook`` (source.json ``apeWebhookEndpoint`` and its four operations).
These handlers touch only the core's ``SUBSCRIPTION_COLLECTION``; the wire document is the vendor-private ``document``."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr

from vendorfake.core.kernel.reply import json_
from vendorfake.core.kernel.types import HandlerArgs, ReplyInit, Route, UnitError, UnitErrorKind
from vendorfake.core.webhooks.models import SUBSCRIPTION_COLLECTION, require_postable_target
from vendorfake.lightspeed_k.events import endpoint_pattern
from vendorfake.lightspeed_k.paths import (
    APE_CREATE_WEBHOOK_OO,
    APE_DELETE_WEBHOOK_ENDPOINT,
    APE_GET_WEBHOOK_OO,
    APE_UPDATE_WEBHOOK_OO,
)
from vendorfake.lightspeed_k.seed.constants import SEED_EXAMPLE_ENDPOINT_ID
from vendorfake.lightspeed_k.surface.common import BEARER_AUTH, SCOPE_ORDERS, validate_body

__all__ = ["CAPABILITY", "LightspeedKWebhooksSurface", "WebhookEndpointRequest", "webhook_routes"]

CAPABILITY = "webhooks"
_DOCUMENT = "document"
_RESET = ("provideAccount", "expandTransactions", "expandPayments")
_BODY = ConfigDict(extra="ignore")


class EventResource(BaseModel):
    model_config = _BODY

    name: StrictStr | None = None
    resource: Literal["order", "payment", "item", "order_api"] | None = None


class WebhookEndpointRequest(BaseModel):
    model_config = _BODY

    endpointId: StrictStr = Field(min_length=1)  # JUDGMENT: the document sets no minLength; "" names no entity
    url: StrictStr
    withBasicAuth: StrictBool = False
    username: StrictStr | None = None
    password: StrictStr | None = None
    provideAccount: StrictBool = False
    expandTransactions: StrictBool = False
    expandPayments: StrictBool = False
    subscribeTo: list[EventResource] | None = None


def _not_found(endpoint_id: str) -> UnitError:
    # DOCUMENTED source.json: apeGetWebhookOo's 404 example message
    return UnitError(
        UnitErrorKind.NOT_FOUND,
        detail=f"endpoint ID not found for {endpoint_id}",
        field="endpointId",
        info={"reason": "unknown_endpoint"},
    )


def _project(entity: Mapping[str, Any]) -> dict[str, Any]:
    stored = entity.get(_DOCUMENT)
    if isinstance(stored, dict):
        return copy.deepcopy(stored)
    # JUDGMENT: a control-plane subscriber reads back with every documented default
    return {
        "endpointId": str(entity["id"]),
        "url": str(entity.get("notification_url", "")),
        "withBasicAuth": False,
        **dict.fromkeys(_RESET, False),
        "subscribeTo": [],
    }


def _document(request: WebhookEndpointRequest, previous: Mapping[str, Any]) -> dict[str, Any]:
    given = request.model_fields_set

    # DOCUMENTED source.json: the three flags reset when omitted; JUDGMENT: every other member is kept
    def kept(name: str, value: Any, default: Any) -> Any:
        return value if name in given else previous.get(name, default)

    subscribe = None if request.subscribeTo is None else [r.model_dump(exclude_none=True) for r in request.subscribeTo]
    document = {
        "endpointId": request.endpointId,
        "url": request.url,
        "withBasicAuth": kept("withBasicAuth", request.withBasicAuth, False),
        "username": kept("username", request.username, None),
        "password": kept("password", request.password, None),
        **{name: getattr(request, name) for name in _RESET},
        "subscribeTo": kept("subscribeTo", subscribe, []) or [],
    }
    document = {key: value for key, value in document.items() if value is not None}
    if document["withBasicAuth"]:
        for name in ("username", "password"):
            if not document.get(name):
                raise UnitError(
                    UnitErrorKind.MISSING_FIELD,
                    detail=f"{name} is required when withBasicAuth is true.",
                    field=name,
                )
    return document


def _signature_key(document: Mapping[str, Any]) -> str:
    return f"{document['username']}:{document['password']}" if document["withBasicAuth"] else ""


class LightspeedKWebhooksSurface:
    """The four endpoint routes; each declares ``orders-api``, which the kernel enforces."""

    __slots__ = ()

    def routes(self) -> tuple[Route, ...]:
        # No example_body: a subscription write is ignored by the journal listener, so nothing could be delivered.
        common: dict[str, Any] = {"capability": CAPABILITY, "auth": BEARER_AUTH, "scopes": (SCOPE_ORDERS,)}
        probe = {"endpointId": SEED_EXAMPLE_ENDPOINT_ID}
        return (
            Route(
                method="PUT",
                path=APE_CREATE_WEBHOOK_OO,
                handler=self.create,
                operation_id="apeCreateWebhookOo",
                summary="Register an order-notification endpoint by endpointId (case sensitive), optionally Basic.",
                **common,
            ),
            Route(
                method="POST",
                path=APE_UPDATE_WEBHOOK_OO,
                handler=self.update,
                operation_id="apeUpdateWebhookOo",
                summary="Update an endpoint; provideAccount, expandTransactions and expandPayments reset when omitted.",
                **common,
            ),
            Route(
                method="GET",
                path=APE_GET_WEBHOOK_OO,
                handler=self.read,
                operation_id="apeGetWebhookOo",
                summary="One endpoint as registered, password included.",
                example_params=probe,
                **common,
            ),
            Route(
                method="DELETE",
                path=APE_DELETE_WEBHOOK_ENDPOINT,
                handler=self.remove,
                operation_id="apeDeleteWebhookEndpoint",
                summary="Delete an endpoint; later orders naming it deliver to nobody.",
                example_params=probe,
                **common,
            ),
        )

    def create(self, args: HandlerArgs) -> ReplyInit:
        request = validate_body(WebhookEndpointRequest, args.body())
        require_postable_target(request.url, field="url")
        collection = args.ctx.store.collection(SUBSCRIPTION_COLLECTION)
        # JUDGMENT: an existing endpointId is refused; the document names no answer
        if collection.get(request.endpointId) is not None:
            raise UnitError(
                UnitErrorKind.INVALID_VALUE,
                detail=f"endpointId {request.endpointId} already exists; update it with POST {APE_UPDATE_WEBHOOK_OO}.",
                field="endpointId",
            )
        document = _document(request, {})
        collection.insert(
            {
                "id": request.endpointId,
                "name": request.endpointId,
                "notification_url": request.url,
                "event_types": [endpoint_pattern(request.endpointId)],
                "signature_key": _signature_key(document),
                "enabled": True,
                _DOCUMENT: document,
            },
            {"operation_id": "apeCreateWebhookOo"},
        )
        return json_(document)

    def update(self, args: HandlerArgs) -> ReplyInit:
        request = validate_body(WebhookEndpointRequest, args.body())
        require_postable_target(request.url, field="url")
        collection = args.ctx.store.collection(SUBSCRIPTION_COLLECTION)
        stored = collection.get(request.endpointId)
        if stored is None:
            raise _not_found(request.endpointId)
        document = _document(request, _project(stored))

        def mutate(entity: dict[str, Any]) -> None:
            entity["notification_url"] = request.url
            entity["signature_key"] = _signature_key(document)
            entity[_DOCUMENT] = document

        collection.update(request.endpointId, mutate, meta={"operation_id": "apeUpdateWebhookOo"})
        return json_(document)

    def read(self, args: HandlerArgs) -> ReplyInit:
        endpoint_id = args.params["endpointId"]
        stored = args.ctx.store.collection(SUBSCRIPTION_COLLECTION).get(endpoint_id)
        if stored is None:
            raise _not_found(endpoint_id)
        return json_(_project(stored))

    # DOCUMENTED source.json: 200 "Webhook deleted", no content
    def remove(self, args: HandlerArgs) -> ReplyInit:
        endpoint_id = args.params["endpointId"]
        if not args.ctx.store.collection(SUBSCRIPTION_COLLECTION).delete(
            endpoint_id, {"operation_id": "apeDeleteWebhookEndpoint"}
        ):
            raise _not_found(endpoint_id)
        return ReplyInit(status=200, text="")


def webhook_routes() -> tuple[Route, ...]:
    return LightspeedKWebhooksSurface().routes()
