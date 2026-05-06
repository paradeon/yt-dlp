#!/usr/bin/env sh
_SCRIPT_DIR="$(dirname "$(realpath "$0")")"
_VENV_PYTHON="$_SCRIPT_DIR/.venv/bin/python3"
if [ -x "$_VENV_PYTHON" ]; then
    exec "$_VENV_PYTHON" -Werror -Xdev "$_SCRIPT_DIR/yt_dlp/__main__.py" "$@"
fi
exec "${PYTHON:-python3}" -Werror -Xdev "$_SCRIPT_DIR/yt_dlp/__main__.py" "$@"
