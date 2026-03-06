#!/bin/sh
set -e
if [ -c /dev/stdin ] || [ -t 0 ]; then
    exec flask --app web run --host=0.0.0.0
else
    exec renderknecht "$@"
fi
