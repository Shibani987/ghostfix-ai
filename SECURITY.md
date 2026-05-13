# Security Policy

## Supported Versions

GhostFix is currently pre-1.0. Security fixes are applied to the latest public release branch.

## Reporting A Vulnerability

Please do not open a public issue for suspected vulnerabilities. Report privately to the project maintainer or repository owner with:

- A clear description of the issue.
- Steps to reproduce.
- Affected commands or files.
- Any logs or proof-of-concept details that are safe to share.

We will acknowledge reports as soon as possible and coordinate a fix before public disclosure.

## Safety Boundaries

GhostFix is a local developer tool. It is not a sandbox, malware scanner, dependency auditor, or production security monitor.

Important safety expectations:

- Review commands before running them through `ghostfix watch` or `ghostfix daemon start`.
- Review patches before accepting any auto-fix prompt.
- Do not run untrusted project code in a privileged shell.
- Keep `.env`, `.ghostfix/`, local model files, logs, reports, and backups out of public commits.
- Brain v4 output is advisory and cannot bypass safety policy.

## Privacy Defaults

- GhostFix does not upload code, logs, incidents, snippets, feedback, or exports by default.
- `.env`, secret-named files, private keys, local databases, `.ghostfix/`, `.ml/`, and model/checkpoint files are ignored or excluded from package builds by default.
- Training exports are created only by an explicit local command and redact emails, home paths, API keys, tokens, passwords, long secrets, env-style secret values, and private key blocks.
- Integration modules are stubs/hooks unless explicitly configured in future releases; they must not make network calls by default.
