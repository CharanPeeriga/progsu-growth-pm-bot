# growth-pm-bot

Discord PM bot for Progsu Growth. Placeholder — full docs coming soon.

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
cp .env.example .env            # then fill in DISCORD_TOKEN and DATABASE_URL
python bot.py
```

## Deployment

Deployed on Railway as a `worker` process (see `Procfile`).
