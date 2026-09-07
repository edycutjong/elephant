<div align="center">

# 🐘 Elephant Tracks

**The tape says balanced. The split says one desk and a crowd.**

Net flow is a sum, and summing is lossy. Elephant Tracks splits the tape back apart —
per-side ticket size and per-side wallet count, from real swaps.

[![CI](https://github.com/edycutjong/elephant-tracks/actions/workflows/ci.yml/badge.svg)](../../actions/workflows/ci.yml)
[![CodeQL](https://github.com/edycutjong/elephant-tracks/actions/workflows/codeql.yml/badge.svg)](../../actions/workflows/codeql.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-FFB020.svg)](LICENSE)
[![No API key required](https://img.shields.io/badge/API%20key-not%20required-4C9AFF.svg)](#run-it-in-30-seconds)

`Python 3.11` · `CoinMarketCap DEX API` · `keyless` · `zero dependencies`

</div>

---

## Run it in 30 seconds

No key. No signup. No install.

```bash
python3 scripts/split_tape.py
```

That is a live call to CoinMarketCap's keyless `/public-api` surface. Nothing here is a fixture.

---

## 💡 The problem

Every DEX flow tool reduces the tape to one signed number: buy volume minus sell volume.

That number **cannot** distinguish the two situations a trader most needs to tell apart:

| | net flow |
|---|---|
| One desk selling $27,000 clips to 4,000 people buying $180 clips | ≈ 0 |
| 4,000 matched trades of the same size | ≈ 0 |

Same number. Opposite market structures. One is distribution into retail; the other is churn.

## 🐘 The solution

**Summing is lossy and cannot be inverted.** You can always re-add a split back into a sum; nothing
recovers the split from the sum. So we never sum — we pull the individual swaps and measure each
side separately.

CoinMarketCap's `/v1/dex/tokens/transactions` returns, per swap: the **side** (`tp`), the **USD
value** (`v`), and the **maker address** (`ma`). That last field is what turns "one desk against a
crowd" from an inference into a **count**.

### Live output — UNI, captured from real swaps

```
HERO — rule: max ticket asymmetry among |net flow| < 5.0%
  UNI at 2.9x while net flow reads -1.6% — a dashboard calls this balanced
  25 buys  avg $8,358  from 15 wallets
  75 sells avg $2,875  from 52 wallets
```

Net flow reads **−1.6%**. Balanced, says every dashboard. The split says 15 wallets are buying at
nearly 3× the ticket size that 52 wallets are selling at.

**The hero row is chosen by a published rule** — highest ticket asymmetry among tokens whose net
flow is within ±5% — so it is a screen, not a cherry-pick.

---

## 🏗️ How it works

```
pull the swaps  →  split by side  →  count wallets + average tickets  →  rank by asymmetry
```

| Endpoint | Used for | Key? |
|---|---|---|
| `/public-api/v1/dex/tokens/transactions` | per-swap side, USD value, maker address | ❌ none |
| `/public-api/v4/dex/spot-pairs/latest` | universe enumeration | ❌ none |
| `/public-api/v4/dex/pairs/quotes/latest` | liquidity context | ❌ none |
| `/v1/dex/holders/count` | offline holder series (not on the demo path) | ✅ |

## 🏆 Why only CoinMarketCap

Most market-data APIs publish volume. Some publish trade count. **CMC publishes the individual
swaps with side, USD value and maker address together, keyless** — and the maker address is the
only reason the wallet count is available at all.

Remove CoinMarketCap and you would need a multi-chain swap indexer, a per-DEX pool registry, a
balance indexer, a wallet-labelling pipeline and a symbol→contract mapping service — five separate
systems — to recompute what one endpoint returns in one call.

## 🧪 Testing & CI

```bash
make lint    # ruff check + format
make test    # pytest + coverage
make demo    # the judged capability, live
make bench   # p50/p95
```

CI runs lint, tests, `pip-audit`, CodeQL, gitleaks — **and a `live-api` job that executes the real
split on every push.** It is keyless, so it runs on forks and PRs too. If CMC changes the contract,
it breaks in CI rather than in front of a judge.

## ⚠️ Honest limitations

- **The 24h aggregate fields are not used, deliberately.** `24h_buy_volume` / `24h_sell_volume`
  reconcile with `volume_24h` on only **6 of 200** pairs we sampled — 55 are off by more than 100×.
  This project computes from individual swaps instead. That finding is in `FEEDBACK.md`.
- **Swap windows are paginated at 100 per call**, so a run measures a recent window, not the full 24h.
- **Wallet counts are per-window** — a maker trading in two windows counts once in each.
- **`/v1/dex/holders/trend/list` is not available on the Startup plan**, so the holder series is
  collected daily by us instead.

## 📄 License

MIT — see [LICENSE](LICENSE).

## 🙏 Acknowledgments

Built for the **Build with CMC: API Hackathon**. Thank you to the CoinMarketCap team for exposing
per-swap maker addresses on a keyless endpoint — that single field is what made this measurable.
