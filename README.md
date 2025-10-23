This single file contains everything you need to install and configure the environment used for **Phase 2 (Batch Automation & Concurrency)**:

- Python + virtual environment  
- Playwright (Python) + browser engines  
- OpenAI Python SDK  
- Environment variables (`.env`)  
- CSV/Google Sheets ingestion  
- Batch mode & concurrency (`MAX_CONCURRENT`, `BATCH_LIMIT`)  
- Sanity checks & troubleshooting  

!!! This README intentionally does not include app code—only the dependencies and exact commands to reproduce the setup.

---

## Install Homebrew & Python

If `python3 --version` already shows 3.8+, you can skip this section.

```bash
# Check your Python
python3 --version

# Install Homebrew (optional — handy for tooling). Skip if you have it.
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install/upgrade Python via Homebrew (optional)
brew install python
```

---

## 1) Create & Activate a Virtual Environment

From your project folder (e.g., `~/seo_odoo_bot`):

```bash
python3 -m venv venv
# shellcheck disable=SC1091
source venv/bin/activate
```

Upgrade pip:

```bash
python3 -m pip install --upgrade pip
```

---

## 2) Install Python Packages

### Core
```bash
python3 -m pip install playwright
python3 -m pip install openai
python3 -m pip install python-dotenv
python3 -m pip install tqdm
python3 -m pip install requests
```

### (when you add Google Sheets later)
```bash
python3 -m pip install gspread
python3 -m pip install google-auth
```

### Install Playwright Browsers (one-time)
```bash
playwright install
```

---

## 3) Configure Environment Variables

Create a `.env` file in your project root to store secrets & runtime knobs:

```bash
nano .env
```

Paste and edit:

```env
# OpenAI
OPENAI_API_KEY=sk-REPLACE_ME

# Odoo (Steersman)
OD_URL=https://greatamerican.steersman.io/web/login
OD_EMAIL=REPLACE_ME
OD_PASS=REPLACE_ME

# Runtime
HEADLESS=false            # true|false (browser UI)
SLOWMO_MS=200             # ms delay for visibility
MAX_CONCURRENT=2          # simultaneous browser windows
BATCH_LIMIT=20            # number of products per run (0 = all)
BATCH_CSV_PATH=August_2025_Product_Data.csv
# Optional Google Sheet export URL:
# BATCH_CSV_URL=https://docs.google.com/spreadsheets/d/.../export?format=csv&gid=...

TEST_QUERY=Milwaukee 0940-20 M18 FUEL™ Compact Vacuum
```

---

## 4) Helper Files (create from Terminal)

### `requirements.txt` — pin core deps
```bash
cat > requirements.txt <<'REQ'
playwright>=1.46.0
python-dotenv>=1.0.1
openai>=1.40.0
tqdm>=4.66.0
requests>=2.31.0

# Optional (when you add Google Sheets):
gspread>=6.0.0
google-auth>=2.35.0
REQ
```

### `.env.example` — safe example env file
```bash
cat > .env.example <<'ENV'
OPENAI_API_KEY=sk-REPLACE_ME
OD_URL=https://greatamerican.steersman.io/web/login
OD_EMAIL=REPLACE_ME
OD_PASS=REPLACE_ME
HEADLESS=false
SLOWMO_MS=200
MAX_CONCURRENT=2
BATCH_LIMIT=20
BATCH_CSV_PATH=August_2025_Product_Data.csv
ENV
```

### `.gitignore` — prevent secrets & venv commits
```bash
cat > .gitignore <<'GI'
.env
.DS_Store
batch_log.csv
August_2025_Product_Data.csv
service_account.json
venv/
__pycache__/
*.pyc
*.pyo
*.log
test-results/
playwright-report/
GI
```

### `setup_mac.sh` — one-time env setup
```bash
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
  python3 -m pip install playwright openai python-dotenv tqdm requests
fi

playwright install
echo "✅ Setup complete. Copy .env.example to .env and fill values."
SH
chmod +x setup_mac.sh
```

### `run_batch.sh` — activate venv and run your batch script
```bash
cat > run_batch.sh <<'SH'
#!/usr/bin/env bash
set -euo pipefail

if [ -d "venv" ]; then
  # shellcheck disable=SC1091
  source venv/bin/activate
fi

python3 odoo_poc_batch.py
SH
chmod +x run_batch.sh
```

---

## 5) Verify Setup

```bash
source venv/bin/activate
python3 odoo_poc_batch.py
```

Expected startup output:
```
Loaded 1333 total products; processing first 20 (BATCH_LIMIT)
Concurrency = 2, Headless = False

Preview of products being processed:
 • Wix 42055 WIX Air Filter (42055)
 • Wix 57060 WIX Spin-On Lube Filter (57060)
Batch progress: ...
✅ Batch completed: 20 products processed (limit = 20).
```

---


