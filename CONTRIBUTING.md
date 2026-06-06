# Contributing

Thanks for helping improve GhostFix.

## Development Setup

```bash
git clone https://github.com/Shibani987/ghostfix-ai.git
cd ghostfix-ai
python -m pip install -e ".[dev]"
python -m pytest
```

## Local Workflow

1. Create a branch for the change.
2. Keep changes focused.
3. Add or update tests when behavior changes.
4. Run `python -m pytest`.
5. Update docs if commands, config, provider behavior, or safety behavior changes.

## Code Style

- Prefer small, readable functions.
- Keep CLI behavior explicit and predictable.
- Avoid broad refactors in bug-fix PRs.
- Use structured parsing where possible.
- Keep patch application conservative.

## Documentation Style

- Use short sections.
- Include copy-pasteable commands.
- Call out safety and provider/API-key behavior clearly.
- Keep release docs accurate to the current code.

## Testing

Current tests focus on error parsing. When changing the repair loop, provider routing, or patching behavior, add focused tests around the changed contract.
