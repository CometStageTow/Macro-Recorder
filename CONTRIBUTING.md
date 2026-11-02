# Contributing

1. Create a virtual environment and install dependencies:
   ```bash
   python -m venv .venv
   . .venv/bin/activate
   pip install -r requirements.txt
   pip install -e .
   ```

2. Run linting and tests:
   ```bash
   ruff check .
   pytest -q
   ```

3. Submit PRs with a clear description of changes and screenshots/GIFs when touching the UI.