# Wiki runtime

The optional runtime adds an inline editor and local accounts to the Hugo theme. Release [v0.2.8](https://github.com/alchemmist/hugo-docs/releases/tag/v0.2.8) provides the public image `ghcr.io/alchemmist/hugo-docs-wiki:0.2.8` and an OCI Helm chart. The regular static theme remains usable without the runtime or editor.

## Run locally

From the repository root, with Docker Compose installed:

```sh
docker compose -f compose.wiki.yaml up -d --no-build
```

This pulls the published image when it is not already present, starts one process on `127.0.0.1:8080`, and creates a persistent `wiki-data` volume. The image starts with the neutral `runtime-site/` template; normal publication uses its packaged Hugo templates.

For a source build or a customized template, run `make wiki-up` instead. This builds `runtime/Dockerfile` before starting the service; the initial build downloads pinned build dependencies.

Read the bootstrap token on the host:

```sh
docker compose -f compose.wiki.yaml exec wiki cat /data/bootstrap-token
```

Open `http://localhost:8080/login`, enter the token, and choose an administrator username and password. The token cannot create another administrator after the first account exists. There is no public signup, OIDC or SMTP dependency. Store the token privately, not in site content or Git.

Use `make wiki-logs` for logs and `make wiki-down` to stop. Do not run `docker compose down -v` unless you intend to delete the content and accounts.

To use another local port, set both the mapped port and canonical URL:

```sh
WIKI_PORT=8085 WIKI_URL=http://localhost:8085 docker compose -f compose.wiki.yaml up -d --no-build
```

## Accounts and permissions

Roles apply to the entire wiki:

| Role | Access |
| --- | --- |
| Reader | Published pages, search and published media |
| Editor | Reader access plus content and tree editing and publication |
| Administrator (`admin`) | Editor access plus creating, disabling, assigning roles and resetting passwords for users |

The account link opens the full `/admin` page with password changes and sign-out. Administrators also manage users there; anonymous visitors use `/login`. Usernames are case-insensitive and need not be email addresses. Passwords must contain at least eight characters and are stored as Argon2 hashes. Sessions are persisted in SQLite and expire after eight hours. Password reset, disabling an account and role changes revoke its sessions. The final enabled administrator cannot be disabled or demoted through user management.

Reading is public by default; local accounts are still required for editing. Start with `WIKI_PUBLIC=false docker compose -f compose.wiki.yaml up -d --no-build` to require login for reading too. The backend enforces access for content, search, media and API requests. A hidden editing button is not an access-control boundary.

Use HTTPS when exposing the service outside localhost. Configure a reverse proxy to send requests to port 8080 and set the exact external canonical URL. HTTPS URLs enable secure session cookies; mutation requests require the matching Origin and a CSRF token. The runtime does not accept the legacy Socrat/WireGuard authorization headers.

## Configuration and subpaths

Settings come from `/config/wiki.yaml` (or the path in `WIKI_CONFIG`), with environment variables taking precedence. Mount a configuration file through a Compose override when required:

```yaml
url: https://docs.example.org/docs
public: true
site: /opt/wiki
storage:
  path: /data
  content_prefix: content
auth:
  bootstrap_secret_file: /data/bootstrap-token
git:
  repository: ''
  branch: main
  author: Wiki
  email: wiki@example.org
```

Principal environment overrides are `PUBLIC_ORIGIN`, `WIKI_PUBLIC`, `WIKI_DATA_DIR`, `CONTENT_PREFIX`, `LIVE_TEMPLATE_DIR`, `WORK_DIR`, `LIVE_STATE_DIR`, `WIKI_BOOTSTRAP_SECRET_FILE`, `GIT_REPOSITORY`, `GIT_BRANCH`, `GIT_AUTHOR_NAME` and `GIT_AUTHOR_EMAIL`. The supplied Compose file sets several of these explicitly; change its override/environment rather than expecting the YAML file to override them.

For `/docs/` hosting, use `WIKI_URL=https://docs.example.org/docs` and preserve the prefix when forwarding requests. The runtime strips its configured prefix internally; the proxy must not strip it a second time. Links, editor APIs and session cookie paths use that prefix. `/healthz` is the runtime health endpoint.

Branding, language and rendering remain ordinary Hugo settings in `runtime-site/hugo.toml`. Change that template and rebuild the image for a customized installation. Keep executable templates and dependencies in the image; the runtime-managed content belongs on the volume. Set `defaultContentLanguage` to `en` or `ru` for the corresponding theme/editor/account interface. Login and account pages use that same site language. Runtime editing supports one content language per instance; normal static Hugo use is not restricted to that model.

Custom monospace fonts apply consistently to navigation, controls, code and account pages. Supply local WOFF2 files through the site or the chart's `staticBinaryFiles`, then configure:

```toml
[params.content.typography]
monoFamily = 'My Mono'
monoRegular = 'fonts/my-mono.regular.woff2'
monoBold = 'fonts/my-mono.bold.woff2'
monoItalic = 'fonts/my-mono.italic.woff2'
monoBoldItalic = 'fonts/my-mono.bold-italic.woff2'
```

Use content-hashed font filenames for immutable caching. The regular face is preloaded and account pages reuse the wiki's exact asset URLs. Serif article text and headings retain their existing typography.

## Editing and publication

The pencil enters a shared editing session across pages. Edit headings and body content in place; create, rename, move, reorder and delete notes or folders in the sidebar. Publish submits content and structural changes together. Successful publication exits editing. A rejected publication leaves browser drafts available for correction.

Browser drafts belong to the current site/user and browser session. They are not a backup and are not synchronized to another device before publication. Server publication validates revisions, builds Hugo output and switches the published snapshot atomically. A reload after successful publication serves the accepted content without waiting for Git or CI.

Markdown with YAML, TOML and JSON front matter is supported. Unknown metadata fields are retained; unchanged front matter preserves its source. The editor includes tables, tasks, images/media and rich nodes for math, Mermaid, alerts and footnotes. Unsupported constructs may appear as protected source blocks rather than an editable rendering. This is not arbitrary Hugo syntax editing: active HTML and unsafe URLs are rejected, and unknown shortcodes still need valid Hugo templates to build. Test representative content when importing a site.

The media picker stages uploads, which are included with the publication. The backend caps individual files at 8 MiB and accepts a fixed set of image, audio, video and PDF formats; the picker exposes a subset of those formats. HTML and SVG uploads are not accepted. Unpublished uploads belong to their uploader and are not public assets.

See [plugins](plugins.md) for the versioned editor extension API. Extensions are trusted owner-supplied code installed when building the image, including corresponding Hugo rendering templates. There is no plugin marketplace or runtime upload of executable plugins. Treat installing a plugin like changing the application code.

## Optional Git synchronization

Leave `git.repository` empty to operate entirely from the local volume. There is no remote sync worker in this mode. Local Git history remains part of the publication mechanism.

Set the remote repository and branch to enable background synchronization. For SSH, mount an identity and verified host keys as secret files and set `GIT_SSH_KEY` and `GIT_KNOWN_HOSTS`. The process uses strict host-key checking. Never put private keys, passwords or credential-bearing Git URLs into Hugo parameters or a public repository.

The remote branch must exist. Start with compatible content paths; a remote is not automatically a safe replacement for the initial volume contents. Publication succeeds locally before remote synchronization, so a Git outage does not block editing. Pending snapshots record the work to retry. Conflicting remote edits leave the queue pending instead of force-pushing. Inspect `/api/editor/sync` with an editor session and the runtime logs for sync state.

External edits should go through the remote workflow, not directly into the running managed checkout. Do not mount that checkout into an IDE or run another Git writer on it. Keep backups of the volume: accepted content may not yet exist on the remote.

## Operations

Run exactly one worker and one writable runtime replica for each volume. The image uses one Uvicorn worker; a filesystem lock prevents a second local writer. It is not a distributed multi-writer service. The image runs as UID/GID 1000, so bind-mounted storage and secret files must be readable/writable as appropriate by that identity.

The published chart is `oci://ghcr.io/alchemmist/charts/wiki`, version `0.2.8`; its source is in `charts/wiki/`. Download it with:

```sh
helm pull oci://ghcr.io/alchemmist/charts/wiki --version 0.2.8
```

Its deployment uses one replica and `Recreate`; pin an image digest for production, provide a bootstrap Secret with key `token`, and configure a persistent claim. Optional Git SSH Secrets contain `id_ed25519` and `known_hosts`. Test your configured release on a restored copy before upgrading an existing installation.

Back up the complete volume and site configuration before upgrades. See [backup, recovery and migration](migration.md). Check runtime health, publication errors, pending Git synchronization, storage usage and recoverability after every upgrade.
