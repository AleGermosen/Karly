# Karly — Deploy Checklist

Your recurring runbook for shipping changes from **Vanessa** (dev laptop) to
the **OptiPlex** (server). Two terminals are always open:

| Terminal | Machine | Prompt |
|---|---|---|
| **Vanessa** | Dev laptop | `(.venv) aj@Vanessa:~/PycharmProjects/Karly$` |
| **OptiPlex** | Server | `marcus@paradise:~/PycharmProjects/Karly$` |

Claude edits code and runs tests on Vanessa, but cannot push to GitHub or SSH
to the OptiPlex — those steps are on you.

---

## TL;DR — first time (run once on Vanessa)

Do this once when you first open the project in PyCharm on a fresh Vanessa.

```bash
# 1. Get the code (skip if PyCharm already cloned it)
cd ~/PycharmProjects
git clone git@github.com:AleGermosen/Karly.git   # or your remote URL
cd Karly

# 2. Create the virtualenv and install deps
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 3. Create your local .env and fill in the secrets
cp .env.example .env
nano .env        # fill in TELEGRAM_BOT_TOKEN, GEMINI_API_KEY, GROQ_API_KEY

# 4. Add the deploy env + SSH alias to ~/.bashrc so every shell has them
cat >> ~/.bashrc <<'EOF'
export KARLY_HOST=karly-optiplex
export KARLY_REMOTE_DIR=PycharmProjects/Karly
EOF
source ~/.bashrc

# 5. Set up the karly-optiplex SSH alias (once) so make deploy/logs work
cat >> ~/.ssh/config <<'EOF'
Host karly-optiplex
    HostName 192.168.8.228        # the OptiPlex's LAN IP
    User marcus
EOF
ssh karly-optiplex 'echo ok'      # confirm passwordless SSH works

# 6. Sanity checks
make test        # unit tests should pass
make run         # runs the bot locally against your .env (Ctrl-C to stop)
```

In PyCharm: set the interpreter to `~/PycharmProjects/Karly/.venv/bin/python`
(Settings → Project → Python Interpreter → Add → Existing → point at that path).

> The **secrets on the OptiPlex are separate** from your local `.env`. First-time
> server setup lives in the "Secrets" section below — you edit those on the
> OptiPlex, not on Vanessa.

---

## TL;DR — every time you ship (the recurring flow)

`KARLY_HOST` / `KARLY_REMOTE_DIR` are already in your `~/.bashrc` from setup, so
new shells just work.

**On Vanessa:**
```bash
# 1. Run tests
make test

# 2. Commit
git add -p          # or: git add <specific files>
git commit -m "your message"

# 3. Deploy (push to GitHub, pull on OptiPlex, restart service)
make deploy

# 4. Watch logs to confirm it came up clean
make logs           # Ctrl-C to stop
```

That's it. `make deploy` runs `deploy/deploy.sh`, which pushes the current
branch, SSHes to the OptiPlex to `git pull`, reinstalls deps, and
`systemctl --user restart karly`.

---

## What "healthy" looks like in the logs

After `make deploy` (or `make logs`), you want to see near the end:

```
Database ready.
... Ollama is available at http://localhost:11434
Starting Karly (long polling)...
```

Then, on the first message, you want a Groq call succeeding:
```
INFO httpx: HTTP Request: POST https://api.groq.com/openai/v1/chat/completions "HTTP/1.1 200 OK"
```

You should **not** see repeated Groq 404s (bad model name) or only Ollama
calls (means Groq key is missing or Groq is exhausted).

---

## Secrets — never committed, must be set on OptiPlex manually

`.env` is gitignored. When you add a new secret, SSH in and append it:

**On OptiPlex:**
```bash
echo 'NEW_VAR=value' >> ~/PycharmProjects/Karly/.env
systemctl --user restart karly
```

Current secrets in `.env` on the OptiPlex:
- `TELEGRAM_BOT_TOKEN`
- `GEMINI_API_KEY`
- `GROQ_API_KEY`

After editing `.env`, always restart the service for it to take effect.

---

## Quick reference — Makefile targets

All remote targets need `KARLY_HOST` (and `KARLY_REMOTE_DIR` unless you set a
`~/Karly` symlink on the OptiPlex).

| Command | Run on | What it does |
|---|---|---|
| `make test` | Vanessa | Run the unit tests locally |
| `make run` | Vanessa | Run the bot locally (needs local `.env`) |
| `make deploy` | Vanessa | Commit push + pull on OptiPlex + restart |
| `make logs` | Vanessa | Follow live service logs (Ctrl-C to exit) |
| `make status` | Vanessa | One-shot service status |
| `make restart` | Vanessa | Restart without deploying new code |
| `make stop` | Vanessa | Stop the service |

Or run systemctl directly **on OptiPlex** if SSH isn't cooperating:
```bash
systemctl --user restart karly
journalctl --user -u karly -n 50 --no-pager
```

---

## When the schema changes

No manual step needed: `db/session.py` (`_apply_migrations`) runs on startup
and adds missing columns automatically. Just `make deploy` as usual.

---

## When you add a new Groq model

Groq's free-tier model list can change. To check what's available **on OptiPlex**:

```bash
curl -s https://api.groq.com/openai/v1/models \
  -H "Authorization: Bearer $(grep GROQ_API_KEY ~/PycharmProjects/Karly/.env | cut -d= -f2)" \
  | python3 -m json.tool | grep '"id"'
```

Then update `GROQ_MODEL_PRIMARY` / `GROQ_MODEL_FALLBACK` in `config.py` on
Vanessa and `make deploy`.

---

## When you rotate the bot token

1. `@BotFather` → `/revoke` → `/token` to get a new token.
2. **On OptiPlex**, update the token in `.env`:
   ```bash
   nano ~/PycharmProjects/Karly/.env   # edit TELEGRAM_BOT_TOKEN line
   systemctl --user restart karly
   ```
3. (Optional hygiene) clear old journal entries:
   ```bash
   journalctl --user --vacuum-time=1s
   ```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Set KARLY_HOST ...` error | `export KARLY_HOST=karly-optiplex` on Vanessa |
| `cd: Karly: No such file or directory` | `export KARLY_REMOTE_DIR=PycharmProjects/Karly` on Vanessa |
| `.venv/bin/pip: cannot execute` | On OptiPlex: `sudo apt install python3-venv python3-pip -y && rm -rf .venv && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt` |
| `git push` rejected (behind) | On Vanessa: `git pull --rebase origin main`, then push |
| Deploy fails on `git pull` (remote dirty) | On OptiPlex: `git status`, resolve, then `make restart` on Vanessa |
| Service won't start | `make logs` on Vanessa — read the traceback; usually a bad `.env` value |
| Groq 404 errors | Groq model name changed — check available models (see section above) |
| Bot silent, only Ollama | Groq key missing from OptiPlex `.env` — add it and restart |
| Bot silent, all 429s | All free-tier daily limits hit — wait for reset or check `/status` in Telegram |
