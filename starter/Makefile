COMPOSE ?= $(shell if docker compose version >/dev/null 2>&1; then printf "docker compose"; else printf "docker-compose"; fi)

.PHONY: build dev up down logs

build:
	hugo --minify --cleanDestinationDir

dev:
	hugo server --bind 127.0.0.1 --port 1321

up:
	$(COMPOSE) up --build -d

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f docs
