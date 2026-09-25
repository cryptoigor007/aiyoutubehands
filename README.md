# AI YouTube Hands

AI-first CLI for full control of a YouTube channel.

**Binary:** `ayh`  
**Package:** `aiyoutubehands`  
**Version:** see `VERSION`

## Quick start

```bash
make install
ayh --help
ayh doctor
```

## Safety

- No real YouTube mutations without explicit confirmation and `--yes`.
- Tokens encrypted with age.
- Channel ID checked on every request.
- Quota ledger enforced.

## Development

```bash
make check   # ruff + mypy --strict + pytest + version
```

See the Master Agent Charter for full specification.
