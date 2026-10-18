# Alchemmist Docs

A Hugo documentation theme and an optional self-hosted wiki runtime with inline editing, local accounts, and persistent content. Both use Computer Modern typography, folder navigation, a page outline, and local full-text search. Built on [hugo-content](https://github.com/alchemmist/hugo-content).

Folders expand in the sidebar; only notes have pages. Search, breadcrumbs, and previous/next navigation follow the same model.

## Start an editable wiki

Release [v0.3.5](https://github.com/alchemmist/hugo-docs/releases/tag/v0.3.5) includes a public runtime image and Helm chart. With Docker Compose installed:

```sh
git clone --branch v0.3.5 https://github.com/alchemmist/hugo-docs.git
cd hugo-docs
docker compose -f compose.wiki.yaml up -d --no-build
```

This starts the published `ghcr.io/alchemmist/hugo-docs-wiki:0.3.5` image without a local build. To build your own image from this checkout instead, run `make wiki-up`.

Open <http://localhost:8080/login> and create the first administrator. Read the one-time bootstrap token locally:

```sh
docker compose -f compose.wiki.yaml exec wiki cat /data/bootstrap-token
```

Keep that token private. The default site is neutral, reading is public, editing requires a local account, and content persists in the `wiki-data` volume. No Git remote, Kubernetes or OIDC is required. Do not remove the volume when stopping the service.

Optional [MCP access](docs/mcp.md) lets agents read and publish notes as a local user. Enable it with `mcp.enabled: true` and create a personal token on `/admin`.

See [runtime configuration and accounts](docs/runtime.md), [backup and migration](docs/migration.md), and [editor plugins](docs/plugins.md). For a static site without a backend, use the workflow below.

## Start a documentation site

Requires Python 3 to generate the project, then Docker Compose to run it. Hugo and Go are only needed for the optional host workflow.

```sh
git clone https://github.com/alchemmist/hugo-docs.git
python3 hugo-docs/scripts/new_site.py my-docs --title "My documentation" --language en
cd my-docs
make up
```

Open <http://localhost:1320/>. Use `DOCS_PORT=1325 make up` to run another documentation site alongside it. The generator refuses to overwrite an existing destination.

The generated project contains its own content, configuration, Dockerfile, Compose file, and Makefile. It downloads the versioned theme as a Hugo module; it does not depend on the cloned theme directory. Commit that project to its own repository, public or private.

For live reload with Hugo 0.167.0+ and Go 1.23+ installed, use `make dev` and open <http://localhost:1321/>. Use `make build` for a static build in `public/`. Keep the generated `go.sum` in version control.

## Add the theme to an existing Hugo site

Initialize a Hugo module if your project does not already have `go.mod`:

```sh
hugo mod init example.com/my-docs
hugo mod get github.com/alchemmist/hugo-docs@v0.3.5
```

Configure `hugo.toml`:

```toml
_merge = 'deep'
baseURL = 'https://example.com/docs/'
title = 'My documentation'
defaultContentLanguage = 'en'

[[module.imports]]
path = 'github.com/alchemmist/hugo-docs'

[params.docs]
brand = 'My documentation'
logo = 'images/logo.svg'
footer = ''
noindex = true
```

Place your logo at `static/images/logo.svg`, or set `logo = ''` for a text-only brand. `brand` defaults to the site title; `footer` is hidden when empty. Interface translations are included for `en` and `ru`.

`_merge = 'deep'` opts into the theme's configuration, including folder-only sections, the search output, syntax highlighting, math delimiters, and raw HTML support. Hugo otherwise does not inherit all of these settings from modules. See [Hugo configuration merging](https://gohugo.io/configuration/introduction/#merge-configuration-settings). Site configuration can override theme settings.

The theme defaults to indexable output. The starter and demo explicitly set `noindex = true`; change it for a public site you want indexed. This controls robots metadata only, not authentication. Private static documentation needs access control at its hosting layer. The optional runtime can require local-account authentication for reading as well.

The supported installation is a Hugo module. The pinned `hugo-content` dependency supplies fonts and browser libraries automatically; no npm step is required.

## Content model

```text
content/
  _index.md
  engineering/
    _index.md
    idempotency.md
    reliability/
      _index.md
      timeouts.md
```

`_index.md` holds a folder title and optional `weight`. Do not put article text in it: folder pages are not rendered. The root `content/_index.md` is the exception and provides the home overview.

```yaml
---
title: Reliability
weight: 20
---
```

Write notes as ordinary `.md` files or leaf bundles (`note/index.md` with sibling images). Use `title`, `description`, and `weight` in front matter. New notes can be created with `hugo new content engineering/my-note.md`.

Use Hugo references rather than domain-root URLs to keep links working under subpaths:

```md
[Timeouts]({{< relref "engineering/reliability/timeouts.md" >}})
```

Only published notes and the home overview enter the search index. Drafts are excluded from production builds. The outline comes from Markdown headings. Search supports `Ctrl/⌘ K`, `/`, arrow keys, Enter, and Escape.

## Customize without editing the theme

Override templates by placing the same path in your site. Empty extension points are available at:

- `layouts/partials/docs/head-extra.html`
- `layouts/partials/docs/body-extra.html`

Put custom CSS in your site's `assets/` and load it through `head-extra.html`. Override individual strings in `i18n/en.toml` or `i18n/ru.toml`. Theme updates will not overwrite site files.

## Develop the theme

```sh
make build
make check
make dev
make up
```

`exampleSite/` uses a local module replacement pointing to this repository. `make build` renders the demo into `public/`; `make dev` provides live reload; `make up` builds and runs the demo container. `make check` builds independent English and Russian consumers under `/docs/` and checks navigation, search, branding, content isolation, local assets, and the starter generator.

The root contains the Hugo theme and runtime build configuration. `exampleSite/` contains the content specimen; `starter/` is the static-site scaffold; `runtime-site/` is the neutral editable-wiki template. `editor/` contains the browser editor and `runtime/` its Python backend. Static consumers need neither Python nor Node at serving time. Use `make wiki-check` for backend/editor checks after installing their development dependencies; `make wiki-build` builds the runtime image.

## Deployment

The starter's `make up` builds a multi-stage image and starts nginx. The service binds to `127.0.0.1:1320` by default; set `DOCS_PORT` to change the port. A reverse proxy can provide TLS and authentication. HTML is not cached; fingerprinted assets use immutable caching. Removed folder URLs and unknown paths return the custom 404 page.

For static hosting, upload `public/` after `make build`. Set `baseURL` to the full deployment URL, including any subpath. The theme works without runtime external requests.

## License

MIT. The bundled logo belongs to the Alchemmist identity; replace it for your own documentation. Fonts and browser libraries are provided by `hugo-content`, which includes their third-party license notices.
