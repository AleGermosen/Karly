# Deploying Karly on the OptiPlex (run-from-there, edit-from-here)

> This is the **one-time, from-scratch** setup runbook (single bot, generic
> paths/IPs). It's already been done on the current OptiPlex, which now runs
> **two** bot instances (German + English) from `~/PycharmProjects/Karly` —
> see `DEPLOY_CHECKLIST.md` for the actual day-to-day flow and how the
> second (`karly-english`) unit + the nightly backup timer were added on top
> of what's set up below.

Goal: the **OptiPlex 3020M** runs Karly 24/7 as a background service; you keep
developing on your main PC and deploy with one command (`make deploy`). Because
the bot uses Telegram **long polling**, the OptiPlex needs no public IP, no port
forwarding, and no firewall changes — just power and internet.

Do the one-time setup below once. After that, your daily loop is just:

```
# on your main PC, after editing code:
git commit -am "..."     # (Claude Code does this)
make deploy              # push + pull + restart on the OptiPlex
make logs                # watch it run
```

---

## Part A — On your MAIN PC (one time)

### A1. Create an SSH key (skip if you already have `~/.ssh/id_ed25519`)
```bash
ls ~/.ssh/id_ed25519.pub || ssh-keygen -t ed25519 -C "karly-deploy"
```

### A2. Set the target host (once it exists — see Part B for the IP)
Add to `~/.bashrc` (adjust user + IP to match the OptiPlex):
```bash
export KARLY_HOST=aj@192.168.1.50
export KARLY_REMOTE_DIR=Karly
```
Then `source ~/.bashrc`.

> Tip: give the OptiPlex a static IP or a DHCP reservation in your router so its
> address never changes. Or add an alias in `~/.ssh/config`:
> ```
> Host optiplex
>     HostName 192.168.1.50
>     User aj
> ```
> then `export KARLY_HOST=optiplex`.

---

## Part B — On the OPTIPLEX (one time)

Do these directly on the OptiPlex (keyboard/monitor) or over SSH once it's up.

### B1. Install prerequisites
```bash
sudo apt update
sudo apt install -y openssh-server git python3-venv python3-pip
sudo systemctl enable --now ssh          # start the SSH server
ip addr | grep 'inet '                    # note the 192.168.x.x address -> KARLY_HOST
```

### B2. Authorize your PC's SSH key
From your MAIN PC:
```bash
ssh-copy-id aj@192.168.1.50               # use the OptiPlex user + IP
ssh aj@192.168.1.50 'echo connected ok'   # should print without a password
```

### B3. Clone the repo
The GitHub repo is **private**, so the OptiPlex needs to authenticate. Easiest:
create a GitHub Personal Access Token (classic, scope `repo`) and clone over
HTTPS:
```bash
cd ~
git clone https://github.com/AleGermosen/Karly.git
# username = AleGermosen ; password = the PAT (not your account password)
cd Karly
git config credential.helper store        # remember it for future git pull
```
(Alternative: add an SSH deploy key to the repo and clone via `git@github.com:`.)

### B4. Python environment
```bash
cd ~/Karly
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### B5. Configuration (.env)
`.env` is **not** in git (it holds secrets). Two options:

- Copy your working one from your MAIN PC:
  ```bash
  # run this on your MAIN PC:
  scp .env aj@192.168.1.50:~/Karly/.env
  ```
- Or create it on the OptiPlex from the template and fill it in:
  ```bash
  cp .env.example .env && nano .env
  ```

Quick sanity check that it starts (Ctrl-C after you see "Starting Karly"):
```bash
.venv/bin/python -m bot.main
```

### B6. Install the systemd **user** service
```bash
mkdir -p ~/.config/systemd/user
cp ~/PycharmProjects/Karly/deploy/karly.service ~/.config/systemd/user/karly.service
systemctl --user daemon-reload
systemctl --user enable --now karly
systemctl --user --no-pager status karly     # should be "active (running)"
```

### B7. Survive logout / run without an active session
By default user services stop when you log out. Enable **linger** so Karly keeps
running (and starts on boot) even with nobody logged in:
```bash
loginctl enable-linger $USER
```

Reboot once and confirm it comes back:
```bash
sudo reboot
# after it's back, from your MAIN PC:
make status
```

---

## Part C — Daily use (from your MAIN PC)

```bash
make deploy     # push current branch, pull + reinstall deps + restart on OptiPlex
make logs       # follow live logs (journalctl)
make status     # is it running?
make restart    # restart without deploying
make stop       # stop it
```

Need a real shell on the box? `ssh $KARLY_HOST`.

---

## Part D — Ollama activation (Phase 5c, optional but planned)

The LLM router already has Ollama built in but dormant; it health-checks on
startup and uses Gemini until Ollama answers. To turn it on:

### D1. Install Ollama on the OptiPlex
```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5:3b-instruct         # ~2 GB; fits 8 GB RAM, CPU-only
```
Ollama runs its own service on `http://localhost:11434`, which matches
`OLLAMA_BASE_URL` in `.env`.

### D2. Restart Karly and verify
```bash
make restart
make logs        # look for: "Ollama is available at http://localhost:11434"
```
Once available, `lookup` / `check` tasks route to Ollama locally, and if Gemini
hits its daily quota the bot falls back to Ollama instead of erroring.

### D3. Verify the quota fallback (optional)
Temporarily break the Gemini key in `.env` (e.g. add an `X`), `make restart`,
send a message — it should still answer via Ollama. Then restore the key and
`make restart`.

> On an 8 GB CPU-only box, `qwen2.5:3b-instruct` is the sweet spot. Expect
> lookups in a few seconds. Keep conversation/assessment/documents on Gemini
> (the router already does this).

---

## Troubleshooting

- **`make deploy` fails at ssh:** check `echo $KARLY_HOST`, and that
  `ssh $KARLY_HOST` works without a password (redo B2).
- **Service won't start:** `make logs` — usually a missing/invalid `.env`
  (config fails fast with the missing variable name).
- **Bot doesn't respond after reboot:** confirm `loginctl show-user $USER |
  grep Linger` says `Linger=yes` (B7).
- **`git pull` on deploy asks for a password:** re-run B3's
  `git config credential.helper store` and do one manual `git pull` to cache the
  PAT.
