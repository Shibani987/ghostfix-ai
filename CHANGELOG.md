# Changelog

All notable changes to GhostFix will be documented here.

## 0.1.0

Initial release candidate.

### Added

- `ghostfix watch` command for running and monitoring shell commands.
- Error detection and stack trace parsing for Python, Node.js, Java, Go, Rust, Ruby, and generic CLI output.
- Context builder for source snippets, related files, and project tree context.
- AI provider routing for OpenAI, Claude, Gemini, and custom/local endpoints.
- Unified-diff patch application with backup support.
- Project config generation through `ghostfix init`.
- Global setup and masked config display commands.
- Release-ready documentation set.

### Changed

- `watch --ai` now asks for provider/API key on every run instead of silently reusing a saved provider.

### Known Limitations

- Patch quality depends on model quality and stack trace context.
- Manual patch fallback supports simple diffs only.
- Generic CLI error parsing is partial.
