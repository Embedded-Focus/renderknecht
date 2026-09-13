#!/bin/sh
set -e
if [ "${1:-}" = "render" ]; then
    shift
    exec renderknecht-render "$@"
else
    exec flask --app renderknecht.web:create_app run --host=0.0.0.0
fi
