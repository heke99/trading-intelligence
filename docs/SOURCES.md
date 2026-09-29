# Source contracts reviewed on 2026-09-28

Only public provider documentation was consulted. The program has not been exercised
with an authenticated C2 account. The development container could not resolve public
network hosts, so requests were tested with injected offline transports. Documentation
pages were read through the browsing tool, not through a successful live API probe.

## Collective2

- API4 General reference / endpoint index:
  https://api4-general.collective2.com/index.html
- General schema/reference, including historical orders and historical closed trades:
  https://api-docs.collective2.com/apis/general/swagger/schemas/getsubscribedstrategies
- Cursor pagination, Limit/AscendingOrder, URL-decoding cursors, and status 200 examples:
  https://api-docs.collective2.com/guides/pagination
- HistoricalTradeDTO schema (provider reference; shared DTO):
  https://api-docs.collective2.com/apis/whitelabel/swagger/schemas/helloresponse
- OrderStatusDTO and explicit UTC meaning of PostedDate (provider reference; shared DTO):
  https://api-docs.collective2.com/apis/geosite/swagger/schemas/orderdto
- API4 key setup:
  https://support.collective2.com/hc/en-us/articles/360001154907-Where-can-I-find-my-API-key
  Current Collective2 API4 page also links to https://collective2.com/apikey
- API4 quickstart and Bearer authorization:
  https://api-docs.collective2.com/guides/quickstart
- FOREX VIX-3 page, Trading Record / Download CSV and hypothetical-results warning:
  https://collective2.com/details/134962085
- Terms to confirm against the actual licensing agreement:
  https://collective2.com/terms-of-service.html

The implementation calls only the **General API host**, never the GeoSite or WhiteLabel
hosts. Shared schema references are used for field semantics; permissions and real
response shapes must be verified for the General API account. Both documented PascalCase
and older camelCase forms are accepted; ambiguous duplicate-case fields fail closed.
The full OpenAPI JSON was not downloaded in this environment.

`GetStrategyHistoricalClosedTrades` is documented as non-paginated and groups orders
into trades. `GetStrategyHistoricalOrders` is paginated. Closed trades are requested
with explicit CommissionPlan=0, not an assumed net/gross interpretation.

## Future MT5 adapter — not implemented here

- Broker deal-history fields:
  https://www.mql5.com/en/docs/python_metatrader5/mt5historydealsget_py
- Terminal report export:
  https://www.metatrader5.com/en/terminal/help/trading_advanced/history_report

## Verification limits

No CSV downloaded from a real C2 account was available for a verified fixed header map.
The included CSV and mapping are synthetic contract examples, not reproductions of a
claimed provider export. The seven manually transcribed trade examples from the previous
research message were intentionally NOT treated as a full or licensed training dataset.
No copytrading subscription was purchased. No broker was connected. No orders were placed.

## API4 request and 403 review — 2026-09-29

The current requests were captured using an injected synthetic transport and
compared with the official General API reference:

| Request detail | Implementation and documented contract |
| --- | --- |
| Server | `https://api4-general.collective2.com` |
| Closed trades | `GET /Strategies/GetStrategyHistoricalClosedTrades`, `StrategyId`, `CommissionPlan=0`; non-paginated |
| Historical orders | `GET /Strategies/GetStrategyHistoricalOrders`, `StrategyId`, `Limit=500`, `AscendingOrder=true`; cursor-paginated |
| Authentication | `Authorization: Bearer <local key>` |
| Required content header | `Content-Type: application/json` |
| Accept | `application/json` |
| Cursor handling | Decode once before URL-encoding it into the next query; completion uses the cursor rather than row count |

References additionally checked:

- Required request headers (X-AppId and X-Version are optional):
  https://api-docs.collective2.com/guides/request-headers
- Authorization header format:
  https://api-docs.collective2.com/guides/authorization
- Error semantics: 401 is a wrong key; 403 means denied access to the content:
  https://api-docs.collective2.com/guides/error-codes
- `GET /General/GetAccessKey` and AccessKeyDTO are in the General API reference.
  Its raw response includes `AccessKey`, personal fields, `Role` and `DeleteDate`.
  The local diagnostic deliberately exposes only validated role/deletion metadata,
  status codes and counts. `DeleteDate` is not claimed to be an expiration timestamp.
  https://api-docs.collective2.com/apis/general/swagger/schemas/searchstrategies

The header requirements are already present in main commit `8c50561`. No documented
request-format mismatch was found that explains the user's 403. This review does
not prove access for a real key, establish per-strategy entitlements, or attribute
the user's response to the application versus a gateway. The diagnostic must be
run locally to obtain the missing endpoint-level evidence. It does not relax the
importer's reflected-secret rejection or enable a trading/subscription method.
