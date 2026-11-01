# Changelog

## Unreleased

- Separate interface, prose and code typography: custom UI fonts no longer replace Computer Modern Typewriter in inline/fenced code.
- Restore the blog's shared hugo-content prose sizing and code metrics, token line heights, padding and backgrounds on desktop and mobile.
- Add custom-UI-font regression coverage and Playwright checks for prose, inline code and syntax-highlighted blocks at five viewport widths.

- Match blog heading fragment marks: Computer Modern Typewriter, full-size hashes, opacity and hover treatment independent of the configured UI/code font.
- Keep native smooth fragment navigation and avoid doubled scroll offsets on desktop and mobile.
- Compact the sidebar brand/search spacing and extend the scrolling tree and its fade to the viewport's bottom edge, including the mobile drawer.
- Add reusable Playwright reading-layout checks for heading marks, fragment navigation and viewport-edge sidebar placement.

## 0.2.3

- Replace the account modal with a full `/admin` page and make `/login` use the same site typography and language.
- Support local custom monospace font families and four WOFF2 faces across navigation, controls and code.
- Reuse exact fingerprinted asset URLs on account pages while keeping private content protected.
- Support binary static assets in the Helm chart and preserve password-manager username associations.

## 0.2.2

- Build browser assets and Hugo templates on the native builder platform. This avoids the ARM64 Node/npm illegal-instruction crash under QEMU that stalled the previous multiarchitecture release.
- Limit release jobs to 20 minutes and retain architecture-specific final runtime images.
- Include the per-file ConfigMap mounts from 0.2.1 so Kubernetes logos and favicons are published by Hugo.

## 0.2.1

The source tag exists, but image and chart artifacts were not published: the release build was canceled after the ARM64 frontend crashed under QEMU. Use 0.2.2.

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
