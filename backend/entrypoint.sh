#!/bin/sh
# Container entrypoint: migrate, then run whatever the image was asked to run.
#
# Schema ownership lives with Alembic (see the baseline_core_001 migration).
# The retry loop tolerates two containers racing on a first boot: the
# inspector-guarded migrations make the loser's second attempt a no-op.
# Set BEACON_RUN_MIGRATIONS=0 to skip (e.g. external migration management).
set -e

if [ "${BEACON_RUN_MIGRATIONS:-1}" != "0" ]; then
  attempt=0
  until alembic upgrade head; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 5 ]; then
      echo "entrypoint: alembic upgrade failed 5 times; aborting" >&2
      exit 1
    fi
    echo "entrypoint: alembic retry $attempt/5 in 5s" >&2
    sleep 5
  done
fi

exec "$@"
