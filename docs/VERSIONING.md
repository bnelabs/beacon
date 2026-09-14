# Versioning policy

BEACON versions the **platform**, not its parts: one SemVer sequence for the
whole repository (backend, frontend, schema migrations, API contract), because
the parts ship together in one Compose stack and one set of images.

## Rules

- **Version of record**: the root `VERSION` file, one line, `MAJOR.MINOR.PATCH`.
  `backend.__version__`, `/api/v1/system/status` and the frontend sidebar
  (`__APP_VERSION__`, stamped from `frontend/package.json`, which
  `scripts/release.py` keeps equal to `VERSION`) all derive from it. No other
  file may hard-code a platform version.
- **MAJOR** — breaking change to the public API contract (route removal or
  semantics), to the database schema in a non-upgradable direction, or to
  checkpoint/manifest compatibility.
- **MINOR** — new capability, endpoint, page or model module; backwards
  compatible migrations.
- **PATCH** — fixes, documentation, hygiene; no contract change.
- **Pre-release tags** (`-rc.1`) are allowed on release branches only.

## Changelog

`CHANGELOG.md` follows Keep a Changelog. Work lands under `[Unreleased]`;
`scripts/release.py <major|minor|patch>` moves that block under a dated
`[X.Y.Z]` heading, bumps `VERSION`, syncs `frontend/package.json`, and commits
atomically. `--tag` additionally creates the annotated git tag
(`vX.Y.Z`) locally; pushing tags is a maintainer act, never CI's.

## Guards

`scripts/check_versioning.py` (run by `.github/workflows/versioning-ci.yml`
on every push and PR) fails when:

1. `VERSION` is missing or not strict semver;
2. `frontend/package.json` disagrees with `VERSION`;
3. the top block of `CHANGELOG.md` is neither `[Unreleased]` nor the current
   `VERSION` (a release commit must move the block, not leave it stranded);
4. a platform version is hard-coded anywhere else (`grep`-based spot checks).

## What a version does NOT cover

- **Model artefacts**: checkpoints carry their own provenance —
  `ModelManifest` records code revision, resolved config, data attestation and
  snapshot id, plus a weight hash. A checkpoint's trust chain is its manifest,
  not the platform version.
- **Data**: dataset snapshots are content-addressed (`snapshot_id`); the
  point-in-time exposure store is vintaged by upload time.
- **The API inventory**: `docs/api-endpoints.md` is generated from the live
  app and guarded by `test_api_docs_current.py`; it drifts-proof itself.

## Release cadence

Releases are cut from `main` when a coherent body of work lands (typically a
merged PR cluster), not on a calendar. Until the first tagged release the
baseline is `[3.0.0]` (untagged, see CHANGELOG).
