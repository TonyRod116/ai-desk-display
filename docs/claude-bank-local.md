# Saved Claude resets in the local clock

The bar and countdown come from the existing official quota reader. The small
hearts count saved resets: they do not count natural renewals or reset purchases.

The ordinary native Claude quota response omits the bank. The account's
first-party usage GET must opt in with `?cedar_ember=1`. The locally written Arc
extension reads `/api/account`, the pinned organization's usage, then the account
again. It refuses any identity change. It never sends a model prompt, buys or
redeems a reset, reads browser cookies, or exports credentials. See the
[Claude limit-reset explanation](https://support.claude.com/en/articles/17007452-what-is-a-limit-reset)
for the distinction between saved resets and renewal dates.

## Install privately

The source is `integrations/claude-bank`. Prepare a private copy with
`scripts/prepare_claude_bank.py --config <private-config> --pin <verified-pin>
--destination <private-folder>`. The pin is private account metadata from an
authorized, identity-verified observation; never derive it from another browser
profile. Preparation does not enable network traffic. Neither `pairing.js` nor
the account pin belongs in Git. The public manifest key only fixes the extension
ID; the separate random pairing secret authenticates its local requests.

In Arc's extensions page, enable developer mode and load the prepared folder as
an unpacked extension. Enable `automatic_claude_resets: true` in the private local
config and restart only the clock monitor. Arc must be running and signed in to
the pinned account; no Usage tab, Console, terminal or chat with Codex needs to
stay open. The optional [private Windows launcher](windows-startup-local.md)
starts the clock and opens Arc at Windows login without changing Arc settings.
The collector reinstates its alarm on startup and after worker suspension.

It requests a single-use, 30-second challenge from the panel before querying
Claude. A stopped or disabled panel prevents provider queries. The extension has
only `alarms` and two host permissions (`claude.ai` and IPv4 localhost). Browser
host permissions cover the whole host; code restricts them to the three GETs and
`http://127.0.0.1:8787/display/claude-bank`. There are no content scripts, tab,
cookie, debugger or storage permissions, remote scripts, external messages or
analytics. Nothing goes to Token TV's author or another account.

## Freshness and failure

Successful observations arrive about once a minute. The local receiver requires
the paired extension origin and a private bearer secret, and checks the nonce,
identity before/after, organization, provider dates and every grant. Only
`resets_left` in started, unexpired, unpaused grants counts; `usable_now` is not
the saved balance. Malformed or missing bank data means unknown. A valid empty
or spent inventory means zero. Every observation is bound to source home,
expected identity and organization, with no fallback to a manual count.

The cache expires after 180 seconds or the earliest counted grant expiry. A
failed current read clears it immediately; a delayed failure cannot clear a new
read. Provider dates are bracketed by the two identity responses; grant expiry
is translated relative to those dates so a computer clock offset does not add
or remove saved resets. The display uses `?` for unknown, not empty hearts.
The panel applies the same expiry and refuses manual edits when automatic.
`/health` and local `doctor` report an unavailable automatic bank as degraded.
HTTP CORS is granted only to the paired origin on the one ingress route; existing
Host, loopback binding and dashboard origin checks remain in place.

If Claude changes the opt-in contract or Arc loses login/access, the bank becomes
unknown and retries. HTTP 429 backs off up to 15 minutes. Weekly quota remains
independent of Arc. No implementation can promise provider availability; missing
or old data must remain visible as missing instead of plausible numbers.

Validation: `python -B -m unittest discover -s tests` and
`node --test tests/test_claude_browser.mjs`. Use synthetic data for browser QA.
Actual bank changes, expiry, account identifiers and screenshots stay private.

The private extension has now delivered identity-verified observations in the
actual Arc installation. Both weekly quotas, both automatic bank sources, local
health and the five stored clock images have been checked together. A real PC
reboot is not part of this check; never reboot Windows or WSL as a test while
Sierra and the bots may be running.
