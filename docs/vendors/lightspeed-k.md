# Lightspeed Restaurant K-Series (V1 authentication)

The fifth vendor, identifier `lightspeed-k`, and the first whose identifier
differs from its module (`vendorfake.lightspeed_k`). D-016's three slices:
the V1 token lifecycle, three Order and Pay reads, the to-go order, the webhook
endpoint CRUD and the order notifications delivered to it, and the tax
breakdown of a proposed order. Lightspeed's other
Restaurant series are not modelled.

!!! warning "Unofficial"
    Built from Lightspeed's public documentation only, without sandbox or
    partner access; konyklabs is not affiliated with, endorsed by, or connected
    to Lightspeed. The same statement is published at `GET /__unit/info` under
    `auth.statement`. Every behaviour that is *not* documented is labelled
    JUDGMENT here and at its site in the code.

## What is modelled

Eleven routes and one delivery on one merchant account:

| Route | Operation | Fidelity |
|---|---|---|
| `GET /oauth/authorize` | stand-in for the consent screen | EXCUSED: prose only |
| `POST /oauth/token` | the V1 token endpoint, both grants | EXCUSED: prose only |
| `GET /o/op/data/businesses` | `apeLookupBusinesses` | validated against `source.json` |
| `GET /o/op/1/menu/list` | `apeLoadMenus` | validated against `source.json` |
| `GET /o/op/2/menu/load/{menuId}` | `apeGetMenuByIdV2` | validated against `source.json` |
| `POST /o/op/1/order/toGo` | `apePlaceToGoOrder` | validated against `source.json` |
| `PUT /o/wh/1/webhook` | `apeCreateWebhookOo` | validated against `source.json` |
| `POST /o/wh/1/webhook` | `apeUpdateWebhookOo` | validated against `source.json` |
| `GET /o/wh/1/webhook/{endpointId}` | `apeGetWebhookOo` | validated against `source.json` |
| `DELETE /o/wh/1/webhook/{endpointId}` | `apeDeleteWebhookEndpoint` | validated against `source.json` |
| `POST /tp/v1/business-locations/{businessLocationId}/tax-breakdown` | `tax-preview-apiTaxBreakdown` | validated against `source.json` |
| delivery: `POST <your url>` | `webhooks["apeOrder notification"]` | asserted in a unit test; the fidelity cut carries no `webhooks` entries yet |

## Consumer calls

The six calls an online-ordering consumer makes, and which are modelled:

| # | Call | Modelled |
|---|---|---|
| 1 | the V1 token (`POST /oauth/token`) | yes |
| 2 | the businesses (`GET /o/op/data/businesses`) | yes |
| 3 | the menu (`GET /o/op/1/menu/list`, `GET /o/op/2/menu/load/{menuId}`) | yes |
| 4 | the to-go order (`POST /o/op/1/order/toGo`) | yes |
| 5 | the webhook registration (`PUT /o/wh/1/webhook`) | yes |
| 6 | the tax breakdown (`POST /tp/v1/business-locations/{businessLocationId}/tax-breakdown`) | yes |

V1 authentication is the documented legacy path: "As of November 10, 2025 all
newly created API clients are V2 by default. Existing V1 clients will continue
to work until applications have been migrated to V2"
([manual migration steps](https://api-portal.lsk.lightspeed.app/quick-start/authentication/migration-guides/Manual%20Migration/manual-migration-steps),
fetched 2026-10-29); no sunset date is published. A
client id beginning `devp-v2` is a V2 client, and this unit refuses it with
reason `v2_client_id`.

The specification is **not vendored** (`vendored: false`, as Toast's): the
repository carries `declaration.json`, `pin.json` (sha256, size, version and
fetch date of `source.json`) and the corpus. The extract is cut at run time
into `~/.cache/vendorfake/fidelity/vendorfake.lightspeed_k.fidelity/`, so the
first fidelity run on a cold cache needs the network:

```sh
python -m vendorfake.fidelity fetch  --target vendorfake.testing.fidelity:lightspeed_k_target
python -m vendorfake.fidelity report --target vendorfake.testing.fidelity:lightspeed_k_target
```

## First journey

Produced by running these commands against `vendorfake serve --vendor
lightspeed-k --port 8125` on the `full` profile; `$BASIC` is
`Basic dW5pdC1saWdodHNwZWVkLWstY2xpZW50LWlkOnVuaXQtbGlnaHRzcGVlZC1rLWNsaWVudC1zZWNyZXQ=`,
the seeded client's `client_id:client_secret`. Minted tokens differ per unit.

```console
$ curl -s -o /dev/null -w "%{http_code} %{redirect_url}\n" "http://127.0.0.1:8125/oauth/authorize?response_type=code&client_id=unit-lightspeed-k-client-id&redirect_uri=https://consumer.example/callback&scope=financial-api+orders-api&state=xyz"
302 https://consumer.example/callback?code=E59Xgh&state=xyz
$ curl -s -X POST "http://127.0.0.1:8125/oauth/token?grant_type=authorization_code&code=E59Xgh&redirect_uri=https://consumer.example/callback" -H "Authorization: $BASIC"
{"access_token":"f63a07c3-af11-47bd-8a66-59cc03089838","token_type":"bearer","refresh_token":"78cad0aa-5db1-4697-a2ec-22bdac8eda32","expires_in":3599,"scope":"financial-api orders-api "}
$ curl -s http://127.0.0.1:8125/o/op/data/businesses -H 'Authorization: bearer unit-lightspeed-k-access-token-full'
[{"id":100000000001,"name":"Unit K Bistro","businessLocations":[{"id":100000000101,"name":"Unit K Bistro - Main Street"}]}]
$ curl -s 'http://127.0.0.1:8125/o/op/1/menu/list?businessLocationId=100000000101' -H 'Authorization: bearer unit-lightspeed-k-access-token-full'
[{"menuName":"Unit Lunch Menu","ikentooMenuId":100000000201}]
$ curl -s 'http://127.0.0.1:8125/o/op/2/menu/load/100000000201?businessLocationId=100000000101' -H 'Authorization: bearer unit-lightspeed-k-access-token-full'
{"menuName":"Unit Lunch Menu","ikentooMenuId":100000000201,"menuEntryGroups":[{"@type":"group","id":"100000000301","name":"Mains","color":"blue","menuEntry":[{"@type":"menuItem","productName":"Unit Burger","productPrice":12.5,"sku":"UNITK-001","taxes":[{"description":"10% VAT","amount":1.25,"percentage":10.0}],"defaultTaxAmount":1.25,"defaultTaxPercentage":10.0,"taxIncludedInPrice":false,"menuModifierGroups":[]},{"@type":"menuItem","productName":"Unit Lemonade","productPrice":4.0,"sku":"UNITK-002","taxes":[{"description":"10% VAT","amount":0.36,"percentage":10.0}],"defaultTaxAmount":0.36,"defaultTaxPercentage":10.0,"taxIncludedInPrice":true,"menuModifierGroups":[]}]}],"richDataMissing":false,"conditionalTaxRules":false}
$ curl -s -X POST http://127.0.0.1:8125/oauth/token -H "Authorization: $BASIC" -d grant_type=refresh_token -d refresh_token=unit-lightspeed-k-refresh-token-full
{"access_token":"ba3b68ac-d77f-45e2-9fa3-b04ec4b4cdba","token_type":"bearer","refresh_token":"2ecfe92a-4ad1-4d11-ad28-a903e44f15f8","expires_in":3599,"scope":"financial-api orders-api "}
$ curl -s -X POST http://127.0.0.1:8125/oauth/token -H "Authorization: $BASIC" -d grant_type=refresh_token -d refresh_token=unit-lightspeed-k-refresh-token-full
{"error":"invalid_grant","error_description":"The refresh token was already used; refresh tokens can only be used once."}
$ curl -s 'http://127.0.0.1:8125/o/op/1/menu/list?businessLocationId=100000000101'
{"status":401,"error":"Unauthorized","message":"An Authorization: bearer header is required."}
```

## Order notifications

An order names its endpoint (`endpointId`, case sensitive), and every change of
the order's status is delivered there, from the journal: the handler stores the
order and answers `{"status": "ok"}`, and the notification follows. An endpoint
registered with `withBasicAuth: true` receives `Authorization: Basic
base64(username:password)` on every delivery; one registered without it
receives no `Authorization` header. A SKU on no menu at the location is a POS
refusal: the order is stored as `FAILURE` and its notification says why.

Produced against `vendorfake serve --vendor lightspeed-k --port 8125` on `full`,
with a loopback receiver on port 8126; `$T` is `Authorization: bearer
unit-lightspeed-k-access-token-full`. The order id and account identifier differ
per unit.

```console
$ curl -s -X PUT http://127.0.0.1:8125/o/wh/1/webhook -H "$T" -H "content-type: application/json" -d '{"endpointId":"MY-ENDPOINT","url":"http://127.0.0.1:8126/hooks","withBasicAuth":true,"username":"unit-k-user","password":"unit-k-password"}'
{"endpointId":"MY-ENDPOINT","url":"http://127.0.0.1:8126/hooks","withBasicAuth":true,"username":"unit-k-user","password":"unit-k-password","provideAccount":false,"expandTransactions":false,"expandPayments":false,"subscribeTo":[]}
$ curl -s -X POST http://127.0.0.1:8125/o/op/1/order/toGo -H "$T" -H "content-type: application/json" -d '{"businessLocationId":100000000101,"thirdPartyReference":"unit-k-order-1","endpointId":"MY-ENDPOINT","customerInfo":{"firstName":"Jane"},"items":[{"quantity":2,"sku":"UNITK-001"}],"takeAway":true}'
{"status":"ok"}
$ curl -s -X POST http://127.0.0.1:8125/o/op/1/order/toGo -H "$T" -H "content-type: application/json" -d '(the same body)'
{"status":"fail","msg":"reference has already been used unit-k-order-1"}
```

The receiver got, with `Authorization: Basic dW5pdC1rLXVzZXI6dW5pdC1rLXBhc3N3b3Jk`:

```json
{"thirdPartyReference":"unit-k-order-1","businessLocationId":100000000101,"status":"SUCCESS","ikentooAccountIdentifier":"A55515.2","type":"ORDER"}
```

A `FAILURE` notification is `{"status": "FAILURE", "reason": ..., "thirdPartyReference": ...}`.
Neither shape carries an event id, as against the real vendor: deduplicate on
`thirdPartyReference` plus `status`.

**The POS stand-in.** Nothing in the unit moves an order past `SUCCESS`; the
POS operator does, through the control plane's journalled write. Each change to
a documented status is delivered; any other value is logged and delivers
nothing:

```console
$ curl -s -X POST http://127.0.0.1:8125/__unit/state/update -H "content-type: application/json" -d '{"collection":"orders","id":"1ef588f6-3a07-4c3a-8f11-7bda6659cc03","patch":{"status":"READY_FOR_PICKUP"}}'
{"collection":"orders","id":"1ef588f6-3a07-4c3a-8f11-7bda6659cc03","version":2,"journal_seq":8}
```

The order id comes from `POST /__unit/state/page {"collection": "orders"}`. The
receiver then got the same body with `"status":"READY_FOR_PICKUP"`.

**Retry schedule (JUDGMENT).** K-Series documents none. A delivery not answered
2xx within 10 s is retried after 60 s, 5 min, 15 min and 1 h, four retries in
all, compressed by `time_scale = 1/6000` (the first retry 10 ms after the
failure) unless a profile says otherwise.

!!! warning "The Basic credential is visible"
    The password is echoed by `PUT`, `POST` and `GET`, and the header appears
    at `GET /__unit/webhooks/deliveries`, in the manifest's
    `webhooks.signature_keys` and in the subscriber list at
    `GET /__unit/webhooks/subscriptions`. Never register a real credential.

## Tax breakdown

`POST /tp/v1/business-locations/{businessLocationId}/tax-breakdown` prices a
proposed order from the seeded menu and stores nothing. On the default seed
`UNITK-001` is tax-exclusive and `UNITK-002` tax-inclusive, both at 10 %:

```console
$ curl -s -X POST http://127.0.0.1:8125/tp/v1/business-locations/100000000101/tax-breakdown -H 'Authorization: bearer unit-lightspeed-k-access-token-full' -H 'content-type: application/json' -d '{"items":[{"sku":"UNITK-001","quantity":2},{"sku":"UNITK-002"}]}'
{"transactions":[{"sku":"UNITK-001","quantity":2.0,"unitPrice":12.5,"netAmount":25.0,"grossAmount":27.5,"taxAmount":2.5},{"sku":"UNITK-002","quantity":1.0,"unitPrice":4.0,"netAmount":3.64,"grossAmount":4.0,"taxAmount":0.36}],"taxLines":[{"description":"10% VAT","taxRate":"1.10","netAmount":25.0,"grossAmount":27.5,"taxAmount":2.5,"taxIncluded":false},{"description":"10% VAT","taxRate":"1.10","netAmount":3.64,"grossAmount":4.0,"taxAmount":0.36,"taxIncluded":true}],"totalNetAmountInCents":2864,"totalGrossAmountInCents":3150,"totalTaxAmountInCents":286,"amountDue":31.5}
$ curl -s -X POST http://127.0.0.1:8125/tp/v1/business-locations/100000000101/tax-breakdown -H 'Authorization: bearer unit-lightspeed-k-access-token-full' -H 'content-type: application/json' -d '{"items":[{"sku":"UNITK-404"}]}'
{"status":"400","message":"Unknown SKU UNITK-404 at business location 100000000101","apiSubExceptions":[{"field":"items.0.sku","rejectedValue":"UNITK-404","message":"Unknown SKU UNITK-404 at business location 100000000101"}]}
$ curl -s -X POST http://127.0.0.1:8125/tp/v1/business-locations/100000000101/tax-breakdown -H 'Authorization: bearer unit-lightspeed-k-access-token-financial' -H 'content-type: application/json' -d '{"items":[]}'
{"status":403,"error":"Forbidden","message":"The access token is missing the required permission(s): orders-api."}
```

!!! warning "Integer cents beside decimal numbers"
    One body carries both: `totalNetAmountInCents`, `totalGrossAmountInCents`
    and `totalTaxAmountInCents` are int64 **cents** (`3150`), while every
    `*Amount`, `unitPrice` and `amountDue` is a decimal number of currency
    units (`31.5`). Read each field in its own unit.

`taxRate` is a string: `"1.20"` means 20 % (the document's own example), so
10 % is `"1.10"`, 8.875 % is `"1.08875"` and 0 % is `"1.00"`: at least two
decimals, more only when the configured percentage has them.

The arithmetic, all JUDGMENT:

1. Every input is read as a `Decimal` of its decimal text; floats are never
   multiplied.
2. A line's amount is `productPrice × quantity` in cents, rounded half-up once.
3. Tax-exclusive (`taxIncludedInPrice: false`): net is the amount, each tax
   part is `net × rate` rounded half-up, gross is net plus the parts.
4. Tax-inclusive (`true`): gross is the amount, each part is
   `gross / (1 + R) × rate` rounded half-up (`R` the sum of the item's rates),
   net is gross minus the parts, so `net + tax = gross` always holds.
5. An item with no `taxes[]` has no tax and no tax line, and still counts.
6. A transaction line echoes `sku`, the quantity and `productPrice`, with its
   net, gross and tax in currency units.
7. One tax line per distinct `(description, percentage, taxIncluded)`, first
   seen first: the nets of the lines carrying it, that tax's parts, and their
   sum as gross. `taxCode` and `taxName` are omitted.
8. The three totals are the integer sums of the per-line cents and
   `amountDue` is the gross total in currency units, so transactions, tax
   lines and totals agree to the cent; rounding is per line, never per order.
9. A line or total outside an int64 of cents is 400 `invalid_value` on
   `items` (a quantity of `1e300` is a valid double).

Two envelopes answer refusals here. The route's own 400 and 404, and the 503
of an armed `unavailable` fault, answer the declared `*/*` body with a
**string** status, `{"status": "400", "message", "apiSubExceptions"}`, with one
sub-exception naming the field (and `rejectedValue` for an unknown SKU). The
kernel's 403 for a token without `orders-api` is refused before any vendor code
runs and keeps the **integer**-status body every other route answers; the
document types it as the string `"403"`, and two declared deviations
(`type` and `enum` on `/status`, this route only) record the disagreement. A
401 is unchanged.

## Documented

All pages fetched 2026-10-29.

| Fact | Page |
|---|---|
| The authorize URL carries `response_type=code`, `client_id`, `scope` (space-delimited) and `redirect_uri`, `state` optional; the redirect carries `code` and `state` | [V1 authorization overview](https://api-portal.lsk.lightspeed.app/quick-start/authentication/v1-authentication/v1-authorization-overview) |
| Client authentication is `client_id:client_secret`, base64-encoded, in the `Authorization: Basic` header | V1 authorization overview |
| The code exchange's `grant_type`, `code` and `redirect_uri` "must be passed as query parameters"; the refresh's values "in the request body as an x-www-form-encoded payload" | V1 authorization overview |
| Both token responses: `access_token`, `token_type: bearer`, `refresh_token`, `expires_in: 3599`, `scope: "financial-api orders-api "` (trailing space in both samples); both tokens UUID-shaped; codes six mixed alphanumerics | V1 authorization overview |
| Access tokens expire after 60 minutes; refresh tokens after 14 days and can be used once; redirect URLs require HTTPS | [V1 authorization FAQ](https://api-portal.lsk.lightspeed.app/quick-start/authentication/v1-authentication/v1-authorization-faq) |
| A client id beginning `devp-v2` is a V2 client | banner on every V1 page |
| An invalid or expired token gets "a 4xx error" | [V1 managing access tokens](https://api-portal.lsk.lightspeed.app/quick-start/authentication/v1-authentication/v1-managing-access-tokens) |
| `orders-api` reads business information and menus; the three reads declare it | [`source.json`](https://api-docs.lsk.lightspeed.app/source.json), [access scopes](https://api-portal.lsk.lightspeed.app/quick-start/authentication/access-scopes) |
| The three response shapes, `businessLocationId` int64 and required, `richContent`/`accountProfile` optional; the 503 body under `*/*` with `status` the string `"503"` | `source.json` |
| An account can have several business locations, referenced by `businessLocationId` | [business locations](https://api-portal.lsk.lightspeed.app/guides/definitions/business-locations) |
| List the menus, copy the `ikentooMenuId`, load the menu | [online-ordering tutorial](https://api-portal.lsk.lightspeed.app/guides/tutorials/online-ordering-basics) |
| `GET /o/op/1/menu/load/{menuId}` deprecated and V2 added on 2026-05-15 | [changes](https://api-docs.lsk.lightspeed.app/changes) |
| The to-go validations: `businessLocationId`, `thirdPartyReference` (1..48, unique), `endpointId` and `customerInfo.firstName` (1..128) required; `items[].quantity` and `items[].sku` (≤25); `payment.paymentAmount`; `collectionCode` ≤8; `maxTimeToAttemptOrderDeliverToPos` ≥60000 ("The minimum value is 60000ms"); the two times `format: date-time` (RFC 3339 §5.6, `Z` or a numeric offset, `t`/`z` in either case) and "must be in the future" | `source.json` |
| A 200 "doesn't necessarily mean that it has been sent to the POS. This must be confirmed via the webhook" | tutorial |
| The tutorial's to-go body carries `takeAway: true`, which the schema does not name; with no `additionalProperties: false` it is accepted and ignored | tutorial, `source.json` |
| A reused `thirdPartyReference` is 409 `{"status": "fail", "msg": "reference has already been used <ref>"}` under `*/*` | `source.json` |
| `endpointId` is case sensitive; `url` required; `withBasicAuth`, `provideAccount`, `expandTransactions`, `expandPayments` default false; `subscribeTo[].resource` is `order`, `payment`, `item` or `order_api` | `source.json` |
| An update omitting `provideAccount`, `expandTransactions` or `expandPayments` resets them to their defaults | `source.json` |
| An unknown endpoint is 404 `endpoint ID not found for <id>`; a delete answers 200 "Webhook deleted" | `source.json` |
| The endpoint schema `apeWebhookEndpoint` carries `withBasicAuth`, `username` and `password`, and no other credential member | `source.json` |
| The notification shapes: the `failure` example; the others `apeBaseWebhookInformation` plus `status`, `type: ORDER`; `ikentooAccountIdentifier` shaped `A17700.3`; the status enum `SUCCESS, FAILURE, IN_DELIVERY, READY_FOR_PICKUP, CLOSED, ABANDONED, CANCELLED` | `source.json` webhooks |
| Order `FAILURE`, `READY_FOR_PICKUP` and `CANCELLED` are always sent; `order: DELIVERED` is subscribable | `source.json` `apeEventResource` |
| The tax breakdown's path, `businessLocationId` int64 with `minimum: 1`, and `orders-api` | `source.json` `tax-preview-apiTaxBreakdown` |
| Its request body is required: `accountProfileCode`, `items[].sku` (required, at most 25), `items[].quantity` (double), `items[].subItems[]` of the same | `source.json` |
| Its response: `transactions[]` and `taxLines[]` of numbers, `taxLines[].taxIncluded` boolean, the three `*InCents` totals int64, `amountDue` a number "in big decimal format" | `source.json` |
| `taxRate` is "a decimal number encoded in a string, \"1.20\" means 20% tax" | `source.json` |
| Its 400, 403, 404 and 503 under `*/*`: `{status: "<code>" (a string), timestamp, message, apiSubExceptions[{field, rejectedValue, message}]}` | `source.json` |

## Judgment

| Behaviour | Basis |
|---|---|
| `GET /oauth/authorize` approves automatically; an armed `authorize_denied` redirects with `error=access_denied` and the state | a stand-in for an interactive page; RFC 6749 §4.1.2.1 |
| A code is single use and lives ten minutes | RFC 6749 §4.1.2 |
| Every token-endpoint refusal is RFC 6749 §5.2: `{"error", "error_description"}`, 400 or 401, `WWW-Authenticate: Basic` on `invalid_client` | V1 documents no token-endpoint error |
| A parameter in the undocumented place (exchange in the body, refresh in the query) is 400 `invalid_request`, reason `v1_exchange_reads_query_parameters` / `v1_refresh_reads_form_body` | strict reading of the overview |
| A JSON refresh body is accepted beside the documented form | the X-Series precedent: the body reader is content-type general |
| A malformed body on the token endpoint is 400 `invalid_json` before client authentication | conformance C04: a parse failure is the vendor's error, never the framework's |
| The trailing space in `scope` is always present | both samples carry it |
| A refresh leaves the previous access token valid until its own expiry | D-010: nothing documents revoking it |
| Every 4xx on the reads is `{"status", "error", "message"}` — `apePaymentBadRequestError` without `timestamp` and `path`; 401 missing/unknown/expired bearer, 403 without `orders-api`, 400 missing or non-integer id, 404 unknown location or menu | "a 4xx error"; RFC 6750 §3.1; C10 compares both bindings' bytes |
| Every 503 is the documented `*/*` envelope, also on the two routes that declare none (one declared deviation) | the envelope `apeGetMenuByIdV2` declares for its 503 and the tax breakdown for its 400, 403, 404 and 503 |
| One unit is one merchant account: every token sees every seeded business | no binding is documented |
| `richContent=false` (the default) strips `itemRichData`; `accountProfile` is accepted and ignored | the parameter descriptions |
| Seeded values: ids, names, prices and tax rates | obvious placeholders |
| The retry schedule (60 s, 5 min, 15 min, 1 h; 10 s timeout) and the `x-vendorfake-*` retry headers | K-Series documents none |
| Every order status change is delivered to the order's endpoint whatever `subscribeTo` holds; `SUCCESS` included, though neither list names it | the tutorial's confirmation webhooks |
| An unknown SKU is a `FAILURE` order, with reason `Unknown SKU <sku> at business location <id>` | the tutorial's "problem with the order" |
| A `FAILURE` order frees its reference: only an order that reached the POS spends it | the tutorial: such an order "will need to be corrected and sent again" |
| An `endpointId` naming no registration is accepted, and nothing is delivered | nothing documented |
| A second `PUT` for an existing id is 400 `invalid_value` on `endpointId`; `withBasicAuth` without both credentials is 400 `missing_field` | nothing documented |
| An update or delete of an unknown id is the GET's 404 | the one documented 404 |
| Every other member an update omits is kept from the stored endpoint | the reset note names only three |
| The password is echoed | the schema includes it |
| Routing travels in the event type, `order:<STATUS>:<endpointId percent-encoded>`; a registration subscribes to its own `order:*:<id>` only | the core's matcher |
| No HTTPS rule on `url`, beyond refusing a link-local host | none is documented |
| 404 for an unknown business location on the to-go order | the reads' choice |
| A to-go order with no item (`items` absent or `[]`) is 400 `invalid_value` on `items`, and nothing is stored or notified | the schema requires no item; accepting an empty order silently would hide a consumer bug |
| HTTP Basic is the only delivery authentication | the endpoint schema names no other scheme |
| Tax breakdown: half-up rounding, once per line amount and once per tax part | nothing documented |
| Tax breakdown: the inclusive split `gross / (1 + R) × rate` | nothing documented |
| Tax lines keyed on description, rate and inclusion; `taxCode` and `taxName` omitted | the seeded menu carries neither |
| An unknown SKU is 400 with one sub-exception; an unknown location is 404 | a body value versus a path value |
| `{}` is 200 with empty arrays and zeros; an empty body is 400 `missing_field` | `requestBody.required` |
| `quantity` defaults to 1 and must be a finite number above 0 | nothing documented |
| A sub-item is its own transaction line, right after its parent, at parent × sub quantity | nothing documented |
| The first served menu in store order wins when two carry one SKU | nothing documented |
| `taxes[]` is authoritative; `amount`, `defaultTaxAmount` and `defaultTaxPercentage` are never read | `amount` "can change dynamically at time of sale" |
| `accountProfileCode` is accepted and ignored | one price per item |
| A line or total beyond an int64 of cents is 400 on `items` | the totals are int64 |
| The 403 keeps the integer-status envelope (two declared deviations) | the kernel refuses before the route runs |

## Unverified

- Whether the real V1 endpoint tolerates parameters in the other place (the
  exchange in the body, the refresh in the query).
- Whether `timestamp` and `path` appear on a real 4xx from the reads.
- Whether the real API lets a reference be reused after a `FAILURE`, and what it
  does with an `endpointId` naming no registration.
- What the real API answers to a second `PUT` for an existing `endpointId`.
- The contents of the tutorial's second confirmation webhook, shown only as a
  screenshot: this unit sends one notification per status change.
- Whether a 2xx other than 200 is accepted as delivered (this unit accepts any).
- The real tax breakdown's rounding mode and how it allocates tax across lines.
- The real status for an unknown SKU on the tax breakdown.
- Whether a real 403 carries the string-status envelope.
- How a real location prices sub-items.
- Whether `taxCode` and `taxName` are always present.

## Differences from X-Series

- A refresh does **not** revoke the access token it came with; X-Series does.
- The code exchange reads the query string, and the client authenticates with
  HTTP Basic, not `client_id`/`client_secret` body members.
- No rate limiter: K-Series documents none.

## Deferred

Until a consumer asks: V2 authentication (OpenID Connect), the V1-to-V2 token
exchange, `GET /oauth/userinfo`, `accountProfileCode` pricing, conditional tax
rules and `/f/finance/{businessLocationId}/tax-rates`. Open, pending the two
consumer facts below: the V1 menu load (deprecated 2026-05-15). Not planned:
local orders, the `/business-locations` webhook
operations and payment, item and order_api notifications, the `account`
snapshot, `subscribeTo` filtering, `order: DELIVERED`, scheduled dispatch,
`maxTimeToAttemptOrderDeliverToPos` elapsing, `accountProfile` pricing, rate
limits, per-token location binding.

Two consumer facts are still owed: which menu load the consumer calls, and
whether its client id starts with `devp-v2`.
