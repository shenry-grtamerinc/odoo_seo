# Odoo SEO Bot — Dependencies & Setup (macOS)

This single file contains **everything you need** to install and configure the environment used for the MVP:
- Python + virtual environment
- Playwright (Python) + browser engines
- OpenAI Python SDK
- Environment variables (`.env`)
- Optional Google Sheets deps
- Sanity checks & troubleshooting

> ⚠️ This README intentionally **does not include app code**—only the dependencies and exact commands to reproduce the setup.

---

## 0) (Optional) Install Homebrew & Python

If `python3 --version` already shows **3.8+**, you can skip this section.

```bash
# Check your Python
python3 --version

# Install Homebrew (optional — handy for tooling). Skip if you have it.
#/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install/upgrade Python via Homebrew (optional)
#brew install python

```

1) Create & Activate a Virtual Environment

From your project folder (e.g., ~/seo_odoo_bot):

python3 -m venv venv
source venv/bin/activate


2) Upgrade pip
python3 -m pip install --upgrade pip

3) Install Python Packages
# Core
python3 -m pip install playwright
python3 -m pip install openai
python3 -m pip install python-dotenv

# Optional (only if/when you add Google Sheets later)
# python3 -m pip install gspread
# python3 -m pip install google-auth


4) Install Playwright Browsers (one-time)
playwright install

5) Configure Environment Variables

Create a .env file in your project root to store secrets & runtime knobs.

nano .env

Paste and edit:

# OpenAI
OPENAI_API_KEY=sk-REPLACE_ME

# Odoo (Steersman)
OD_URL=https://greatamerican.steersman.io/web/login
OD_EMAIL=REPLACE_ME
OD_PASS=REPLACE_ME

# Runtime
HEADLESS=false        # true|false (browser UI)
SLOWMO_MS=250         # ms to slow down actions for visibility
TEST_QUERY=Milwaukee 0240-20 3/8" Drill  # default product search text for MVP


6) Helper Files (create from Terminal)

# requirements.txt — pin core deps
cat > requirements.txt <<'REQ'
playwright>=1.46.0
python-dotenv>=1.0.1
openai>=1.40.0
# Optional (when you add Google Sheets):
# gspread>=6.0.0
# google-auth>=2.35.0
REQ

# .env.example — safe example env file
cat > .env.example <<'ENV'
OPENAI_API_KEY=sk-REPLACE_ME
OD_URL=https://greatamerican.steersman.io/web/login
OD_EMAIL=REPLACE_ME
OD_PASS=REPLACE_ME
HEADLESS=false
SLOWMO_MS=250
TEST_QUERY=Milwaukee 0240-20 3/8" Drill
ENV

# .gitignore — prevent secrets & venv commits
cat > .gitignore <<'GI'
.env
service_account.json
venv/
__pycache__/
*.pyc
*.pyo
*.log
test-results/
playwright-report/
GI

# setup_mac.sh — one-time env setup
cat > setup_mac.sh <<'SH'
#!/usr/bin/env bash
set -euo pipefail
python3 -m pip install --upgrade pip
if [ ! -d "venv" ]; then
  python3 -m venv venv
fi
# shellcheck disable=SC1091
source venv/bin/activate
if [ -f requirements.txt ]; then
  python3 -m pip install -r requirements.txt
else
  python3 -m pip install playwright openai python-dotenv
fi
playwright install
echo "✅ Setup complete. Copy .env.example to .env and fill values."
SH
chmod +x setup_mac.sh

# run_poc.sh — activate venv and run your script
cat > run_poc.sh <<'SH'
#!/usr/bin/env bash
set -euo pipefail
if [ -d "venv" ]; then
  # shellcheck disable=SC1091
  source venv/bin/activate
fi
python3 odoo_poc.py
SH
chmod +x run_poc.sh





