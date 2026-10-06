# Import the existing BMSTU archive

## Source and scope

The initial dataset comes from `backend/exports/andromeda_bmstu_2026_bundle/`, which already contains normalized JSONL, its source manifest, validation/reconciliation reports, and captured official files. The service importer does not import or call the crawlers, issue HTTP requests, or discover new source URLs. It reads the local directory or an operator-provided ZIP and computes hashes again.

The imported scope is BMSTU bachelor's admission 2026, Moscow head campus. Olympiad records and personal applicant rows were excluded at the user's request. Missing files and associations remain gaps; importing does not fill values from names or from another profile's curriculum plan.

## Offline validation and mapping

Run commands from `services/academic-data/`:

```powershell
uv sync --extra dev
uv run academic-data bundle validate `
  --input ..\..\backend\exports\andromeda_bmstu_2026_bundle `
  --output artifacts\bmstu-2026\validation-report.json

uv run academic-data bundle import `
  --input ..\..\backend\exports\andromeda_bmstu_2026_bundle `
  --dry-run `
  --output artifacts\bmstu-2026\mapping-report.json
```

Validation and dry-run do not open a database connection. Review their JSON reports before any commit. Keep these reports with the operator's release evidence; generated artifacts are not part of the service source tree.

## Persist an approved bundle

The target must be the separate `academic_data_2026` database on PostgreSQL 16. Provision the three roles and apply migrations using the [operations guide](operations.md). On the live VM, the locked system accounts connect to the same-named PostgreSQL roles through Unix-socket peer authentication. The importer does not need a password or network database address:

```sh
release=/opt/andromeda/academic-data/current
bundle=/var/www/bmstu2026/andromeda_bmstu_2026_bundle/andromeda_bmstu_2026_bundle.zip
sudo -u academic_data_importer env \
  ACADEMIC_DATA_ENV=production \
  ACADEMIC_DATA_DATABASE_URL=postgresql+psycopg:///academic_data_2026 \
  PYTHONPATH="$release/src" \
  "$release/.venv/bin/python" -m academic_data_service bundle import \
    --input "$bundle" --commit \
    --output /var/lib/andromeda/academic-data/reports/import-report.json
```

Use `--commit` only after the archive SHA-256, offline validation, dry-run mapping, target preflight, backup, and role checks pass. It validates and maps again, persists a batch, reconciles references and activates a release transactionally. The release key is deterministic from source bundle digest and mapper version. Repeating the same import is a no-op; a changed mapper or source digest creates a distinct immutable release. Do not run crawlers or fetch official pages as part of this operation.

If an import fails, inspect the sanitized report and structured logs by batch/request identifier. The active release must remain unchanged unless the new release completed reconciliation. Do not delete database rows to retry. Use the [operations guide](operations.md) for a forward retry or an explicit activation of an already committed release.

## Reconciliation meaning

Resolved relations are based on explicit external keys and source links. A null target plus an unresolved/manual-review status is an intentional preserved gap, not a failed guess. In particular, campaign offers without an exact profile key stay queryable; unavailable plans do not borrow another profile's file. Every published requirement node retains its operator and threshold (`AND`, `OR`, or `AT_LEAST`).

See [the release record](release-record-2026-10-03.md) for counts and limitations found in the verified production import. The machine-readable reconciliation report is [here](release-reconciliation-2026-10-03.json).
