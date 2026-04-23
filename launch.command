#!/bin/zsh

set -u
unsetopt bg_nice 2>/dev/null || true

APP_URL="http://127.0.0.1:8765"
APP_DIR="${0:A:h}"
PYTHON_BIN="$APP_DIR/.venv/bin/python"
APP_FILE="$APP_DIR/local_web_app.py"
NO_OPEN="${OLLALA_NO_OPEN:-0}"

cd "$APP_DIR" || exit 1

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required to check whether the local web app is ready."
  exit 1
fi

if [ ! -x "$PYTHON_BIN" ]; then
  echo "Python virtual environment was not found at:"
  echo "$PYTHON_BIN"
  echo
  echo "Install the project dependencies first, then run this launcher again."
  exit 1
fi

if [ ! -f "$APP_FILE" ]; then
  echo "local_web_app.py was not found at:"
  echo "$APP_FILE"
  exit 1
fi

if curl -fsS "$APP_URL" >/dev/null 2>&1; then
  echo "Ollala AI OCR is already running."
  if [ "$NO_OPEN" != "1" ]; then
    open "$APP_URL"
  fi
  exit 0
fi

echo "Starting Ollala AI OCR..."
echo "Project folder: $APP_DIR"
echo "App URL: $APP_URL"
echo

"$PYTHON_BIN" "$APP_FILE" &
SERVER_PID=$!

cleanup() {
  if kill -0 "$SERVER_PID" >/dev/null 2>&1; then
    kill "$SERVER_PID" >/dev/null 2>&1
  fi
}

trap cleanup INT TERM

for _ in {1..60}; do
  if curl -fsS "$APP_URL" >/dev/null 2>&1; then
    echo
    echo "Ollala AI OCR is ready."
    if [ "$NO_OPEN" != "1" ]; then
      echo "Opening browser..."
      open "$APP_URL"
    fi
    wait "$SERVER_PID"
    exit $?
  fi

  if ! kill -0 "$SERVER_PID" >/dev/null 2>&1; then
    echo
    echo "The web app stopped before it became ready."
    wait "$SERVER_PID"
    exit $?
  fi

  sleep 1
done

echo
echo "The web app did not become ready within 60 seconds."
echo "Leaving the server process running so you can inspect the output above."
wait "$SERVER_PID"
