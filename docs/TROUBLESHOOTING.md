# Troubleshooting

## GhostFix Says No AI Provider Is Configured

Use cloud mode:

```bash
ghostfix watch "your command" --fix --ai
```

Or create a custom model config:

```bash
ghostfix init
ghostfix watch "your command" --fix
```

## The Same Error Keeps Repeating

GhostFix limits repeated fixes with `fix.max_retries`.

Increase or decrease it in `ghostfix.config.py`:

```python
"fix": {
    "max_retries": 3,
}
```

## Patch Failed

Common causes:

- The model returned a malformed diff.
- The target file changed after context was gathered.
- The project is not a Git repository and the manual fallback could not parse the patch.

Try:

```bash
git status
ghostfix watch "your command" --fix --ai --verbose
```

## Wrong File Was Selected

Add ignored folders to `watch.ignore`, especially generated folders:

```python
"watch": {
    "ignore": ["node_modules", ".next", "dist", "build", "coverage"]
}
```

## Local Model Does Not Respond

Check the endpoint:

```bash
curl http://localhost:11434/api/tags
```

For OpenAI-compatible servers, confirm `/v1/chat/completions` exists.

## API Key Is Not Being Reused

This is intentional for `watch --ai`. GhostFix asks for provider/API key each run so a new terminal does not silently reuse an old saved Gemini/OpenAI/Claude key.

Use `ghostfix setup` only if you want to store global provider details for setup workflows.
