.PHONY: pgbouncer_dev

pgbouncer_dev:
	docker rm -f pgbouncer 2>/dev/null || true
	mkdir -p ~/pgbouncer/config ~/pgbouncer/logs
	docker run -d \
		--name pgbouncer \
		--add-host=host.docker.internal:host-gateway \
		-p 6400:5432 \
		-e AUTH_TYPE=scram-sha-256 \
		-e DB_HOST=host.docker.internal \
		-e DB_PORT=$(DATABASE_PORT) \
		-e DB_USER=$(DATABASE_USER) \
		-e DB_PASSWORD=$(DATABASE_PASSWORD) \
		-e DB_NAME=$(DATABASE_NAME) \
		-e POOL_MODE=transaction \
		-e MAX_CLIENT_CONN=100 \
		-e DEFAULT_POOL_SIZE=20 \
		-v ~/pgbouncer/config:/etc/pgbouncer \
		-v ~/pgbouncer/logs:/var/log/pgbouncer \
		edoburu/pgbouncer:latest
