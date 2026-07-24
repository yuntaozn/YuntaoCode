# Versioning

YuntaoCode separates the product release version from compatibility and
extension versions.

## Product Release Version

The single source of truth is `runtime/version.py`.

Change `__version__` there when preparing a release, then run:

```bash
python scripts/sync_release_version.py
```

The command synchronizes the release version into the desktop package
manifests, generated lockfile entries, and README version labels. Python package
metadata and the Runtime `/health` response read the source version directly.

To check for drift without modifying files:

```bash
python scripts/sync_release_version.py --check
```

CI runs this check on every pull request and push.

After a public tag is fixed, `main` may use a semantic pre-release version such
as `0.2.0-dev` to make the next development line explicit. Patch releases for a
published line should use normal release versions such as `0.1.1`.

## Source Update Detection

Before packaged desktop releases are available, source installations can check
for updates from Git remotes.

- The Runtime exposes `/updates/source` for read-only update detection.
- Detection compares `runtime/version.py` with the latest semantic Git tag
  found from the configured Git remotes, preferring Gitee and then GitHub.
- The web UI may show a lightweight update hint near the runtime status area.
- The Runtime does not modify its own source tree. It only reports status,
  release links, and suggested commands such as `git pull --ff-only`.
- If the working tree has local changes, the UI must warn the user before they
  run any update command.

Packaged desktop updates should remain a separate release concern, likely based
on signed Tauri updater artifacts.

## Independent Versions

The synchronization command intentionally does not modify:

- `schema_version` values for Task, Run, events, results, context, capability,
  checkpoints, or stored records;
- `settings_version`, which controls user-setting migrations;
- plugin manifest versions;
- frontend static asset cache versions;
- dependency versions.

These versions describe independent compatibility boundaries and change only
when their own contract changes.

## Release Checklist

1. Update `runtime/version.py`.
2. Run `python scripts/sync_release_version.py`.
3. Move relevant `CHANGELOG.md` entries from `Unreleased` into the release.
4. Run tests and builds.
5. Create the matching Git tag after the release commit is ready.
