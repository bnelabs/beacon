## Summary

<!-- What does this change do, and why? Link any related issue. -->

## Checklist

- [ ] **Tests pass.** `python -m pytest backend/tests` (backend) and `npm test` in `frontend/` both pass locally, and new behavior is covered by tests.
- [ ] **No new synthetic / sample-data fallbacks.** Production paths must not silently substitute generated, random, or bundled sample data when a real data source fails. Fail loudly (or surface a visible degraded state) instead.
- [ ] **`torch.load` uses `weights_only=True`.** Every new or modified `torch.load(...)` call passes `weights_only=True` (or documents, in code, why the checkpoint genuinely requires arbitrary-object loading).
- [ ] **Migrations included for schema changes.** Any change to a SQLAlchemy model comes with an Alembic revision under `backend/alembic/`; no implicit `create_all`-only schema changes in production paths.
- [ ] **Metrics / observability for new background work.** New Celery tasks, pipeline stages, or long-running jobs emit structured logs and metrics (success/failure counters, duration) so failures are visible.

## Notes for reviewers

<!-- Anything reviewers should pay special attention to, follow-up work, screenshots, etc. -->
