# Architecture — AI YouTube Hands

## Layers

1. **CLI** (`main.py`) — click commands, Russian user-facing output
2. **Config / Logging** — YAML + pydantic, structlog (or fallback)
3. **Token** — AES-GCM encrypted store, audit, health
4. **Quota** — SQLite ledger + projection
5. **HTTP Client** — httpx, retries, circuit breaker, error mapping
6. **YouTube Service** — channel guard, dry-run, cost table
7. **Calendar** — SQLite + ASCII grid
8. **AI** — local stub by default; cloud only with explicit allow

## Safety

- No real YouTube mutations without `--yes` and user confirmation
- `expected_channel_id` checked on every channel-bound call
- Quota enforced unless `--force-quota`
- Secrets never committed
