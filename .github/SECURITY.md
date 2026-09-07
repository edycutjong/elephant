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

## The keyless claim is tested, not just asserted

`test_judged_path_requires_no_credential_at_all` unsets every CMC environment variable the project
could read and then runs the real fetch. If a key ever leaks into the judged path, that test is what
fails. A second test drives six malformed API responses through the parser and asserts each yields
no result rather than a plausible-looking number.

## Scanning
`gitleaks` on every push over full history, CodeQL weekly and on PRs, `pip-audit` in CI,
Dependabot monthly.
