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
