# Android Server Setup Guide
### Hosting Your Quant Trading Bot on a Spare Android Phone (24/7)

---

## Architecture Overview

```
Android Phone (Server)                    Laptop (Client)
──────────────────────                    ───────────────
Termux (base shell)                       VS Code Remote-SSH
  └── proot Ubuntu                          └── Edit files directly on phone
        ├── Python 3.11                    Browser
        ├── FastAPI :8080     ←─ WiFi ───    └── Monitor dashboard
        ├── React :5173       ←─ WiFi ───  Terminal
        └── Trading Bot             └── SSH → tmux → live logs
```

> **Why proot-distro (Ubuntu), not native Termux?**  
> TA-Lib, hmmlearn, and scikit-learn require C compilation with glibc headers.  
> Native Termux uses musl-libc and many pip wheels simply fail to build.  
> Ubuntu inside proot gives you a full Linux environment where everything Just Works.

---

## Phase 1 — Install Termux (Phone)

**Critical:** Install from **F-Droid only**. The Play Store version is abandoned (2019) and breaks pip.

1. Open browser on phone → download **F-Droid** from `f-droid.org`
2. Inside F-Droid, search for **Termux** → install
3. Open Termux and run:

```bash
# Update package lists
pkg update && pkg upgrade -y

# Grant storage access (lets Termux read/write your phone files)
termux-setup-storage

# Install essential base tools
pkg install -y git curl wget nano openssh termux-api
```

---

## Phase 2 — Set Up Ubuntu via proot-distro (Phone)

proot-distro runs a real Ubuntu ARM64 environment inside Termux without root.

```bash
# Install proot-distro
pkg install -y proot-distro

# Install Ubuntu 22.04
proot-distro install ubuntu

# Enter Ubuntu (you'll use this for ALL Python work)
proot-distro login ubuntu
```

You're now inside Ubuntu. All further Python commands in this guide run here unless marked `[Termux]`.

```bash
# Inside Ubuntu — initial setup
apt update && apt upgrade -y
apt install -y python3.11 python3.11-venv python3.11-dev python3-pip \
               build-essential cmake pkg-config libffi-dev libssl-dev \
               git curl wget

# Set python3 to point to 3.11
update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1
```

---

## Phase 3 — Install TA-Lib and Heavy ML Libraries (Ubuntu)

### 3a. Compile TA-Lib C Library from Source

```bash
cd /tmp
wget https://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz
tar -xzf ta-lib-0.4.0-src.tar.gz
cd ta-lib

# Compile and install (takes ~2 minutes on phone CPU)
./configure --prefix=/usr
make -j$(nproc)
make install
ldconfig
```

### 3b. Create Project Virtual Environment

```bash
# Go to where you'll store your project (inside Ubuntu's home)
cd ~
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip wheel setuptools
```

### 3c. Install All Python Dependencies

```bash
# Core scientific stack (pre-built ARM64 wheels from PyPI)
pip install numpy pandas scipy

# ML + quant
pip install scikit-learn hmmlearn statsmodels

# TA-Lib Python wrapper (C library must be installed first — done above)
pip install TA-Lib

# FastAPI stack
pip install fastapi uvicorn[standard] python-dotenv pydantic

# Finance data
pip install yfinance requests feedparser vaderSentiment

# Deep learning (optional — heavy; skip if RAM is tight)
# pip install torch --index-url https://download.pytorch.org/whl/cpu

# Verify everything loaded
python3 -c "import numpy, pandas, sklearn, hmmlearn, talib; print('All imports OK')"
```

> **If TA-Lib fails:** Make sure `ldconfig` ran after `make install`. If still failing:  
> `export LD_LIBRARY_PATH=/usr/local/lib:$LD_LIBRARY_PATH`

---

## Phase 4 — Transfer Your Project to the Phone

### Option A: rsync over SSH (fastest for large projects)

On your **laptop terminal**:

```bash
# First get the phone's IP (run in Termux — see Phase 5 for SSH setup)
# Then sync your project folder to the phone
rsync -avz --exclude '__pycache__' --exclude 'node_modules' --exclude '.git' \
  /path/to/your/project/ \
  -e "ssh -p 8022" \
  user@192.168.x.x:/root/trading-bot/
```

### Option B: git clone (cleanest)

```bash
# Inside Ubuntu on phone
git clone https://github.com/youruser/your-trading-bot.git ~/trading-bot
```

### Option C: USB File Transfer

Copy project folder to phone storage via USB, then inside Ubuntu:

```bash
# Phone storage is accessible from Ubuntu via
cp -r /sdcard/trading-bot ~/trading-bot
```

---

## Phase 5 — SSH Server + VS Code Remote Editing

### 5a. Configure SSH on Termux (Phone)

```bash
# [Termux] — run these in Termux, NOT inside Ubuntu

# Generate SSH host keys (first time only)
ssh-keygen -A

# Set a password for SSH login
passwd

# Start the SSH server (Termux uses port 8022 — Android blocks ports below 1024)
sshd

# Find your phone's local IP address
ip addr show wlan0 | grep 'inet ' | awk '{print $2}' | cut -d/ -f1
# Example output: 192.168.1.105
```

> **Make SSH start automatically:** Add `sshd` to your `~/.bashrc` in Termux.

### 5b. Set Up Key-Based Auth (No Password Prompts)

On your **laptop**:

```bash
# Generate SSH key if you don't have one
ssh-keygen -t ed25519 -C "laptop-to-phone"

# Copy public key to the phone
ssh-copy-id -p 8022 user@192.168.x.x

# Test the connection (should NOT ask for password now)
ssh -p 8022 user@192.168.x.x
```

### 5c. Configure VS Code Remote-SSH

1. Install the **Remote - SSH** extension in VS Code
2. Open Command Palette → `Remote-SSH: Open SSH Configuration File`
3. Add this block:

```
Host android-trading-bot
    HostName 192.168.x.x
    User u0_a123
    Port 8022
    IdentityFile ~/.ssh/id_ed25519
```

> **Finding your Termux username:** run `whoami` in Termux. It looks like `u0_a123`.

4. Command Palette → `Remote-SSH: Connect to Host` → `android-trading-bot`
5. VS Code is now editing files **directly on the phone**. Open the folder:  
   `/data/data/com.termux/files/home/root/trading-bot` (or wherever your project is)

---

## Phase 6 — 24/7 Stability

### 6a. Disable Battery Optimization (Critical)

On the phone:
- **Settings → Apps → Termux → Battery → Unrestricted** (exact wording varies by Android)
- Also find **"Don't optimize"** or **"Allow background activity"** for Termux
- Some phones: Settings → Battery → Battery Optimization → All Apps → Termux → Don't Optimize

### 6b. Acquire Wake Lock (Prevents CPU Sleep)

```bash
# [Termux] — run BEFORE entering Ubuntu
termux-wake-lock
```

> This keeps the CPU running. You'll see a persistent notification. This is required.

### 6c. Set Up tmux for Persistent Sessions

```bash
# [Termux] Install tmux
pkg install tmux

# Start a named tmux session
tmux new-session -s bot

# Inside tmux — enter Ubuntu and start the bot
proot-distro login ubuntu -- bash -c "cd ~/trading-bot && source ~/venv/bin/activate && python server.py"

# Detach from tmux (bot keeps running): Ctrl+B, then D
# Reattach later: tmux attach -t bot
```

### 6d. Auto-Restart Script (Crash Recovery)

Create `/data/data/com.termux/files/home/start-bot.sh` in Termux:

```bash
#!/data/data/com.termux/files/usr/bin/bash

# Acquire wake lock to prevent CPU sleep
termux-wake-lock

# Start tmux session if not already running
tmux has-session -t bot 2>/dev/null
if [ $? != 0 ]; then
  tmux new-session -d -s bot
fi

# Run the bot inside Ubuntu with auto-restart loop
tmux send-keys -t bot "proot-distro login ubuntu -- bash -c '
  cd ~/trading-bot
  source ~/venv/bin/activate
  while true; do
    echo \"[$(date)] Starting server...\"
    python server.py
    echo \"[$(date)] Server crashed! Restarting in 10s...\"
    sleep 10
  done
'" Enter

echo "Bot started in tmux session 'bot'. Attach with: tmux attach -t bot"
```

```bash
chmod +x ~/start-bot.sh
```

Run this once after every phone reboot: `~/start-bot.sh`

### 6e. Handle Phone Reboots (Termux:Boot)

```bash
# [Termux] Install Termux:Boot from F-Droid
# After installing, it creates ~/.termux/boot/
mkdir -p ~/.termux/boot

# Create auto-start script
cat > ~/.termux/boot/start-trading-bot.sh << 'EOF'
#!/data/data/com.termux/files/usr/bin/bash
sleep 30  # Wait for WiFi to connect
~/start-bot.sh
EOF

chmod +x ~/.termux/boot/start-trading-bot.sh
```

> After a reboot, Termux:Boot runs this script automatically. The 30-second delay gives WiFi time to connect before the bot tries to fetch market data.

---

## Phase 7 — Live Monitoring from Laptop

### Option A: Attach to tmux Session (Best)

```bash
# On laptop — SSH into phone and attach to the running bot session
ssh -p 8022 user@192.168.x.x -t "tmux attach -t bot"
```

You see the exact live terminal output. Ctrl+B, D to detach without killing the bot.

### Option B: Watch Live Logs

Add logging to your `server.py`:

```python
import logging
logging.basicConfig(
    filename='/root/trading-bot/logs/server.log',
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
```

Then from laptop:

```bash
ssh -p 8022 user@192.168.x.x "tail -f ~/trading-bot/logs/server.log"
```

### Option C: Access Your Dashboard from Laptop Browser

Your FastAPI backend and React frontend are already on ports 8080 and 5173. Just open on your laptop:

```
http://192.168.x.x:8080    ← FastAPI + all API endpoints
http://192.168.x.x:5173    ← React dashboard (if you build/serve it)
```

For the React frontend, build it once and serve statically:

```bash
# Inside Ubuntu on phone
cd ~/trading-bot/frontend
npm install
npm run build

# Serve the built files via FastAPI (add this to your server.py)
# from fastapi.staticfiles import StaticFiles
# app.mount("/", StaticFiles(directory="frontend/dist", html=True))
```

Now the entire dashboard is accessible from your laptop at `http://192.168.x.x:8080`.

---

## Phase 8 — Performance Tuning for 6GB RAM

Your bot uses HMM, LSTM, and multiple concurrent market loops. On 6GB RAM:

```python
# In server.py — add near the top to limit thread pool size
import os
os.environ["OMP_NUM_THREADS"] = "2"      # Limit OpenMP threads (numpy/scikit)
os.environ["OPENBLAS_NUM_THREADS"] = "2" # Limit BLAS threads
os.environ["MKL_NUM_THREADS"] = "2"      # Limit MKL threads (if used)

# Uvicorn — limit worker threads
# In your uvicorn.run() call:
# uvicorn.run(app, host="0.0.0.0", port=8080, loop="asyncio", workers=1)
```

```bash
# Check RAM usage inside Ubuntu
free -h

# Check which processes are using most RAM
ps aux --sort=-%mem | head -10
```

**If RAM is tight:**  
- Disable the LSTM engine in config (it's the heaviest single component)
- Reduce the number of concurrent symbols per market loop
- Use `--no-cache-dir` with pip to avoid filling 64GB storage with pip cache

---

## Quick Reference Card

| Task | Command |
|------|---------|
| Enter Ubuntu | `proot-distro login ubuntu` |
| Start bot | `~/start-bot.sh` |
| View live output | `tmux attach -t bot` |
| Detach from tmux | `Ctrl+B`, then `D` |
| SSH from laptop | `ssh -p 8022 user@192.168.x.x` |
| Check phone IP | `ip addr show wlan0` (in Termux) |
| Check RAM | `free -h` (in Ubuntu) |
| Acquire wake lock | `termux-wake-lock` (in Termux) |
| Stop bot cleanly | `tmux kill-session -t bot` |
| Transfer files | `rsync -avz -e "ssh -p 8022" ./project/ user@IP:~/trading-bot/` |

---

## Troubleshooting

**TA-Lib import fails:**  
```bash
export LD_LIBRARY_PATH=/usr/local/lib:$LD_LIBRARY_PATH
echo 'export LD_LIBRARY_PATH=/usr/local/lib:$LD_LIBRARY_PATH' >> ~/.bashrc
```

**SSH connection refused:**  
Run `sshd` in Termux. Check `ps aux | grep sshd`.

**proot-distro Ubuntu is slow on first boot:**  
Normal — it's unpacking ~500MB. Only happens once.

**Phone restarts kill the bot even with Termux:Boot:**  
Check that battery optimization is truly disabled for Termux AND Termux:Boot. On Xiaomi/Samsung/Huawei devices, also disable "Auto-start management" restrictions.

**Out of storage:**  
```bash
pip cache purge          # Clear pip cache (can free 1–2GB)
apt clean                # Clear apt cache in Ubuntu
du -sh ~/*               # Find what's taking space
```

**hmmlearn build fails:**  
```bash
pip install --no-build-isolation hmmlearn
# or
pip install hmmlearn --prefer-binary
```
