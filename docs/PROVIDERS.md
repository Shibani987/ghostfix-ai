# Providers

GhostFix supports cloud providers and custom/local providers.

## Cloud Providers

Use `--ai`:

```bash
ghostfix watch "npm run dev" --fix --ai
```

Supported names:

| Provider | Flag |
| --- | --- |
| OpenAI | `--provider openai` |
| Claude | `--provider claude` |
| Gemini | `--provider gemini` |

When no provider is passed, GhostFix prompts you to choose one.

## OpenAI

```bash
ghostfix watch "pytest" --fix --ai --provider openai
```

Enter an OpenAI API key when prompted.

## Claude

```bash
ghostfix watch "python manage.py runserver" --fix --ai --provider claude
```

Enter an Anthropic API key when prompted.

## Gemini

```bash
ghostfix watch "npm run dev" --fix --ai --provider gemini
```

Enter a Google Gemini API key when prompted.

## Ollama

Create `ghostfix.config.py`:

```python
GHOSTFIX_CONFIG = {
    "model": {
        "type": "custom",
        "endpoint": "http://localhost:11434/api/chat",
        "model_name": "codellama:13b",
    }
}
```

Run without `--ai`:

```bash
ghostfix watch "python app.py" --fix
```

## LM Studio

```python
GHOSTFIX_CONFIG = {
    "model": {
        "type": "custom",
        "endpoint": "http://localhost:1234",
        "model_name": "local-model",
    }
}
```

## OpenAI-Compatible Servers

GhostFix calls:

```text
POST /v1/chat/completions
```

Expected response:

```json
{
  "choices": [
    {
      "message": {
        "content": "{\"root_cause\":\"...\",\"patch\":\"...\"}"
      }
    }
  ]
}
```

The model response content must be a JSON object with:

```json
{
  "root_cause": "short explanation",
  "explanation": "technical explanation",
  "fix_suggestion": "what to do",
  "patch": "unified diff or empty string",
  "confidence": 0.8,
  "related_files": []
}
```
