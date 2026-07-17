#!/usr/bin/env sh
set -eu

MAX_RETRIES="${DB_MIGRATION_MAX_RETRIES:-20}"
RETRY_DELAY_SECONDS="${DB_MIGRATION_RETRY_DELAY_SECONDS:-3}"
export PYTHONPATH="/app:${PYTHONPATH:-}"

echo "[entrypoint] Applying database migrations..."
attempt=1
while :; do
	if alembic upgrade head; then
		echo "[entrypoint] Migrations applied successfully."
		break
	fi

	if [ "$attempt" -ge "$MAX_RETRIES" ]; then
		echo "[entrypoint] Migration failed after ${MAX_RETRIES} attempts. Exiting."
		exit 1
	fi

	echo "[entrypoint] Migration attempt ${attempt}/${MAX_RETRIES} failed. Retrying in ${RETRY_DELAY_SECONDS}s..."
	attempt=$((attempt + 1))
	sleep "$RETRY_DELAY_SECONDS"
done

echo "[entrypoint] Starting API..."
exec "$@"
