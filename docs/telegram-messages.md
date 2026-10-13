# StockWatch Telegram messages

StockWatch sends plain-text summaries with deterministic templates. Autobot formats
`/stockwatch` command replies; StockWatch formats durable notifications before
putting them in its existing outbox. No AI model is called.

## Daily overview

Illustrative values (not a live account report):

```text
StockWatch · Paper · Oct 12, 8:00 PM ET
Stocks: $1,025.00 · P/L +$25.00
Bitcoin: $990.00 · P/L −$10.00
Total profit/loss since setup: +$15.00
3 positions · 1 pending order
http://stockwatch.home.arpa/manual-paper
```

The existing configured daily schedule is retained (default 20:00 New York time).
Values come from the Stock and Bitcoin allocations, not the broker's $1 million
simulated account balance. P/L is since setup, including posted identifiable fees;
it is not a daily return. Missing or unreconciled allocation values are unavailable,
not zero. Snapshots older than five minutes are labeled stale. An Attention line
appears for account/service problems or uncertain orders. The dashboard address
requires access to the home network.

## Commands and alerts

- `/stockwatch` lists common read commands. `/stockwatch help orders` and
  `/stockwatch help systems` show complete syntax for those operations.
- Accounts/P&L show allocation values and observation time. Prices retain source
  and timestamp; Coinbase observations are distinct from Alpaca execution quotes.
- Positions, orders, fill updates, and system lists show at most five entries and
  indicate how many additional returned entries are in StockWatch. The underlying
  API's existing history limits still apply. Orders prioritize uncertain and active
  instructions and retain complete IDs for cancellation.
- Fill updates explicitly describe cumulative quantities. Alerts distinguish
  queued, partially filled, filled, rejected, and cancellation-requested states.
- Previews retain exact amounts, material terms, account identity, expiration,
  and applicable protection/system semantics. Incomplete, unsupported, or oversized
  previews do not get a confirmation button. Research-linked previews require the
  dashboard. Confirmation continues to use the exact original revision/token,
  bound to the authorized Telegram user and chat.
- Messages stay within a 3,900 UTF-16-unit budget. Lists omit whole entries with a
  details link; previews are never cut off. No JSON payloads are printed by the new
  templates. Pre-existing outbox messages are not rewritten or replayed.

No trading calculations, API schemas, database migrations, notification identities,
claim/ack behavior, or uncertain-send retry rules change. Formatting fixtures and
mocked command tests run without sending Telegram messages or placing orders.

## TinyLlama assessment — October 12, 2026

Read-only inspection of a1347-m found Ollama running, `tinyllama:latest` installed
(approximately 638 MB, Q4_0), and no model loaded in `/api/ps`. The machine reports
an Intel i5-4278U and approximately 8 GB RAM. Installation demonstrates availability,
not measured summarization accuracy or latency; no inference benchmark was run.

[TinyLlama's model card](https://huggingface.co/TinyLlama/TinyLlama-1.1B-Chat-v1.0)
describes a compact 1.1B conversational model. It could generate narrative wording,
but these messages already have known fields and a fixed purpose. Templates keep
numbers, statuses, and delivery independent of generated text. The selected approach
is templates only; it does not load TinyLlama or modify Ollama configuration.

A future, separately scoped experiment could compare narrative research summaries
against fixed examples. It would need factuality and latency evaluation before use,
and should remain separate from authoritative financial values and confirmations.
The deferred Mac Mini M4 research assistant remains separate from this change.

## Release

Deploy the StockWatch notification producer through its reviewed-release process
and Autobot through its Git-based deploy script; restart the existing note-bot
service after updating Autobot. Verify the installed revisions and service health.
No test message is required: inspect the next naturally occurring digest or command
reply. Roll back code using each repository's release procedure, preserving ledgers,
confirmation state, outbox status, and Telegram offsets.
