NOVA Bot — API-LESS + Captcha-Aware
====================================

Files in this folder
--------------------
  bot.py               Telegram bot (main entry)
  checkout_engine.py   Shopify checkout engine (captcha-aware)
  api_server.py        FastAPI HTTP wrapper for the engine (optional)
  preview_server.py    Mock API for the Replit docs preview (optional)
  requirements.txt     pip install -r requirements.txt
  videos/              welcome.mp4 + hit*.mp4 (optional, for HIT videos)

Run the bot
-----------
  pip install -r requirements.txt
  export BOT_TOKEN="<your bot token>"
  python bot.py

Run the HTTP API (optional)
---------------------------
  export CHECKER_THREADS=200
  export CHECKER_RETRIES=1
  python api_server.py       # listens on :8000 by default

Captcha handling
----------------
  The engine sets `captcha: True` whenever it detects a captcha
  challenge at any step. The bot reads that flag and rotates the
  site automatically rather than treating the card as dead.

  Tune in bot.py:
    CAPTCHA_EXTRA_RETRIES        (default 4)
    CAPTCHA_PENALTY_WEIGHT       (default 0.8)
    SITE_DISABLE_AFTER_CAPTCHAS  (default 5)

  Admin commands:
    /captchastats                List captcha-heavy sites
    /resetcaptcha <site>         Clear one site's captcha counter
    /resetcaptcha all            Clear every site's captcha counter
    /clearcaptcha                Clear counters without re-enabling
