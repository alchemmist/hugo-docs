# Changelog

## 0.2.1

- Mount chart-provided static files individually so Hugo publishes logos and other assets from Kubernetes ConfigMaps.
- Check projected-volume behavior with a real Hugo build and keep release image tags independent of earlier chart versions.

## 0.2.0

- Add an optional persistent wiki runtime alongside the static Hugo theme.
- Edit page content and navigation in one workspace and publish atomically without waiting for CI.
- Add local accounts, reader/editor/administrator roles, persistent sessions and public or private reading. OIDC is not included.
- Preserve YAML, TOML and JSON front matter and support rich content, staged attachments and build-time editor plugins.
- Package the runtime for Compose and Kubernetes with a single-writer Helm chart, optional Git synchronization and full-volume backup tooling.
- Support deployment subpaths and English/Russian interfaces.
- Fingerprint font assets through hugo-content 0.1.2 and preload the fonts used by text and navigation.
- Keep editor assets and API requests disabled for ordinary static theme consumers.
