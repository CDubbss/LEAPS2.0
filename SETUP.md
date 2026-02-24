# Leaps2.0 — Setup Guide

## Prerequisites
- Python 3.11+
- Node.js 18+ and npm (for frontend)
- Docker Desktop (for Redis)
- FMP API key (Financial Modeling Prep)

---

## Backend Setup

### 1. Create virtual environment
```bash
cd backend
python -m venv .venv
.venv\Scripts\activate    # Windows
```

### 2. Install PyTorch (CPU-only — do this FIRST)
```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
```

### 3. Install remaining dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure environment variables
```bash
copy ..\env.example .env
# Edit .env and add your FMP_API_KEY
```

### 5. Start Redis
```bash
# From the root directory:
docker compose up -d
```

### 6. Pre-download FinBERT model (~450MB, one-time)
```bash
python -c "
from transformers import BertTokenizer, BertForSequenceClassification
BertTokenizer.from_pretrained('ProsusAI/finbert')
BertForSequenceClassification.from_pretrained('ProsusAI/finbert')
print('FinBERT downloaded successfully')
"
```

### 7. Initialize ML training database
```bash
python -m backend.ml.train --init-db
```

### 8. Start the backend server
```bash
# From the project root:
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at:
- **Swagger UI**: http://localhost:8000/docs
- **Health check**: http://localhost:8000/health

---

## Frontend Setup

### 1. Install dependencies
```bash
cd frontend
npm install
```

### 2. Start development server
```bash
npm run dev
```

The dashboard will be available at: **http://localhost:5173**

---

## Running Your First Scan

1. Open http://localhost:5173
2. In the Filter Panel (left), select strategies (e.g., "Bull Call", "Bear Put")
3. Optionally add specific symbols (or leave empty to scan the default universe)
4. Click **"Run Scan"**
5. Click any result row to see the full detail panel

---

## ML Model Training

The ML model starts in **placeholder mode** (returns ~50 quality scores) until trained.
As you run scans, spread candidates are logged to `backend/ml/data/spread_outcomes.db`.

After collecting ~500+ outcomes with labeled results:
```bash
python -m backend.ml.train
# Then restart the backend server to load the new model
```

---

## Running Tests
```bash
cd backend
pytest tests/ -v
```

---

## Backtesting
After labeling historical outcomes:
```bash
python -m backend.ml.backtest --start 2024-01-01 --end 2024-06-01
```
