# Setup prompt for Claude Code (run this ON the OptiPlex)

**How to use:** On the OptiPlex, open Claude Code inside the extracted project
folder and paste everything in the box below as your first message. A human (AJ)
is sitting at the machine and can type a sudo password when asked.

Before you start, make sure:
- You extracted the GitHub zip (the folder is probably named `Karly-main`).
- You placed the real `.env` file **inside** that folder (it holds the Telegram
  and Gemini keys; it is not in the zip).

---

```
You are setting up "Karly", a single-user German-tutor Telegram bot, to run
24/7 on this machine — a Dell OptiPlex 3020M (8 GB RAM, Linux, no GPU). The bot
is Python, uses Telegram long polling (no public IP or ports needed), stores
data in SQLite, and calls Google Gemini (and optionally a local Ollama model).

I extracted the project from a GitHub zip and I have already put the real .env
file (with my secret keys) inside the project folder. Do NOT print the contents
of .env or any secret values.

Work through the goals below IN ORDER. After each goal, run its verification and
tell me the result before moving on. If something fails, stop and explain it in
plain language with the fix — don't guess past an error. When everything is
done, give me a short summary and the exact command to see live logs.

GOAL 1 — Locate and normalize the project folder
- Find the project root (the folder containing bot/, llm/, requirements.txt).
- The systemd service expects it at ~/Karly. If it's somewhere else (e.g.
  ~/Downloads/Karly-main), move/rename it to ~/Karly.
- Confirm .env exists in ~/Karly and that requirements.txt is present.
  (Check .env has non-empty TELEGRAM_BOT_TOKEN and GEMINI_API_KEY WITHOUT
  printing their values.)

GOAL 2 — System prerequisites
- Ensure python3, python3-venv, and python3-pip are installed. Install any that
  are missing with apt (I'll type my sudo password if prompted).

GOAL 3 — Python environment
- Create a virtualenv at ~/Karly/.venv and install requirements.txt into it.
- Verify apscheduler imported OK (it comes via the python-telegram-bot[job-queue]
  extra and is needed for reminders).

GOAL 4 — Smoke test (does it start and reach Telegram/Gemini?)
- Run the bot briefly: ~/Karly/.venv/bin/python -m bot.main
- Success looks like log lines "Database ready." and "Starting Karly (long
  polling)...", and (expected on this machine) an INFO line that Ollama is
  unavailable and it's routing to Gemini — that is FINE for now.
- Then stop it (Ctrl-C / terminate). Confirm ~/Karly/karly.db was created.
- Also run the unit tests: ~/Karly/.venv/bin/python -m unittest discover -s tests
  (they should all pass).

GOAL 5 — Install the background service (systemd --user)
- Copy ~/Karly/deploy/karly.service to ~/.config/systemd/user/karly.service
  (create the directory if needed).
- Run: systemctl --user daemon-reload
       systemctl --user enable --now karly
- Verify: systemctl --user --no-pager status karly shows "active (running)".
- Check recent logs with: journalctl --user -u karly -n 30 --no-pager

GOAL 6 — Keep it running without me logged in (and across reboots)
- Run: loginctl enable-linger $USER
- Confirm: loginctl show-user $USER | grep Linger  ->  Linger=yes
- Explain to me that after this, the bot keeps running when I log out and starts
  on boot. (You don't need to reboot now; tell me I can test with `sudo reboot`
  later and then `systemctl --user status karly`.)

GOAL 7 (OPTIONAL — ask me first) — Activate the local Ollama model
- Ask me if I want to enable Ollama now. If yes:
  - Install it: curl -fsSL https://ollama.com/install.sh | sh
  - Pull the model: ollama pull qwen2.5:3b-instruct  (~2 GB, CPU-only, fits 8 GB)
  - Restart Karly: systemctl --user restart karly
  - Confirm the logs now show "Ollama is available at http://localhost:11434".
  - Explain that lookups now run locally and that if Gemini hits its daily quota
    the bot falls back to Ollama automatically.
- If I say no, skip this — the bot already works on Gemini alone.

GOAL 8 (OPTIONAL — ask me first) — Enable one-command deploys from my other PC
- Since I installed from a zip, this folder is not yet a git clone, so the
  `make deploy` workflow (git pull on this box) won't work yet. Ask me if I want
  to fix that now. If yes:
  - Turn ~/Karly into a clone of my repo without losing .env or karly.db:
      cd ~/Karly
      git init
      git remote add origin https://github.com/AleGermosen/Karly.git
      git fetch origin
      git checkout -f -t origin/main
    (git won't overwrite untracked files like .env; .env and *.db are gitignored
    so they stay.)
  - Tell me that future `git pull` will ask for GitHub credentials: username
    AleGermosen and a Personal Access Token (classic, scope "repo") as the
    password. Suggest: git config credential.helper store, then one manual
    `git pull` to cache it.
  - Then from my OTHER PC I can run `make deploy` to push + pull + restart here.
- If I say no, skip it — I can re-zip and re-copy manually for now.

FINISH
- Summarize what's running, how to check status/logs, and anything I still need
  to do myself.
```

---

## Quick reference (for AJ, after setup)

On the OptiPlex directly:
```bash
systemctl --user status karly          # is it running?
journalctl --user -u karly -f          # live logs
systemctl --user restart karly         # restart
```

From your main PC once GOAL 8 is done and `KARLY_HOST` is set:
```bash
make deploy    # push + remote pull + restart
make logs      # follow remote logs
```
