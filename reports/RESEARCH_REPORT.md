# Research Report — Systematic Strategy Discovery & Validation

*Data through 2026-10-30 (ETFs) / 2026-10-31 (crypto). Generated with the code at tag `frozen-pre-holdout` plus later reporting-only commits.
Every number here is a **simulated** backtest or paper-trading result on historical data, net of modelled costs. None of it is realised profit.*

## Executive summary

**No strategy showed a robust, exploitable edge over simple passive investing after realistic costs, multiple-testing correction and an untouched holdout.**

- I tested 28 strategy/market combinations (200 parameter trials, every one logged in `reports/trial_ledger.csv`) across trend following, mean reversion, cross-sectional momentum, statistical arbitrage, volatility strategies and machine learning, on US-listed multi-asset ETFs (1993–2026) and Binance crypto spot and perpetuals (2017–2026).
- **Two strategies passed the pre-registered walk-forward gate**: `rotation_filtered_etf` (trend-filtered relative-strength rotation) and `vix_regime_spy` (S&P 500 vs Treasuries switching on the VIX). Both are equity/bond regime-timing rules.
- **Both decayed sharply in the 2022–2026 holdout**, which was evaluated once, after the strategy set was frozen:

  | | WF-OOS 2008–2021 excess Sharpe | Holdout 2022–2026 excess Sharpe [95% CI] | Holdout CAGR | SPY holdout CAGR / Sharpe |
  |---|---|---|---|---|
  | rotation_filtered_etf | 0.80 | 0.16 [−0.57, 0.95] | 5.2% | 11.6% / 0.50 |
  | vix_regime_spy | 0.82 | 0.10 [−0.78, 0.95] | 4.3% | 11.6% / 0.50 |

  They technically clear the "holdout Sharpe ≥ 0" rule, but they earned roughly cash plus 1% and trailed both SPY and the 60/40 benchmark.
- Even before the holdout their risk-adjusted performance (Sharpe 0.80–0.82) only matched a passive **60/40 SPY/IEF portfolio (0.78)** over the same window. In raw return, no ETF strategy beat SPY: reality check p = 0.95.
- **No crypto strategy passed.** Crypto momentum looks spectacular in-sample (WF Sharpe 1.0–1.4) but its drawdowns run 75–84%, it collapsed in the second half of the window, and it underperformed BTC buy-and-hold in the holdout.
- **Recommendation:** keep paper trading only as a low-stakes forward check of the infrastructure and the two regime rules. Do **not** commit real capital on this evidence. For income, a passive 60/40 portfolio did as well in every withdrawal test.

## 1. Market discovery (Phase 1)

| Market | Access for an EU retail trader | Typical cost (one-way) | Data used here | Assessment |
|---|---|---|---|---|
| US equity/sector ETFs | Easy via IBKR etc., **but** PRIIPs bars EU retail from buying US-domiciled ETFs. UCITS clones (LSE/Xetra) are the realistic route, or professional status. | 2–4 bp + min fees | Yahoo adjusted daily, 1993–2026 | Deep and liquid with low costs, but efficient. Only regime/risk-timing rules survived. |
| European equities | UCITS ETFs and single stocks; country ETFs used as a proxy | 3–6 bp | EWG/EWU/EWQ/EZU/VGK | Country momentum failed (WF Sharpe 0.12). |
| Commodities | Futures need margin and roll handling. ETFs (USO/UNG/DBC) embed roll costs (contango). | 4–15 bp (ETF) | ETF proxies + EIA spot as reference | ETF contango erodes trend returns. No contract-level futures data was available (see §9). |
| FX majors | Spot/CFD/futures; the currency trusts used here are thin | 4–10 bp (trusts) | FXE/FXB/FXY/FXF/FXA/UUP, Fed H.10 | Only in multi-asset trend, which failed. |
| Rates/credit | Treasury/credit ETFs | 2–3 bp | SHY/IEF/TLT/TIP/LQD/HYG | Useful as the defensive leg of rotations. |
| Volatility | VIX ETPs decay heavily, and shorting them is dangerous | 4–10 bp + borrow | VIX index, VIXY | VIX as a *signal* worked pre-2022; trading vol products was not attempted. |
| Crypto spot/perps | 24/7 with easy access; perps allow shorting | 10 bp spot taker, 5 bp perp taker, plus spread/slippage (2–3× for alts) | Binance official archive, funding rates | High volatility, 45–85% strategy drawdowns, venue and counterparty risk. |

Short selling was modelled with ETF borrow fees of 0.5–8%/yr and with crypto perps using actual historical funding. Idle cash earns T-bills (BIL; SHY before 2007-05) in the ETF account and 0% in the crypto account.

## 2. Data (Phase 2)

**Real data only.** Most market-data APIs are blocked by this sandbox's egress policy (Yahoo, Stooq, FRED, Binance REST, Kraken, Coingecko, Kaggle, HuggingFace). I used these reachable sources:

| Source | Content | Integrity |
|---|---|---|
| Binance public archive (S3 behind data.binance.vision) | 30 spot pairs (1d, 2017-08→), 17 USDT-M perps (2020-01→), funding history | every zip SHA-256-verified against Binance's CHECKSUM files; 0 failures |
| Yahoo Finance via GitHub mirror `o-lq/run` (snapshot 2026-10-31) | 46 ETFs, split- and dividend-adjusted OHLCV | third party, so cross-checked: SPY vs Shiller monthly ρ = 0.999; FXE vs Fed H.10 EUR/USD ρ = 0.84 (4pm vs noon fixing); USO vs EIA WTI ρ = 0.83 (futures vs spot) |
| `datasets/*` on GitHub | EIA WTI/Brent/Henry Hub, Fed H.10 FX, CBOE VIX, BLS CPI, Shiller S&P | reference and features only |

Validation (`reports/data_quality.md`) covers duplicates, non-monotonic timestamps, missing sessions vs the XNYS calendar or every UTC day, OHLC consistency, non-positive prices, stale runs, reverting spikes and >25% moves. ETF spikes count as errors only if idiosyncratic: when ≥3 series spike on the same day (e.g. 2020-03-12), it is a market event. Flagged bars become non-tradable; prices are never altered.

Survivorship handling:
- The crypto universe includes coins that collapsed or were delisted (LUNA, FTT, MATIC, EOS, XMR). Eligibility is point-in-time (top 15 by trailing 30-day volume, ≥115/120 days of history).
- Tickers reused after a gap (LUNA → LUNA 2.0, FTT) are split into separate instruments.
- Positions in instruments that stop trading are force-closed at the last price at 3× cost.
- The ETF universe was fixed ex-ante, but all its ETFs survive to today. Residual survivorship bias is small for broad index ETFs, though it is not zero.

## 3–4. Methodology (strategy research & backtesting)

- **Engine** (`qrs/backtest/engine.py`): signal at the close of t, execution at the **next open**. Costs are per instrument: half-spread + slippage + commission. The engine also models borrow fees, leverage financing, cash interest, perp funding, tradability masks, delisting force-exit, gross caps and an optional ADV participation cap. Unit tests check exact accounting, and the engine reconciles with the independent integer-share simulator and the paper broker (ρ ≥ 0.995).
- **No look-ahead:** for every strategy, a truncation test checks that weights computed with data to T equal weights computed with data to t for all rows ≤ t. This caught a real issue: month-end detection peeked at the next date. It was fixed before the freeze.
- **Protocol** (`configs/research.yaml`, written before any experiment):
  - Expanding-window walk-forward re-selects parameters each January, using only data before the January minus a 21-day embargo. If no parameter set had a positive training Sharpe, the year is **NO TRADE**.
  - ML models use purged and embargoed training labels.
  - The untouched holdout (ETF 2022→, crypto 2024→) was evaluated once, after commit `frozen-pre-holdout`.
- **Multiple testing:** stationary-bootstrap CIs and p-values, Holm adjustment, and a deflated Sharpe ratio. The DSR uses the effective number of independent trials, estimated by clustering the return streams of all 200 trials (12 effective ETF, 9 crypto). I also ran a White/Hansen reality check vs cash and vs the passive benchmark.
- **Stress tests:** 2× and 3× costs, +5 bp slippage, one extra bar of delay, and 5% of bars randomly missing.
- **Gate** (all must hold): WF Sharpe ≥ 0.4, Sharpe CI lower bound > 0, DSR ≥ 0.90, Sharpe at 2× cost ≥ 0.2, max DD ≥ −35%, ≥ 30 trades, beats the SPY/BTC Sharpe or is a low-correlation diversifier, and holdout Sharpe ≥ 0.

## 5. Results (Phase 5) — full leaderboard

Excess-of-cash Sharpe, net of costs. WF-OOS = ETF 2008–2021, crypto spot 2019-07–2023, perps 2021–2023. Holdout = ETF 2022–2026-10, crypto 2024–2026-10. Full metrics per strategy (Sortino, Calmar, VaR/ES, profit factor, expectancy, exposure, regimes, yearly) are in `reports/results/*.json` and in the dashboard.

| Strategy | Family | WF Sharpe [95% CI] | WF CAGR | WF MaxDD | DSR | SR @2× cost | Cost/gross | Holdout SR | Holdout CAGR | Gate |
|---|---|---|---|---|---|---|---|---|---|---|
| rotation_filtered_etf | momentum | 0.80 [0.39, 1.28] | 11.0% | −22% | 0.91 | 0.76 | 5% | 0.16 | 5.2% | PASS |
| vix_regime_spy | volatility | 0.82 [0.30, 1.32] | 9.9% | −24% | 0.92 | 0.73 | 9% | 0.10 | 4.3% | PASS |
| xsmom_volfilter_crypto | momentum | 1.39 [0.36, 2.44] | 111% | −75% | 0.91 | 1.31 | 5% | 0.41 | 8.2% | FAIL (DD) |
| volmanaged_spy | volatility | 0.60 [0.16, 1.08] | 6.2% | −18% | 0.72 | 0.60 | 1% | 0.46 | 8.4% | FAIL (DSR) |
| riskparity_etf | volatility | 0.61 [0.08, 1.18] | 4.2% | −20% | 0.72 | 0.60 | 1% | 0.06 | 4.1% | FAIL |
| xsmom_multi (dual momentum) | momentum | 0.55 [0.08, 1.03] | 7.7% | −27% | 0.65 | 0.53 | 4% | 0.29 | 7.1% | FAIL |
| xsmom_sectors | momentum | 0.48 [0.07, 0.94] | 8.2% | −36% | 0.55 | 0.47 | 3% | 0.24 | 6.8% | FAIL |
| xsmom_crypto | momentum | 1.02 [0.01, 2.02] | 63% | −80% | 0.74 | 0.95 | 7% | 0.10 | −10.6% | FAIL |
| ml_regime_spy (logistic) | ML | 0.43 [−0.05, 1.03] | 4.6% | −29% | 0.47 | 0.41 | 2% | 0.50 | 11.6% | FAIL |
| ml_lgbm_etf | ML | 0.38 [0.01, 0.84] | 5.2% | −29% | 0.41 | 0.36 | 6% | 0.24 | 6.5% | FAIL |
| breakout_etf | trend | 0.37 [−0.06, 0.82] | 3.9% | −25% | 0.39 | 0.31 | 12% | −0.07 | 2.4% | FAIL |
| ml_lgbm_crypto | ML | 0.79 [−0.27, 1.89] | 36% | −82% | 0.57 | 0.71 | 10% | 0.18 | −3.8% | FAIL |
| rsi2_etf | mean rev. | 0.29 [−0.14, 0.84] | 3.1% | −29% | 0.28 | 0.18 | 24% | 0.60 | 8.5% | FAIL |
| xsrev_sectors | mean rev. | 0.25 [−0.26, 0.76] | 2.3% | −25% | 0.23 | 0.17 | 20% | −0.99 | −6.2% | FAIL |
| pairs_etf (cointegration) | stat arb | 0.20 [−0.25, 0.65] | 1.1% | −12% | 0.18 | 0.02 | 35% | 0.40 | 6.7% | FAIL |
| xsmom_countries | momentum | 0.12 [−0.28, 0.58] | 1.0% | −42% | 0.12 | 0.11 | 7% | 0.48 | 10.4% | FAIL |
| ewmac_etf | trend | 0.10 [−0.30, 0.49] | 1.0% | −21% | 0.10 | −0.00 | 42% | −0.20 | 1.1% | FAIL |
| tsmom_etf | trend | 0.04 [−0.43, 0.53] | 0.3% | −35% | 0.07 | −0.05 | 53% | −0.07 | 2.3% | FAIL |
| ml_ridge_etf | ML | 0.15 [−0.30, 0.67] | 1.5% | −53% | 0.13 | 0.12 | 12% | 0.19 | 5.7% | FAIL |
| rsi2_crypto | mean rev. | 0.49 [−0.26, 0.96] | 17.6% | −45% | 0.25 | 0.42 | 13% | 0.41 | 7.0% | FAIL |
| ml_ridge_crypto | ML | 0.21 [−0.72, 1.14] | −4.0% | −84% | 0.14 | 0.13 | 28% | 0.02 | −13.8% | FAIL |
| zrev_etf | mean rev. | −0.22 [−0.63, 0.22] | −0.9% | −25% | 0.01 | −0.39 | >100% | −0.31 | 1.5% | FAIL |
| funding_carry (crypto) | stat arb | 0.33 [−0.95, 1.52] | 0.0% | −0.2% | 0.17 | −0.63 | 80% | 3.08 | 1.2% | FAIL |
| ewmac_crypto | trend | 0.35 [−0.98, 1.52] | 3.8% | −21% | 0.18 | 0.32 | 9% | 0.45 | 6.7% | FAIL |
| tsmom_crypto | trend | −0.02 [−0.96, 0.94] | −2.5% | −37% | 0.06 | −0.08 | >100% | 0.30 | 4.6% | FAIL |
| breakout_crypto | trend | 0.04 [−1.15, 1.17] | −1.1% | −32% | 0.07 | −0.00 | 52% | 0.29 | 4.3% | FAIL |
| pairs_crypto | stat arb | −0.61 [−1.45, 0.43] | −7.6% | −30% | 0.01 | −0.71 | – | −0.59 | 0.0% | FAIL |
| xsrev_crypto | mean rev. | NO TRADE every year (no parameter set had a positive training Sharpe) | – | – | – | – | – | – | – | FAIL |

Benchmarks over the ETF WF-OOS window: SPY Sharpe 0.59, CAGR 11.0%, max DD −52%; 60/40 Sharpe 0.78, CAGR 8.9%, max DD −31%. In the holdout: SPY 0.50 / 11.6%, 60/40 0.27 / 6.4%, cash 3.9%/yr. BTC buy-and-hold Sharpe was 0.80 (spot WF window) and 0.69 in the holdout, with a −53% drawdown.

Reality check (best-of-all vs benchmark): ETF vs cash p = 0.004, **ETF vs SPY p = 0.95**. Crypto vs cash p = 0.05, crypto vs BTC p = 0.23.

## 6. Portfolio (Phase 6)

Only the two gate-passing strategies were eligible. Their daily correlation is 0.53, because both are equity/bond regime timers, so diversification is limited. A walk-forward inverse-vol combination:

| | CAGR | Vol | Sharpe (excess) | Max DD |
|---|---|---|---|---|
| WF-OOS 2008–2021 | 10.9% | 10.9% | 0.96 | −17.5% |
| Holdout 2022–2026 | 4.9% | 11.2% | 0.14 | −17.3% |

Crypto strategies were excluded because none passed. Zero allocation was allowed, and for crypto it is the outcome.

## 7. Capital & passive-income feasibility (Phase 7)

The simulation trades integer shares with IBKR-like fees (USD 0.005/share, USD 1 minimum, 2 bp FX conversion) in a EUR account with unhedged USD exposure, 2008-01 to 2026-10. The 2008–2026 EUR CAGR includes a currency tailwind: EUR/USD fell from about 1.47 to about 1.1. Taxes are not modelled.

| Start capital | EUR CAGR (realised sim.) | Fees + slippage, % of avg equity/yr | Drag vs frictionless |
|---|---|---|---|
| €1,000 | 1.1% | 8.0% | 9.6%/yr — **not viable** |
| €5,000 | 8.5% | 2.4% | 2.3%/yr |
| €10,000 | 9.5% | 1.8% | 1.3%/yr |
| €25,000–100,000 | 9.9–10.0% | ~1.5% | ~0.9%/yr |

Withdrawals from €100k over 20 years, inflation-indexed. "Depletion" means real equity falls below 50% of the start at any point.

| Withdrawal (monthly at start) | P(depletion), bootstrap of all OOS 2008–2026 | P(depletion), bootstrap of 2022–2026 holdout only | 60/40 benchmark (all) |
|---|---|---|---|
| 2% (€167) | 0.2% | 14% | 0.3% |
| 3% (€250) | 1.1% | 27% | 0.8% |
| 4% (€333) | 2.6% | 45% | 2.9% |
| 6% (€500) | 14% | 81% | 15% |

Interpretation:
- *Realised historical growth* (~10%/yr in EUR on the simulated path) is not the same as *expected return*. The 10-year median bootstrap CAGR is 10.1% on the full window but **4.6% on the holdout regime** (5th percentile −1.0%).
- For income, the strategies offered nothing a passive 60/40 did not.
- Meaningful income takes large capital even with optimistic assumptions. €1,000/month at a 3–4% withdrawal rate needs roughly €300–400k. On the recent-regime evidence, even 3% carries a material risk of depletion.
- Leverage was not used to hit an income target.

## 8. Paper trading & risk (Phases 8–9)

- The paper engine (`qrs/paper`) runs feed → validation → strategy proposal → **independent risk manager** → simulated broker (next-open fills, spread, slippage, minimum fees, integer lots, volume cap) → SQLite journal, with crash recovery.
- The broker rejects any order set without a valid risk-manager signature, so strategies cannot bypass the controls.
- The risk manager enforces position, gross, net, leverage, group and ex-ante volatility caps. A daily loss switches to reduce-only; a drawdown breach, stale feed, three consecutive critical errors or the kill switch triggers a HALT.
- Real-money trading is hard-disabled (`LIVE_TRADING_ENABLED = False`). No credentials are read anywhere.
- A one-year historical replay (2025-11-03 → 2026-10-30) of both strategies reproduced the backtest with daily ρ 0.995/0.999 and 1.1–1.5% annualised tracking error. Over that year `vix_regime_spy` returned −3.5% and `rotation_filtered_etf` +1.7% (simulated).
- Live feeds (Binance REST) are implemented but untested here, because the sandbox blocks them.

## 9. Answers to the required questions

1. **Best markets under realistic testing:** US-listed multi-asset ETFs, and only for low-turnover equity/bond regime timing. Crypto produced the highest raw returns but with unacceptable 75–84% drawdowns and no holdout outperformance vs BTC.
2. **Strongest evidence of an edge:** regime-filtered rotation and VIX-regime switching; vol-managed equity came next. All of these are risk-reduction rules, not alpha. Their pre-2022 evidence (CI lower bound > 0, DSR ≈ 0.91) faded in the holdout.
3. **Failed validation:** time-series momentum, Donchian breakout and EWMAC trend in ETFs and crypto; RSI(2), vol-adjusted and cross-sectional short-term reversal; cointegration pairs (ETF and crypto); country momentum; ridge and LightGBM ranking; the logistic regime model; crypto momentum (drawdowns); crypto funding carry (inactive in the walk-forward period).
4. **Profitable after costs?** The two passers keep >90% of gross profit after costs, and their Sharpe drops by only 0.04–0.09 at 2× costs, so costs are not their problem. Costs are what destroyed trend following and reversal: costs consumed 42–53% of gross profit for EWMAC/TSMOM ETF and >100% for zrev.
5. **Stable across periods?** No. Both passers dropped from Sharpe ~0.8 (2008–2021) to 0.10–0.16 (2022–2026). Most of their advantage came from avoiding 2008 and from calm-market regimes (Sharpe >3 when VIX < 15, negative when VIX > 25).
6. **Drawdown and risk:** WF max drawdowns of −22% and −24%, holdout −17% and −21%; daily 95% ES about −2%. Crypto strategies saw −45% to −84%.
7. **Vs passive benchmarks:** better than SPY on risk-adjusted terms pre-2022 (lower drawdown), worse in raw return, and roughly equal to a 60/40 portfolio. In the holdout they were worse than SPY and 60/40, and only slightly better than cash.
8. **Capital for meaningful income:** €25k is the minimum for fees to be negligible (below €5k, fixed fees dominate). For about €1,000/month you would need €300–400k at withdrawal rates that, on recent evidence, still risk depletion. That is no different from passive investing.
9. **Evidence still missing:**
   - Contract-level futures data (CME/ICE via paid vendors such as Norgate, CSI or Databento) to test trend following without ETF contango and with proper rolls.
   - Intraday and order-book data for execution-sensitive strategies.
   - Point-in-time single-stock data with delistings (CRSP/Compustat, paid) for equity factor research.
   - Actual quoted spreads, rather than assumed ones.
   - UCITS ETF price histories for the EU-accessible implementation.
   - Live forward paper-trading results.
   - A crypto funding-carry test with a longer pre-registered forward period. Its holdout result (Sharpe 3.1, CI lower bound 0.54, but tiny exposure and 1.2% CAGR) is a *hypothesis* generated after seeing the holdout, not evidence.
10. **Continue paper trading?** Yes, but only as a forward test of the infrastructure and of the two regime rules at negligible stakes. Pre-register a re-evaluation after 12 months. The evidence does **not** justify real capital, and these rules should be benchmarked against a passive 60/40 portfolio, which they currently do not beat.

## 10. Reproduce

```
python -m scripts.ingest                    # download + validate data (≈4 min)
python -m qrs.research.run_all              # pre-holdout research (holdout masked)
python -m qrs.research.run_all --holdout    # one-time holdout evaluation (logged in trial_ledger.csv)
python -m scripts.portfolio_capital         # portfolio + capital/withdrawal analysis
python -m scripts.paper replay --strategy vix_regime_spy --start 2025-11-03 --fresh
pytest                                      # 46 tests incl. look-ahead truncation tests on real data
```
