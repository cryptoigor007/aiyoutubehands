# Architecture — AI YouTube Hands

## Layers

1. **CLI** (`main.py`) — click commands, Russian user-facing output
2. **Config / Logging** — YAML + pydantic, structlog (or stdlib fallback)
3. **Token** — AES-256-GCM encrypted store (age-compatible workflow planned), audit, health
4. **Quota** — SQLite ledger + projection
5. **HTTP Client** — httpx, retries, circuit breaker, error mapping
6. **YouTube Service** — channel guard, dry-run, cost table
7. **Calendar** — SQLite + ASCII grid
8. **AI** — local stub by default; cloud only with explicit allow

## Safety

- No real YouTube mutations without explicit user permission and dry-run defaults
- Destructive paths reserved for future `--yes` flag (not all commands expose it yet)
- `expected_channel_id` checked on channel-bound service calls (exit 71 on mismatch)
- Quota enforced unless `force_quota=True`
- Secrets must never be committed (see `.gitignore`)

## Exit codes (selected)

| Code | Meaning |
|------|---------|
| 0 | OK |
| 2 | Usage |
| 10 | Auth |
| 20 | Config |
| 30 | Quota |
| 71 | Channel ID mismatch |
| 80 | Unsupported |
