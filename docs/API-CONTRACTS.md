# API Contracts

## Purpose

This document defines the external API contracts used by the standalone copy-trading program in V1.

The goal is to remove ambiguity around:

- endpoints
- request shapes
- response fields
- symbol normalization
- timestamp handling
- exchange trading-rule inputs

## Contract Principles

- parse only the fields required by V1
- normalize external payloads into internal typed models immediately
- treat missing required fields as data-unavailable errors, not as zero values
- do not let SQLite or prior cycles fill in missing API data

## Hyperliquid

### Endpoint

- method: `POST`
- URL: `https://api.hyperliquid.xyz/info`

### Request

Request body:

```json
{
  "type": "clearinghouseState",
  "user": "<wallet_address>"
}
```

V1 does not require additional request fields.

### Required Response Fields

Top-level fields used by V1:

- `assetPositions`
- `time`

Per position fields used by V1:

- `assetPositions[].position.coin`
- `assetPositions[].position.szi`
- `assetPositions[].position.entryPx`
- `assetPositions[].position.positionValue`
- `assetPositions[].position.positionValue` — read but not used in V1; reserved for future notional reporting
- `assetPositions[].position.leverage.value` as optional metadata

### Normalization Rules

Internal source position model:

- `symbol`
- `side`
- `size`
- `entry_price`
- `source_timestamp`

Normalization logic:

- `symbol` comes from `coin` after config-based symbol mapping
- `size = Decimal(szi)`
- `side` is derived from the sign of `size`
- `entry_price = Decimal(entryPx)` when present
- `source_timestamp` comes from top-level `time`

Side rules:

- `size > 0`: long
- `size < 0`: short
- `size == 0`: flat

V1 must not rely on any textual side field from Hyperliquid.

### Timestamp Rule

`source_timestamp` must use Hyperliquid's response `time`.

If `time` is missing or invalid:

- the source snapshot is invalid for that cycle
- the cycle outcome for affected symbols is `SKIP_DATA_UNAVAILABLE`

The implementation must not silently replace `source_timestamp` with local system time.

### Symbol Mapping

V1 uses explicit config mapping from source asset symbol to Binance symbol.

Example:

```yaml
copy_trade:
  symbols:
    mapping:
      BTC: BTCUSDT
```

Rules:

- only mapped symbols are eligible for reconciliation
- unmapped source symbols should emit warnings
- unmapped symbols should not enter target calculation

### Empty Position Handling

If `assetPositions` is empty:

- treat the source as flat for all configured symbols
- do not treat it as an error

If a configured symbol is absent from `assetPositions`:

- treat that symbol's source size as `0`

## Binance

### Position Snapshot

Endpoint:

- method: `GET`
- path: `/fapi/v3/positionRisk`

Use:

- fetch actual one-way perpetual positions
- derive actual signed size and entry price

Required fields per symbol:

- `symbol`
- `positionAmt`
- `entryPrice`
- `positionSide`
- `updateTime`

Normalization rules:

- `actual_size = Decimal(positionAmt)`
- `side` is derived from the sign of `actual_size`
- `entry_price = Decimal(entryPrice)`
- `binance_timestamp = updateTime`

One-way mode contract:

- V1 supports only `positionSide = BOTH`
- any other position mode is a startup validation error

### Reference Price

Endpoint:

- method: `GET`
- path: `/fapi/v1/premiumIndex`

Use:

- obtain `markPrice` as the V1 reference price

Required field:

- `markPrice`

### Executable Price

Endpoint:

- method: `GET`
- path: `/fapi/v1/ticker/bookTicker`

Use:

- obtain executable side-aware market proxy price

Required fields:

- `bidPrice`
- `askPrice`

Execution-side selection:

- buy orders use `askPrice`
- sell orders use `bidPrice`

### Trading Rules

Endpoint:

- method: `GET`
- path: `/fapi/v1/exchangeInfo`

Use:

- load symbol filters and precision inputs

Required symbol-level filters:

- `LOT_SIZE`
- `MARKET_LOT_SIZE`
- `MIN_NOTIONAL`

V1 must not use display precision fields as a substitute for executable filters.

### Market Order Tradability Calculation

For each proposed market order:

1. start from raw proposed quantity
2. apply convergence and notional caps
3. round toward zero to the allowed market step size
4. check quantity minimums
5. check quantity maximums
6. check `MIN_NOTIONAL` using reference mark price

Filter combination rules:

- effective step size = stricter of `LOT_SIZE.stepSize` and `MARKET_LOT_SIZE.stepSize`
- effective min qty = stricter of `LOT_SIZE.minQty` and `MARKET_LOT_SIZE.minQty`
- effective max qty = stricter of the two max constraints
- min notional check uses `abs(order_qty * mark_price)`

If any rule fails:

- the order is not tradable
- the decision outcome is `SKIP_BELOW_THRESHOLD`

### Order Submission Contract

V1 order type:

- `MARKET`

Required behavior:

- submit only one order per cycle in V1
- use close-then-open for flips
- do not issue the reverse-side open until a later fresh snapshot confirms flat or operationally flat

Suggested order intent mapping:

- increase long: `BUY`
- reduce long: `SELL`
- close long: `SELL`
- increase short: `SELL`
- reduce short: `BUY`
- close short: `BUY`

### Error Handling Boundary

Read-only Binance failures:

- positions unavailable
- prices unavailable
- exchange info unavailable

These failures must block execution for that cycle.

Order-placement failures:

- follow `ERROR-TAXONOMY.md`
- may trigger automatic downgrade only in `live`

## Internal Normalized Models

### Source Position

```python
class SourcePosition:
    symbol: str
    side: str
    size: Decimal
    entry_price: Decimal | None
    source_timestamp: datetime
```

### Actual Position

```python
class ActualPosition:
    symbol: str
    side: str
    size: Decimal
    entry_price: Decimal | None
    binance_timestamp: datetime | None
```

## V1 Symbol Scope

V1 live scope is one symbol:

- source asset: `BTC`
- Binance perpetual symbol: `BTCUSDT`

The API integration should still use mapping-based normalization so later expansion does not require a redesign.
