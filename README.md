# Kuku Promo Builder

[Submission files](submission/) · [Solution PDF](submission/solution.pdf) · [Setup guide](submission/Kuku-Promo-Builder-Setup.pdf)

A local prototype for finding and ranking 20–60 second promo cuts from timestamped microdrama screenplays. Upload a ZIP of numbered episode .txt files, review the ranked cuts and source excerpts, save selections, and export CSV.

## Run locally

Requires Python 3.12+, Node.js 20.19+ or 22.12+, npm, and a Gemini API key.

```sh
cd implementation/frontend
npm ci
npm run build
cd ../backend
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
```

Set `LLM_API_KEY` in `.env`. The default model is Gemini 3.1 Flash-Lite. Set `LLM_MODEL` and `LLM_BASE_URL` to use a compatible alternative.

```sh
.venv/bin/python run_studio.py
```

Open http://127.0.0.1:8000. Keep the terminal open while jobs run. The SQLite database and run logs are stored under `implementation/backend/data/`. The assignment source pack is supplied separately by Kuku.

## Pipeline

Python parses timestamped source blocks and enumerates dialogue-safe windows. A LangGraph workflow proposes and reviews cuts. Gemini assigns points for hook (30), clarity (25), cliffhanger (35), and pacing (10) with source evidence. Python validates citations, enforces per-criterion minimums of 25, 20, 28, and 7, ranks by total points, and removes overlapping cuts. The editor reviews and selects the shortlist.

The prototype handles continuous single-episode cuts. The scores are editorial judgments and should be checked against the screenplay and footage before publication.

## Verify

From `implementation/backend`, run `.venv/bin/python -m unittest discover -s tests -q`. The frontend production build runs TypeScript checks.
