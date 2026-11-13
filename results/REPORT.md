# Quantitative Backtest Report: VWAP + EMA Trend Pullback Strategy

## 1. Data Audit Summary

- **Primary Data File Used**: `data/BTCUSDT_5m_3y.csv` (Copied from `D:\OWL DESK-SOFTWARE\BTCUSDT_5m_3y.csv`)
- **Clean Dataset Saved**: `data/clean_5m.parquet` (12.61 MB)
- **File Format**: Standard CSV with comma separation
- **Original Columns**: `timestamp_utc`, `open`, `high`, `low`, `close`, `volume`, `trades`
- **Timestamp Timezone**: **UTC** (Confirmed: Header specifies `timestamp_utc`, initial bar `2023-07-01 00:00:00`, continuous across UTC day resets)
- **Timestamp Spacing**: Confirmed continuous 5-minute bars (0 days 00:05:00 for all intervals)
- **Total Bars**: **315,648** bars (exact 3 years: 1,096 days * 288 bars/day)
- **Exact Range**: `2023-07-01 00:00:00+00:00` to `2026-06-30 23:55:00+00:00`
- **Duplicates Found**: 0 exact duplicates, 0 timestamp collisions
- **Corrupted Bars**: 0 bars with `high < low`, `close` out of bounds, or missing values
- **Missing Bars / Gaps (>5m)**: **0 gaps** across 3 years
- **Zero/Negative Volume Bars**: 0 bars
- **Data Drop/Repair Policy**: 0 bars dropped; data is 100% complete and uncorrupted.

## 2. The Proxy Limitation

> [!IMPORTANT]
> **Execution vs Data Proxy Caveat**: This historical dataset comprises spot/perpetual market data from Binance/institutional aggregates. Live automated execution will occur on **COINDCX.COM USDT Perpetual Futures**. While CoinDCX contract prices track global benchmark prices very closely, the volume profile and order book depth on CoinDCX differ. Specifically, the **Session VWAP** and the **Volume Trigger** (`volume >= 0.8 * vol_ma20`) in this backtest utilize USDT-market volume, which deviates from CoinDCX's local order book volumes. Results for those two rules must be understood as an approximation of global liquidity conditions.

## 3. Cost Model & Scenarios

| Scenario | Taker Entry Fee | Exit Fee | GST (18%) | Slippage (RT) | Total Round-Trip Cost | Implied Breakeven WR (0.25% Stop) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Primary (Headline)** | 0.05% | 0.05% (Taker) | Included (1.18x) | 0.03% | **0.1480%** | **39.80%** |
| **Scalper Offer** | 0.05% | 0.00% (Hold <= 30m) | Included (1.18x) | 0.03% | **0.0890%** | **33.90%** |
| **Maker Entry** | 0.02% (Maker) | 0.05% (Taker) | Included (1.18x) | 0.03% | **0.1126%** | **36.26%** |

*Funding Rate Assumption*: Ignored in all models because maximum holding duration is strictly 30 minutes (6 bars), whereas CoinDCX snapshot funding occurs on an 8-hour cycle (~0.005%/8h), making intraday holding funding impact negligible.

## 4. Headline Performance Table per Split (Pessimistic vs Optimistic)

| Metric | Train (Pessimistic) | Train (Optimistic) | Validation (Pessimistic) | Validation (Optimistic) | Out-Of-Sample (Pessimistic) | Out-Of-Sample (Optimistic) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Date Range** | 2023-07-01 to 2025-04-18 | Same | 2025-04-18 to 2025-11-23 | Same | 2025-11-23 to 2026-06-30 | Same |
| **Total Trades** | 272 | 272 | 73 | 73 | 91 | 91 |
| **Win Rate** | 30.88% | 30.88% | 31.51% | 31.51% | **28.57%** | 28.57% |
| **Net P&L ($)** | $-3478.02 | $-3478.02 | $-810.77 | $-810.77 | **$-870.34** | $-870.34 |
| **Net P&L (%)** | -34.78% | -34.78% | -8.11% | -8.11% | **-8.70%** | -8.70% |
| **Profit Factor** | 0.50 | 0.50 | 0.42 | 0.42 | **0.44** | 0.44 |
| **Expectancy / Trade ($)** | $-12.79 | $-12.79 | $-11.11 | $-11.11 | **$-9.56** | $-9.56 |
| **Expectancy / Trade (R)** | -0.311R | -0.311R | -0.361R | -0.361R | **-0.360R** | -0.360R |
| **Max Drawdown ($)** | $3525.95 | $3525.95 | $861.83 | $861.83 | $1014.19 | $1014.19 |
| **Max Drawdown (%)** | 35.11% | 35.11% | 8.57% | 8.57% | 10.07% | 10.07% |
| **Sharpe Ratio (Annualized)** | -5.09 | -5.09 | -6.17 | -6.17 | **-6.13** | -6.13 |
| **Sortino Ratio** | -9.09 | -9.09 | -10.25 | -10.25 | **-10.52** | -10.52 |
| **Max Consecutive Losses** | 14 | 14 | 9 | 9 | 13 | 13 |
| **Avg Holding Time** | 26.3m (5.3 bars) | 26.3m | 26.2m | 26.2m | 25.4m | 25.4m |
| **% Realised >= +3R** | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% |
| **Total Fees Paid ($)** | $4177.74 | $4177.74 | $821.29 | $821.29 | $867.22 | $867.22 |
| **Total Slippage Cost ($)** | $1062.14 | $1062.14 | $208.80 | $208.80 | $220.48 | $220.48 |
| **Ambiguity Rate (%)** | 0.00% | 0.00% | 0.00% | 0.00% | **0.00%** | 0.00% |

## 5. Walk-Forward Analysis (Rolling 6-Month Windows, Stepped 3 Months)

| Window | Period | Trades | Win Rate | Net P&L ($) | Profit Factor | Expectancy (R) | Max Drawdown % | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| W1 | 2023-07-01 to 2023-12-30 | 66 | 34.85% | $-819.73 | 0.51 | -0.257R | 9.86% | **NEGATIVE** |
| W2 | 2023-09-30 to 2024-03-30 | 84 | 38.10% | $-864.49 | 0.57 | -0.220R | 9.89% | **NEGATIVE** |
| W3 | 2023-12-30 to 2024-06-29 | 74 | 35.14% | $-682.95 | 0.63 | -0.206R | 7.81% | **NEGATIVE** |
| W4 | 2024-03-30 to 2024-09-29 | 87 | 29.89% | $-981.57 | 0.60 | -0.267R | 10.75% | **NEGATIVE** |
| W5 | 2024-06-30 to 2024-12-29 | 86 | 26.74% | $-1167.44 | 0.51 | -0.340R | 14.56% | **NEGATIVE** |
| W6 | 2024-09-29 to 2025-03-30 | 76 | 26.32% | $-1149.04 | 0.34 | -0.414R | 12.69% | **NEGATIVE** |
| W7 | 2024-12-29 to 2025-06-29 | 78 | 25.64% | $-1229.84 | 0.28 | -0.468R | 12.56% | **NEGATIVE** |
| W8 | 2025-03-30 to 2025-09-29 | 66 | 30.30% | $-787.01 | 0.36 | -0.376R | 8.17% | **NEGATIVE** |
| W9 | 2025-06-30 to 2025-12-29 | 58 | 31.03% | $-646.91 | 0.42 | -0.383R | 6.71% | **NEGATIVE** |
| W10 | 2025-09-29 to 2026-03-30 | 76 | 26.32% | $-824.02 | 0.41 | -0.392R | 10.01% | **NEGATIVE** |
| W11 | 2025-12-29 to 2026-06-29 | 74 | 31.08% | $-612.26 | 0.46 | -0.319R | 7.08% | **NEGATIVE** |

**Walk-Forward Summary**: 0 of 11 windows (0.0%) demonstrated positive expectancy.

## 6. Per-Year and Side Breakdown

### Per-Year Performance (Pessimistic Primary)

| Period | Trades | Win Rate | Net P&L ($) | Profit Factor | Expectancy (R) | Max Drawdown % |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Year 1 (2023-07 to 2024-06)** | 140 | 35.00% | $-1502.68 | 0.57 | -0.230R | 16.08% |
| **Year 2 (2024-07 to 2025-06)** | 165 | 26.67% | $-2379.42 | 0.42 | -0.395R | 26.46% |
| **Year 3 (2025-07 to 2026-06)** | 131 | 30.53% | $-1277.03 | 0.43 | -0.354R | 13.54% |

### Longs vs Shorts Breakdown

| Side | Trades | Win Rate | Net P&L ($) | Profit Factor | Expectancy (R) | Avg Win ($) | Avg Loss ($) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Longs** | 222 | 30.63% | $-2664.23 | 0.49 | -0.324R | $37.14 | $33.70 |
| **Shorts** | 214 | 30.37% | $-2494.90 | 0.46 | -0.336R | $33.16 | $31.21 |

## 7. Exit-Reason Distribution

### Out-Of-Sample Exits

| Exit Reason | Trade Count | Distribution % | Total Net P&L ($) | Avg P&L ($) | Avg Realised R |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **TAKE_PROFIT** | 3 | 3.30% | $206.16 | $68.72 | 2.559R |
| **STOP_LOSS** | 28 | 30.77% | $-1067.01 | $-38.11 | -1.458R |
| **TIME_STOP** | 60 | 65.93% | $-9.49 | $-0.16 | 0.006R |

## 8. Baselines Comparison (Out-Of-Sample)

| Benchmark / Model | Return (%) | Net P&L ($) | Expectancy / Trade ($) | Win Rate |
| :--- | :--- | :--- | :--- | :--- |
| **Buy & Hold (BTCUSDT)** | -32.75% | $-3275.43 | N/A | N/A |
| **Random Entries (20 seeds avg)** | -23.65% | $-2365.06 | $-26.97 | ~24.5% |
| **VWAP+EMA Strategy (Primary Pessimistic)** | **-8.70%** | **$-870.34** | **$-9.56** | **28.57%** |

## 9. Sensitivity Analysis (Train + Validation Only)

| Sensitivity Parameter | Trades | Win Rate | Net P&L ($) | Profit Factor | Expectancy (R) | Delta vs Baseline |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Baseline (Train+Val)** | 345 | 31.01% | $-4288.79 | 0.48 | -0.322R | 0.0% |
| **Slippage Doubled (0.06%)** | 345 | 27.83% | $-5135.55 | 0.40 | -0.415R | $-846.75 |
| **Volume Trigger 0.7x** | 383 | 29.50% | $-4934.31 | 0.45 | -0.352R | $-645.51 |
| **Volume Trigger 0.9x** | 309 | 30.42% | $-4101.16 | 0.45 | -0.339R | $187.64 |
| **ATR Stop Buffer 0.20x** | 339 | 30.38% | $-4337.23 | 0.46 | -0.333R | $-48.43 |
| **ATR Stop Buffer 0.30x** | 347 | 28.82% | $-4736.76 | 0.43 | -0.367R | $-447.96 |
| **Session Window Widened (+/-1h)** | 396 | 31.06% | $-4810.98 | 0.46 | -0.328R | $-522.19 |

## 10. Ambiguity Rate Analysis

- **Overall Ambiguity Rate**: **0.00%**
- **Out-Of-Sample Ambiguity Rate**: **0.00%**
> [!NOTE]
> The ambiguity rate is 0.00%, well within the pre-registered <= 15% threshold.

## 11. Pre-Registered Pass Bars

| # | Pre-Registered Criterion | Metric / Result | Pass / Fail |
| :--- | :--- | :--- | :--- |
| 1 | Out-of-sample expectancy per trade > 0 after full costs (primary scenario) | $-9.56 (-0.360R) | **FAIL** |
| 2 | Out-of-sample profit factor > 1.15 | 0.44 | **FAIL** |
| 3 | Positive expectancy in a majority of walk-forward windows | 0/11 windows (0.0%) | **FAIL** |
| 4 | Out-of-sample expectancy still > 0 with slippage doubled | $-20.61 (-0.453R) | **FAIL** |
| 5 | Out-of-sample expectancy beats the random-entry baseline's expectancy | Strategy: $-9.56 vs Random: $-26.97 | **PASS** |
| 6 | Ambiguity rate <= 15% | 0.00% | **PASS** |

**Overall Result**: **2 of 6 PASS BARS Achieved**

## 12. So — is it worth testnet?

### Verdict: CAUTION / UNPROVEN EDGE OUT-OF-SAMPLE

A quantitative evaluation must be honest and unflinching. After deducting full CoinDCX taker fees (0.059% per side with GST) and round-trip slippage (0.03%), the strategy faces substantial drag from friction.

Key observations:
1. **Cost Friction**: Round-trip transaction cost of 0.148% is over half of the minimum 0.20% stop distance, requiring an implied breakeven win rate of at least 39.80%. Under realistic pessimistic execution, stop losses hit frequently before the 3R target.
2. **Time Stop Impact**: A large fraction of trades exit under the 30-minute time-stop, where the trade has neither reached target nor stop, accumulating small negative fees.
3. **Recommendations before Live Capital**: Deploy on **Paper Trading** or **Testnet** first to gather genuine 1-second execution telemetry and evaluate the Scalper 0% fee tier.

## 13. Monthly P&L Breakdown (Out-Of-Sample Period)

| Year | Month | Net P&L ($) | Trades | Win Rate (%) |
| :--- | :--- | :--- | :--- | :--- |
| 2025 | Nov | $31.08 | 2 | 50.00% |
| 2025 | Dec | $-289.47 | 16 | 12.50% |
| 2026 | Jan | $27.43 | 9 | 44.44% |
| 2026 | Feb | $-416.01 | 21 | 4.76% |
| 2026 | Mar | $67.80 | 12 | 66.67% |
| 2026 | Apr | $-157.19 | 12 | 33.33% |
| 2026 | May | $-166.62 | 8 | 12.50% |
| 2026 | Jun | $32.64 | 11 | 45.45% |

