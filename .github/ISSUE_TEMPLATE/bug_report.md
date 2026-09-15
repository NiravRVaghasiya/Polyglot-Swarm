---
name: Bug report
about: Report something that is broken
title: "[Bug] "
labels: bug
assignees: ""
---

## Describe the bug

A clear, concise description of what's wrong.

## Steps to reproduce

1. ...
2. ...
3. ...

## Expected behavior

What you expected to happen.

## Actual behavior

What actually happened. Include the full error message/traceback if there is
one (use a code block).

## Environment

- Polyglot Swarm version/commit:
- OS:
- Python version:
- Running via: Docker Compose / `pip install -e` / other (specify)
- LLM provider in use: Claude / Gemini / OpenAI / Ollama (local-only) / deterministic

## `polyglot health` output

Run `polyglot health` (or `python -m src.cli health`) and paste the output.
This is usually the fastest way to rule out a configuration problem.

```
paste output here
```

## Additional context

Anything else that would help — screenshots, logs (please redact API keys
and personal data), related issues.
