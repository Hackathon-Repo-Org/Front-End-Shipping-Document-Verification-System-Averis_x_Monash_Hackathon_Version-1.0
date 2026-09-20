#!/bin/sh
# One entrypoint, two roles. `serve` starts the API; anything else is a shipdoc
# subcommand. Keeping both in one image means the batch job and the web service can
# never drift apart in their dependencies, their config or their cache.
set -e
if [ "$1" = "serve" ]; then
  shift
  exec uvicorn shipdoc.adapters.api.app:app \
       --host 0.0.0.0 --port "${PORT:-8000}" \
       --proxy-headers --forwarded-allow-ips='*' "$@"
fi
exec shipdoc "$@"
