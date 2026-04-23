# Contributing

Thanks for considering a contribution to Ollala AI OCR.

## Local Setup

```bash
git clone https://github.com/realanthonyc/ollala-ai-ocr.git
cd ollala-ai-ocr
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

PDF support requires Poppler:

```bash
brew install poppler
```

OCR requires Ollama and the model:

```bash
ollama pull glm-ocr
```

## Checks

Before opening a pull request, run:

```bash
PYTHONPYCACHEPREFIX=/tmp .venv/bin/python -m py_compile ocr_to_md.py local_web_app.py
.venv/bin/python ocr_to_md.py --help
```

If you change the web UI, also check:

```bash
node --check static/app.js
```

## Scope

Keep changes focused. This project is intentionally local-first and avoids
sending user documents to remote services.
