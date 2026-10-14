COMPOSE ?= $(shell if docker compose version >/dev/null 2>&1; then printf "docker compose"; else printf "docker-compose"; fi)

.PHONY: build dev check up down logs

build:
	hugo --source exampleSite --destination ../public --minify --cleanDestinationDir

dev:
	hugo server --source exampleSite --bind 127.0.0.1 --port 1321 --buildDrafts --buildFuture

check:
	python3 tests/integration.py

up:
	$(COMPOSE) up --build -d

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f docs
