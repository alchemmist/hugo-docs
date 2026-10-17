PYTHON ?= python3

COMPOSE ?= $(shell if docker compose version >/dev/null 2>&1; then printf "docker compose"; else printf "docker-compose"; fi)

.PHONY: build dev check up down logs

build:
	hugo --source exampleSite --destination ../public --minify --cleanDestinationDir

dev:
	hugo server --source exampleSite --bind 127.0.0.1 --port 1321 --buildDrafts --buildFuture

check:
	$(PYTHON) tests/integration.py

up:
	$(COMPOSE) up --build -d

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f docs

.PHONY: wiki-build wiki-up wiki-down wiki-logs

wiki-build:
	$(COMPOSE) -f compose.wiki.yaml build

wiki-up:
	$(COMPOSE) -f compose.wiki.yaml up --build -d

wiki-down:
	$(COMPOSE) -f compose.wiki.yaml down

wiki-logs:
	$(COMPOSE) -f compose.wiki.yaml logs -f wiki

.PHONY: wiki-check

wiki-check:
	$(PYTHON) -m unittest discover -s runtime/tests -v
	npm test
	npm run build
