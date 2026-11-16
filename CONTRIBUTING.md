# Contributing

1. Fork and branch from `main`.
2. Set up: `pip install -r requirements.txt`, copy `.env.example` to `.env`.
3. Run tests before pushing: `python -m pytest tests/ -q` (must pass).
4. Keep money as `Decimal`/`Numeric` — never floats.
5. Never commit secrets, real inventory, supplier data, or customer PII.
6. Update `CHANGELOG.md` and relevant `docs/` files with your change.
7. Open a pull request describing the change and test results.
