# Karly — Deploy Checklist

Your recurring runbook for shipping changes to **GitHub** and the **OptiPlex**.
(One-time machine setup lives in `SETUP_OPTIPLEX.md` — you don't need that again.)

Claude can edit code and run the tests, but **cannot** push to `main` or SSH to
the OptiPlex (both are blocked by safety rules), so those steps are on you.

---

## TL;DR — every time you ship

```bash
cd ~/PycharmProjects/Karly

# 0. KARLY_HOST is already exported in your ~/.bashrc (= karly-optiplex,
#    an SSH alias for marcus@192.168.8.228). New shells pick it up
#    automatically; only re-export it if `echo $KARLY_HOST` is empty.

# 1. sanity check + commit
make test
git add -A
git commit -m "your message"

# 2. push to GitHub
git push origin main

# 3. deploy to the OptiPlex (pushes, pulls remotely, restarts the service)
make deploy

# 4. confirm it came back up
make logs            # Ctrl-C to stop following
```

That's it. `make deploy` runs `deploy/deploy.sh`, which pushes the current
branch, then SSHes in to `git pull`, reinstall deps, and `systemctl --user
restart karly`.

> **Note:** `KARLY_HOST=karly-optiplex` is already set in your `~/.bashrc`, and
> that alias is defined in `~/.ssh/config` (→ `marcus@192.168.8.228`), so a
> plain `ssh karly-optiplex` just works.

---

## What "healthy" looks like in the logs

After `make deploy` (or `make logs`), you want to see, near the end:

```
Database ready.
... Ollama is available at http://localhost:11434
Starting Karly (long polling)...
```

And you should **not** see any lines containing `api.telegram.org` (the token
would be in them — the log fix suppresses these).

---

## Quick reference — Makefile targets

| Command | What it does |
|---|---|
| `make test` | Run the unit tests locally |
| `make run` | Run the bot locally (needs local `.env`) |
| `make deploy` | Push + pull on OptiPlex + restart service |
| `make logs` | Follow the live service logs (Ctrl-C to exit) |
| `make status` | One-shot service status |
| `make restart` | Restart the service without deploying |
| `make stop` | Stop the service |

All remote targets need `KARLY_HOST` set.

---

## When the schema changes

If a change adds a database column, no manual step is needed: the migration in
`db/session.py` (`_apply_migrations`) runs on startup and adds any missing
columns automatically. Just `make deploy` as usual.

---

## When you rotate the bot token

You said the token's already rotated — for next time the steps are:

1. `@BotFather` → `/revoke` → `/token` to get a new token.
2. On the OptiPlex, update `TELEGRAM_BOT_TOKEN` in `~/Karly/.env`:
   ```bash
   ssh $KARLY_HOST 'nano ~/Karly/.env'      # edit the token line
   make restart
   ```
3. (Optional hygiene) clear old journal entries that held the old token:
   ```bash
   ssh $KARLY_HOST 'journalctl --user --vacuum-time=1s'
   ```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Set KARLY_HOST ...` error | `export KARLY_HOST=karly-optiplex` |
| `git push` rejected (behind) | `git pull --rebase origin main`, then push |
| Deploy fails on `git pull` (remote dirty) | `ssh $KARLY_HOST 'cd Karly && git status'`, resolve, re-deploy |
| Service won't start | `make logs` — read the traceback; usually a bad `.env` value |
| Bot silent but service "running" | Gemini daily quota (20/req) — logs show `429`; waits till reset |
