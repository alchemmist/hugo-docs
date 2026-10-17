# Backup, recovery and migration

The persistent data volume is authoritative. A remote Git repository may lag successful local publication and does not contain local accounts, sessions or staged uploads. Do not restore a wiki by cloning the remote alone.

## What to preserve

With the default paths, preserve the complete `/data` directory:

| Path | Purpose |
| --- | --- |
| `repository/` | Accepted Markdown and local Git objects/history |
| `live/` | Publication snapshots, current pointer, pending Git sync state and runtime caches |
| `accounts.sqlite3` and any SQLite sidecars | Local users and sessions |
| `uploads/` | Staged attachment files and their ownership metadata |
| `bootstrap-token` | Initial administrator bootstrap secret |

Also preserve the deployment configuration, exact image digest, customized Hugo template, plugin source/build inputs, and external secret files using your protected backup system. These are not necessarily in the data volume. Browser-only drafts have not been accepted by the server and are not included.

## Consistent backup

Stop the application and every Git synchronization writer before copying the volume, or use an application-consistent storage snapshot. A copy of a running SQLite database and changing Git/publication state is not a reliable backup. The application shutdown stops its background worker; verify that the process has exited before copying.

For the supplied Compose project, the following creates a local tar archive without deleting the named volume:

```sh
mkdir -m 700 backup
make wiki-down
docker compose -f compose.wiki.yaml run -T --rm --no-deps \
  --user 0:0 --entrypoint python wiki -c \
  'import sys, tarfile; archive = tarfile.open(fileobj=sys.stdout.buffer, mode="w|"); archive.add("/data", arcname="data", recursive=True); archive.close()' \
  > backup/wiki-data.tar
chmod 600 backup/wiki-data.tar
docker compose -f compose.wiki.yaml up -d --no-build
```

Use this after the selected image has already been pulled or built; keep the same image version for the backup and restart. Retain the same Compose project name and volume configuration throughout; otherwise you may back up a new empty volume. The archive contains private data and credentials, so encrypt it before transferring it to untrusted storage. Tar preserves symbolic links; restoring under `/data` preserves the existing absolute publication pointer where present.

A successful command is only the beginning of verification. Record a checksum, restore into a separate volume, and test startup, login, accepted content, attachments and pending Git state. Use an isolated hostname and disable Git sync during the rehearsal so the restored copy cannot push into the production branch.

## Verified offline data bundles

`scripts/wiki-data.py` provides directory-based export, checksum verification and restore. It requires Python 3.11+ and Git. Stop all writers first, including Git sync, and run it against the mounted offline volume:

```sh
python3 scripts/wiki-data.py export --source /data --bundle /secure/wiki-backup --offline
python3 scripts/wiki-data.py verify --bundle /secure/wiki-backup
python3 scripts/wiki-data.py restore --bundle /secure/wiki-backup --destination /secure/restored-data
```

The bundle contains a manifest and the entire data directory, including accounts, uploads, local history and pending publication metadata. Export rejects dirty repositories, a HEAD different from the accepted publication, missing referenced commits, escaping links and a source that changes during the copy. Verify checks file inventory and SHA-256 checksums; restore refuses an existing destination and validates the copy before moving it into place. It does not contact the remote or modify Kubernetes.

Internal `/data/...` symlinks and absolute links under the actual `--source` directory become relative links. A custom `WIKI_DATA_DIR` can therefore be exported directly at its original mount path. If you first copy a custom-path volume somewhere else, preserve its original mount path during export or normalize its internal links on the offline copy before invoking the tool; arbitrary absolute symlinks are deliberately rejected. Restore into a new directory or an empty volume through an operator-controlled transfer, never on top of the active runtime.

`--offline` confirms that the operator stopped writers; it does not acquire a distributed lock. Protect bundles as credentials and encrypt them when transporting or storing outside trusted infrastructure. Checksums detect corruption, not replacement of both data and manifest. A rehearsal with the destination runtime remains necessary to verify version/schema compatibility.

## Restore and recovery

Restore only to a new, empty volume while the destination runtime is stopped. Extract trusted backup archives using a tool that prevents path traversal and unsafe links; the archive produced above contains the `data/` directory. Mount its restored contents at `/data`, preserving ownership and permissions. The default process needs UID/GID 1000 access. Do not extract over the live volume.

Start with the original image version and original site template first. Confirm the current snapshot and repository HEAD match the accepted publication, all referenced Git commits exist, and accounts can sign in. The runtime reconstructs rendered pages from accepted content on startup; retain publication metadata and Git history even if generated HTML could be rebuilt. Re-enable remote synchronization only after verifying queue compatibility and stopping the previous writer.

Do not manually reset the repository to the remote branch to clear a synchronization error. That can discard locally accepted content. Resolve the conflicting file against both the accepted local version and remote edits, using a backed-up copy first. Retain pending state until the change is confirmed remotely.

If every administrator credential is lost, preserve the volume before recovery. The bootstrap token is deliberately not a permanent backdoor into an initialized account database. This version has no dedicated offline administrator-reset command; use a tested operator recovery procedure or restore a known-good backup rather than deleting the account database on a running service.

## Moving an existing editable wiki

1. Rehearse on a copy. Pin the new image, preserve the site's content prefix and URLs, and package the old branding/rendering configuration into the new template. The default `runtime-site/` is neutral; it does not contain another installation's configuration.
2. Keep the old volume unchanged. Create new deployment resources and a new persistent claim; never attach two runtime writers to the old claim. Keep Git sync off on the rehearsal copy.
3. Verify existing front matter, rich content, image paths, aliases, navigation and shortcode templates. A previous static site may permit HTML that the runtime intentionally rejects during editing. Check YAML/TOML/JSON round trips and one content language per instance.
4. Test local account bootstrap and permissions. The runtime has no OIDC and does not trust a former reverse-proxy/WireGuard authorization bypass. Configure the canonical public URL and HTTPS before exposing login.
5. Freeze editing briefly, stop the old writer, and repeat backup/restore from the final accepted state. Record pending Git sync before starting the new runtime.
6. Switch routes only after startup and acceptance checks succeed. Preserve both public and private DNS/proxy routes if the site uses them. Enable one Git writer, then test immediate publication and eventual synchronization.
7. Retire old automation only after checking resource ownership and retention policies. Deleting an old GitOps installation may delete its volumes or shared resources unless explicitly protected.

For the previous Socrat runtime, the existing content prefix is `wiki/content`, not `content`. Set `CONTENT_PREFIX=wiki/content` in the migrated deployment; moving the directory without migrating local Git history and pending patch paths breaks compatibility. Back up both `/data/repository` and `/data/live`. The Socrat-specific cutover runbook remains in homelab. The generic backup utility described above ships with this distribution.

## Rollback and upgrades

Before any new write is accepted, rollback can switch routes back to the stopped old deployment and its retained volume, after stopping the new writer. Once the new runtime accepts writes, preserve and reconcile them before reopening the old installation. Merely switching the ingress at that point hides new content.

Keep a pre-upgrade backup and test upgrades on a restored copy. Do not assume an older binary can open an account database or publication format changed by a newer version. The published v0.2.2 image and chart provide pinned release versions; schema compatibility and a successful restore rehearsal still determine whether rollback is safe.
