#!/usr/bin/env bash
# my-harness installer for macOS and Linux.
#   curl -fsSL https://raw.githubusercontent.com/chanaza/my-harness/main/scripts/install.sh | bash
# Checks Python and Git, installs (or updates) the engine, then runs the guided setup.
# Installs CAPTURE only: nothing from your harness is loaded into your tools.
set -euo pipefail
ENGINE="${HARNESS_ENGINE_URL:-git+https://github.com/chanaza/my-harness}"

PYTHON=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 && \
     "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    PYTHON="$candidate"; break
  fi
done
if [ -z "$PYTHON" ]; then
  echo "Python 3.11 or newer is needed: https://www.python.org/downloads/ - then run this again."; exit 1
fi
if ! command -v git >/dev/null 2>&1; then
  echo "Git is needed: https://git-scm.com/downloads - then run this again."; exit 1
fi

echo "Installing my-harness..."
"$PYTHON" -m pip install --user --quiet --upgrade "$ENGINE"
# Interactive questions need the terminal even when this script is piped from curl.
exec "$PYTHON" -m harness setup "$@" < /dev/tty
