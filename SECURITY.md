# Security

Ollala AI OCR is designed for local use. Files selected in the web interface
are copied to a local `web_runs/` folder and processed by a local Ollama model.

## Reporting Issues

Please report security issues privately if possible. If private reporting is
not available, open a GitHub issue with minimal reproduction details and avoid
including sensitive documents.

## Local Data

The web interface can create temporary copies of input and output files under:

```text
web_runs/
```

`web_runs/` is ignored by Git. Use **Clear Inactive Runs** in the web UI or
delete the folder manually when you no longer need local working files.

## Network Exposure

The web server binds to:

```text
127.0.0.1:8765
```

Do not expose it to a public network unless you add authentication and review
the upload/download behavior.
