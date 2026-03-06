#!/bin/sh
set -e
if [ "${1:-}" = "render" ]; then
    shift
    exec renderknecht "$@"
else
    exec flask --app web run --host=0.0.0.0
fi
