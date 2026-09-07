# Security Policy

## Reporting a vulnerability
Open a [private security advisory](../../security/advisories/new). Please do not open a public issue
for anything exploitable.

## Secrets posture
**This project ships no secrets, by design.** The judged code path uses CoinMarketCap's keyless
`/public-api` surface, so there is no API key in the repository, in CI, or in the deployment —
not hidden, simply not required.

The only credential in the wider workflow is a CoinMarketCap key used *offline* by the holder-count
collector, which lives in `~/.config/coinmarketcap/` and never enters this tree.

## Scanning
`gitleaks` on every push, CodeQL weekly and on PRs, `pip-audit` in CI, Dependabot weekly.
