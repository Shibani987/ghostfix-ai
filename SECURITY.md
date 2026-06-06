# Security

GhostFix sends error output and selected source snippets to the configured AI provider. Review your provider's data policy before using GhostFix on private or regulated code.

## Sensitive Data

Before running GhostFix, avoid printing secrets in command output. Error logs may include:

- API keys
- Database URLs
- Access tokens
- User data
- Internal file paths

If a command may print secrets, prefer a local model endpoint and sanitize logs where possible.

## API Keys

`ghostfix watch --fix --ai` asks for provider/API key on each run.

`ghostfix setup` can save a global provider/API key at:

```text
~/.ghostfix/config.json
```

Keep that file private.

## Patches

GhostFix can modify files. By default it asks before applying patches and creates backups. Avoid `--auto` on sensitive repositories unless you trust the configured model and have version control in place.

## Reporting Issues

If you find a security issue, do not open a public issue with exploit details. Contact the maintainers privately and include:

- Affected version
- Reproduction steps
- Impact
- Suggested mitigation, if known
