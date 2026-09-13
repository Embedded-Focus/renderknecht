#!/bin/sh
set -eu

if [ "${1:-}" = "render" ]; then
    shift
    exec python -m renderknecht.renderer_cli "$@"
fi

exec python -m flask --app renderknecht.web:create_app run --host=0.0.0.0
