# Wiki chart

One writer uses a persistent volume and Recreate updates. Do not scale the deployment or share its volume between installations.

Create a bootstrap Secret containing a strong random value under the token key. Install with:

```sh
helm upgrade --install docs ./charts/wiki \
  --set bootstrapSecret=wiki-bootstrap \
  --set publicURL=https://wiki.example.com \
  --set ingress.enabled=true \
  --set ingress.host=wiki.example.com
```

Use the bootstrap token once to create the first administrator. Configure ingress.className, ingress.annotations and ingress.tls for your ingress controller and certificate issuer. Set visibility to private to require login for reading.

Git synchronization is optional. Configure git.repository, git.branch and optionally git.sshSecret. The SSH Secret contains id_ed25519 and known_hosts. Secrets are mounted as files.

The PVC is retained on uninstall. Use persistence.existingClaim when restoring an existing volume. Back up the entire volume, including local repository, publication state, pending Git synchronization, accounts and uploads. The remote repository alone is not a complete backup.

Fleet can consume this chart from source or its released OCI artifact. CI produces versioned artifacts; Fleet deploys a pinned version with instance values and Secret references.

## Site configuration and migration

Set `contentPrefix: wiki/content` when restoring the previous Socrat repository layout. The default for new installations is `content`. Restore the complete volume into a new PVC and configure `persistence.existingClaim`; never mount a live writer volume in two deployments.

`config` becomes `/config/wiki.yaml`. It supports runtime settings such as `git.author` and `git.email`. The chart's explicit URL, visibility, content prefix, Git repository/branch and bootstrap Secret settings take precedence over the corresponding file settings. Do not put secrets in this ConfigMap.

`siteConfig` is an optional complete Hugo TOML file mounted at `/opt/wiki/hugo.toml`. For example:

```yaml
publicURL: https://wiki.example.com/docs
contentPrefix: content
config:
  git:
    author: Documentation team
    email: docs@example.com
siteConfig: |
  _merge = 'deep'
  title = 'Team wiki'
  defaultContentLanguage = 'en'
  [[module.imports]]
  path = 'github.com/alchemmist/hugo-docs'
  [params.docs]
  brand = 'Team wiki'
  logo = 'team-logo.svg'
  footer = ''
  [params.docs.editor]
  enabled = true
```

The runtime supplies the canonical base URL to Hugo. Health checks always use `/healthz`, including installations under `/docs`. Configuration changes restart the single writer; accepted content stays on the volume.

Package custom assets in a derived image. No public URL or secret is needed at build time:

```dockerfile
FROM ghcr.io/alchemmist/hugo-docs-wiki:0.2.8
COPY --chown=1000:1000 team-logo.svg /opt/wiki/static/team-logo.svg
```

Build and publish that image, then pin `image.repository` and `image.digest` in deployment values. The same approach can add approved theme overrides under `/opt/wiki/layouts` or `/opt/wiki/assets`. Browser editor plugins require the source build workflow so they are compiled into the editor bundle; copying plugin source into a running container does not activate it.

For Compose, mount a config file read-only at `/config/wiki.yaml`. Use an additional Compose file with a bind mount to `/opt/wiki/hugo.toml` for a custom Hugo configuration, or use a derived image for logos/assets. Bootstrap token retrieval is `docker compose -f compose.wiki.yaml exec wiki cat /data/bootstrap-token`.

Small text assets, including SVG logos and favicons, can use `staticFiles` without building a custom image:

```yaml
staticFiles:
  images/team.svg: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><circle cx="8" cy="8" r="7"/></svg>'
```

Set `params.docs.logo = 'images/team.svg'` in `siteConfig`. Each file is mounted separately below `/opt/wiki/static` using a read-only subPath bind. This avoids ConfigMap directory symlinks, which Hugo does not publish; module-provided static assets remain available. Paths must be relative, with no hidden components, `..`, backslashes or empty segments. Values must be UTF-8 text. Keep the total under Kubernetes' 1 MiB ConfigMap limit. Binary assets can use `staticBinaryFiles` with the same safe paths and base64-encoded values; they are projected through ConfigMap `binaryData` with the same per-file mounts. A path cannot appear in both maps. Use a custom image for larger assets and compiled plugins. Static asset changes trigger a rollout.
