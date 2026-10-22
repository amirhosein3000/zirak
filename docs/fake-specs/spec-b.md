# FAKE SPEC B — «تریدر هوشمند برای والکس» (trading competition track)

_Rehearsal only. Written by us to practise spec day; not from Wallex._

## Problem
Build an automated trader that performs well on Wallex under strict risk.

## Setup and rules
- Each team gets an **API key for a competition sub-account** on the real Wallex API, funded with
  **50,000,000 TMN**. Trading permission only. Withdrawals are disabled.
- Allowed markets: **BTCTMN, ETHTMN, USDTTMN**. Spot only. Any documented order type.
- The competition runs for **48 hours** (Saturday 10:00 → Monday 10:00 Tehran time). No manual trading
  during the window: any order placed from the Wallex website/app disqualifies the team.
- Rate limits are the documented ones; abusive traffic is disqualifying.
- Teams may stop their bot at any time; they may not restart with new code after hour 24.

## Judging criteria
| Criterion | Weight |
|---|---|
| Net PnL in Toman at the end (marked to the last trade price, fees included) | 50 % |
| Maximum drawdown during the window (lower is better) | 30 % |
| Logging quality and explainability (required format below) | 20 % |

## Required logging format
1. `orders.csv`, one row per order **state change**, header exactly:
   `timestamp_utc,client_order_id,symbol,side,type,price,quantity,status,filled_quantity,avg_price,fee,fee_asset,reason`
   (`reason` = one sentence in Persian or English).
2. `equity.csv` every 5 minutes: `timestamp_utc,total_value_tmn,drawdown_pct`.
3. A final `report.json`: start/end value, PnL, max drawdown, number of trades, and a link to the code
   commit that ran.

## Deliverables
The log files above (uploaded at the end), the repository, and a 1-page strategy description.

## Time limit
Code freeze 2 hours before the window opens (i.e. 20 hours after the spec is published).
