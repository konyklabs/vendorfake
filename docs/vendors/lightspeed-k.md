# Lightspeed Restaurant K-Series (V1 authentication)

The fifth vendor, identifier `lightspeed-k`, and the first whose identifier
differs from its module (`vendorfake.lightspeed_k`). Slice 1 of D-016: the V1
token lifecycle and three Order and Pay reads. Lightspeed's other Restaurant
series are not modelled.

!!! warning "Unofficial"
    Built from Lightspeed's public documentation only, without sandbox or
    partner access; konyklabs is not affiliated with, endorsed by, or connected
    to Lightspeed. The same statement is published at `GET /__unit/info` under
    `auth.statement`. Every behaviour that is *not* documented is labelled
    JUDGMENT here and at its site in the code.

## What is modelled

Five routes on one merchant account:

| Route | Operation | Fidelity |
|---|---|---|
| `GET /oauth/authorize` | stand-in for the consent screen | EXCUSED: prose only |
| `POST /oauth/token` | the V1 token endpoint, both grants | EXCUSED: prose only |
| `GET /o/op/data/businesses` | `apeLookupBusinesses` | validated against `source.json` |
| `GET /o/op/1/menu/list` | `apeLoadMenus` | validated against `source.json` |
| `GET /o/op/2/menu/load/{menuId}` | `apeGetMenuByIdV2` | validated against `source.json` |

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
{"menuName":"Unit Lunch Menu","ikentooMenuId":100000000201,"menuEntryGroups":[{"@type":"group","id":"100000000301","name":"Mains","color":"blue","menuEntry":[{"@type":"menuItem","productName":"Unit Burger","productPrice":12.5,"sku":"UNITK-001","taxes":[{"description":"10% VAT","amount":1.25,"percentage":10.0}],"defaultTaxAmount":1.25,"defaultTaxPercentage":10.0,"taxIncludedInPrice":true,"menuModifierGroups":[]},{"@type":"menuItem","productName":"Unit Lemonade","productPrice":4.0,"sku":"UNITK-002","taxes":[{"description":"10% VAT","amount":0.4,"percentage":10.0}],"defaultTaxAmount":0.4,"defaultTaxPercentage":10.0,"taxIncludedInPrice":true,"menuModifierGroups":[]}]}],"richDataMissing":false,"conditionalTaxRules":false}
$ curl -s -X POST http://127.0.0.1:8125/oauth/token -H "Authorization: $BASIC" -d grant_type=refresh_token -d refresh_token=unit-lightspeed-k-refresh-token-full
{"access_token":"ba3b68ac-d77f-45e2-9fa3-b04ec4b4cdba","token_type":"bearer","refresh_token":"2ecfe92a-4ad1-4d11-ad28-a903e44f15f8","expires_in":3599,"scope":"financial-api orders-api "}
$ curl -s -X POST http://127.0.0.1:8125/oauth/token -H "Authorization: $BASIC" -d grant_type=refresh_token -d refresh_token=unit-lightspeed-k-refresh-token-full
{"error":"invalid_grant","error_description":"The refresh token was already used; refresh tokens can only be used once."}
$ curl -s 'http://127.0.0.1:8125/o/op/1/menu/list?businessLocationId=100000000101'
{"status":401,"error":"Unauthorized","message":"An Authorization: bearer header is required."}
```

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
| Every 503 is the documented `*/*` envelope, also on the two routes that declare none (one declared deviation) | the only declared 503 |
| One unit is one merchant account: every token sees every seeded business | no binding is documented |
| `richContent=false` (the default) strips `itemRichData`; `accountProfile` is accepted and ignored | the parameter descriptions |
| Seeded values: ids, names, prices and tax rates | obvious placeholders |

## Unverified

- Whether the real V1 endpoint tolerates parameters in the other place (the
  exchange in the body, the refresh in the query).
- Whether `timestamp` and `path` appear on a real 4xx from the reads.

## Differences from X-Series

- A refresh does **not** revoke the access token it came with; X-Series does.
- The code exchange reads the query string, and the client authenticates with
  HTTP Basic, not `client_id`/`client_secret` body members.
- No rate limiter: K-Series documents none.

## Deferred

The V1 menu load (deprecated 2026-05-15), V2 authentication (OpenID Connect),
the V1-to-V2 token exchange and `GET /oauth/userinfo` (slice 3), to-go and local
orders and webhooks (slice 2), the tax breakdown, `accountProfile` pricing, rate
limits, per-token location binding.

Two consumer facts are still owed before slice 2: which menu load the consumer
calls, and whether its client id starts with `devp-v2`.
