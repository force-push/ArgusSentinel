# Regime Surface Research

Generated: 2026-07-07T14:33:43+00:00
Scope: last 6h

Research-only. This report reads resolved real trades from `data/decisions.db` and does not change live policy.

## Headline

- Trades analysed: 9
- Win rate: 88.9% vs break-even 52.1%
- PnL: $+8.16
- Avg/trade: $+0.907

## Feature Construction

- Momentum pressure: direction-aligned DI imbalance, RSI, MACD gap expansion, MACD sign consistency, trend age.
- Volatility pressure: ATR bps, Bollinger width bps, MACD gap std, ADX.
- Shock pressure: ATR bps + positive gap expansion + MACD instability.
- Buckets are quartiles within the analysed sample, so labels are relative to current Argus history.

## Regime Label

bucket | n | WR | PnL | avg/trade | note
--- | ---: | ---: | ---: | ---: | ---

## Volatility x Momentum Surface

bucket | n | WR | PnL | avg/trade | note
--- | ---: | ---: | ---: | ---: | ---

## Shock x Entry Kind

bucket | n | WR | PnL | avg/trade | note
--- | ---: | ---: | ---: | ---: | ---

## Regime x Direction

bucket | n | WR | PnL | avg/trade | note
--- | ---: | ---: | ---: | ---: | ---

## Regime x Entry Kind

bucket | n | WR | PnL | avg/trade | note
--- | ---: | ---: | ---: | ---: | ---

## Pair x Regime Candidates

bucket | n | WR | PnL | avg/trade | note
--- | ---: | ---: | ---: | ---: | ---

## UTC Hour x Regime Candidates

bucket | n | WR | PnL | avg/trade | note
--- | ---: | ---: | ---: | ---: | ---

## Interpretation

Promote nothing from this report directly into live trading. Treat positive buckets as hypotheses for a shadow gate or a locked walk-forward test.

Strong pair/regime hypotheses:
- None reached the guardrail.

Weak pair/regime avoid-list candidates:
- None reached the guardrail.
