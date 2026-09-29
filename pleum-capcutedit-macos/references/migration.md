# Migration

Move only source, documentation, safe presets, configuration schemas, examples, and tests. Recreate `.venv`; do not copy `.env`, state, logs, caches, projects, media, audio, fonts, or machine paths. Run `scripts/migrate.py --from OLD --to NEW --dry-run`, then setup and doctor. Re-learn schema/style fixtures locally.
