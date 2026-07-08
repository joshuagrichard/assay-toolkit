# Translational Assay Toolkit

Web app for running translational assay analysis tools in the browser.

## Setup

Requires **Python 3.10+** (3.12 recommended).

```bash
# Clone the repository
git clone https://github.com/joshuagrichard/assay-toolkit.git

# Enter the project directory
cd assay-toolkit

# Create a virtual environment (Python 3.10+)
python3.12 -m venv .venv

# Activate the virtual environment
source .venv/bin/activate

# Install dependencies
python -m pip install -r requirements.txt

# Start the web app
python -m uvicorn assay_platform.web_app:app --reload
```

Open http://127.0.0.1:8000

> If setup fails with `Path | None`, your venv is on Python < 3.10 — recreate it with 3.12.
