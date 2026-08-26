# 🧠 Headless AI Mac

A Python script that automatically detects your Apple Silicon Mac's hardware configuration and applies a fully optimised setup for running local AI inference — headless, always-on, and accessible remotely.

Designed for **Mac Mini**, **Mac Studio**, and **MacBook** running as a dedicated AI server with no monitor attached.

---

## Table of Contents

- [Why Headless?](#why-headless)
- [What the Script Does](#what-the-script-does)
- [Requirements](#requirements)
- [Usage](#usage)
  - [Setup](#setup)
  - [Restore (Desktop Mode)](#restore-desktop-mode)
- [What Gets Configured](#what-gets-configured)
  - [Hardware Detection](#hardware-detection)
  - [VRAM Allocation Table](#vram-allocation-table)
  - [Disabled Services](#disabled-services)
  - [Ollama Configuration](#ollama-configuration)
  - [Homebrew](#homebrew)
  - [Tailscale & Remote Access](#tailscale--remote-access)
- [After Setup](#after-setup)
  - [Pulling a Model](#pulling-a-model)
  - [Useful Commands](#useful-commands)
  - [Connecting an Agent or Client](#connecting-an-agent-or-client)
- [Connecting a Monitor Later](#connecting-a-monitor-later)
- [Reverting Everything](#reverting-everything)
- [What Is NOT Changed](#what-is-not-changed)

---

## Why Headless?

Running macOS without a GUI session reclaims **2.5–4 GB of Unified Memory** that would otherwise be consumed by `WindowServer`, display compositors, and GUI framebuffers. It also eliminates **GPU display contention**, giving Ollama 100% of the Metal compute cores for token generation.

```
┌─────────────────────────────────────────────────────────────┐
│                    32 GB UNIFIED MEMORY                     │
│                                                             │
│  Standard Mac (GUI):                                        │
│  [ macOS + WindowServer (~5 GB) ] [ Free VRAM (~27 GB) ]    │
│                                                             │
│  Headless Mac (this script):                                │
│  [ macOS Minimal (~2 GB) ]  [ >>> Free VRAM (~30 GB) <<< ]  │
└─────────────────────────────────────────────────────────────┘
```

---

## What the Script Does

| Phase         | Description                                                                         |
|---------------|-------------------------------------------------------------------------------------|
| **Detect**    | Reads chip model (M1–M5, base/Pro/Max/Ultra) and total RAM                          |
| **VRAM**      | Sets an aggressive GPU memory limit (~90% of RAM) and persists it across reboots    |
| **Power**     | Disables all sleep modes, enables auto-restart on power failure or kernel panic     |
| **Services**  | Disables ~20 background agents (Spotlight, Siri, iCloud, analytics, photo analysis) |
| **Homebrew**  | Installs Homebrew if missing and adds it to `~/.zshrc`                              |
| **Ollama**    | Installs Ollama and creates a `launchd` daemon with production performance flags    |
| **SSH**       | Enables Remote Login so the Mac is accessible over the network                      |
| **Tailscale** | Optionally installs Tailscale for secure remote access from anywhere                |


---

## Requirements

- **macOS** on Apple Silicon (M1, M2, M3, M4, M5 — any tier)
- **Python 3** (pre-installed on macOS)
- **Internet connection** (for Homebrew, Ollama, and Tailscale)
- **`sudo` privileges**

No third-party Python packages are required — the script uses only the standard library.

---

## Usage

### Setup

Clone the repo and run the script:

```bash
git clone https://github.com/ThiagoEvoa/headless-ai-mac.git
cd headless-ai-mac
sudo python3 headless-ai-mac.py
```

The script will:
1. Print your detected hardware configuration and ask for confirmation before making any changes.
2. Walk through each phase, showing progress for every step.
3. Print a final summary with useful commands when complete.

> **Note:** The script will automatically re-invoke itself with `sudo` if not already running as root.

---

### Restore (Desktop Mode)

When you want to plug in a monitor and return to normal desktop use, run:

```bash
sudo python3 headless-ai-mac.py --restore
```

This reverses all system-level changes. See [Reverting Everything](#reverting-everything) for the full list.

---

## What Gets Configured

### Hardware Detection

The script reads:
- **Chip model** via `sysctl machdep.cpu.brand_string` (e.g. `Apple M4 Pro`)
- **Generation and tier** parsed from the chip string (base / Pro / Max / Ultra)
- **Total RAM** via `sysctl hw.memsize`

This information is used to calculate the correct VRAM limit for your specific machine.

---

### VRAM Allocation Table

macOS by default reserves ~20–25% of unified memory for the OS and GUI. In headless mode the script pushes this to ~90% GPU allocation, leaving only ~2–3 GB for the minimal OS footprint.

| Total RAM | Headless VRAM Limit | OS Reserved |
|-----------|---------------------|-------------|
| 16 GB     | 13 GB (13,312 MB)   | ~3 GB       |
| 24 GB     | 20 GB (20,480 MB)   | ~4 GB       |
| 32 GB     | 28 GB (28,672 MB)   | ~4 GB       |
| 48 GB     | 44 GB (45,056 MB)   | ~4 GB       |
| 64 GB     | 60 GB (61,440 MB)   | ~4 GB       |
| 96 GB     | 91 GB (93,184 MB)   | ~5 GB       |
| 128 GB    | 122 GB (124,928 MB) | ~6 GB       |
| 256 GB    | 248 GB (253,952 MB) | ~8 GB       |
| 512 GB    | 504 GB (516,096 MB) | ~8 GB       |

The limit is applied immediately via `sysctl`, persisted in `/etc/sysctl.conf`, and enforced at boot via a `LaunchDaemon` (`com.local.wiredmem`).

---

### Disabled Services

The following background processes are disabled to free RAM and CPU for inference:

| Service                                            | Purpose                     |
|----------------------------------------------------|-----------------------------|
| `com.apple.photoanalysisd`                         | Photo analysis / ML tagging |
| `com.apple.suggestd`                               | Siri suggestions            |
| `com.apple.parsecd`                                | Universal links parsing     |
| `com.apple.knowledge-agent`                        | Siri knowledge base         |
| `com.apple.cloudd` / `cloudpaird` / `cloudphotod`  | iCloud sync                 |
| `com.apple.iCloudHelper` / `com.apple.bird`        | iCloud Drive                |
| `com.apple.coreduetd`                              | Spotlight data aggregation  |
| `com.apple.spotlight.IndexAgent`                   | Spotlight indexing          |
| `com.apple.Siri` / `siriknowledged` / `assistantd` | Siri                        |
| `com.apple.helpd`                                  | Help centre                 |
| `com.apple.screensharing`                          | Screen sharing              |
| `com.apple.AirPlayXPCHelper`                       | AirPlay                     |
| `com.apple.UsageTrackingAgent`                     | Screen Time tracking        |
| `com.apple.PrivacyAnalyticsUtility`                | Privacy analytics           |

Additionally:
- **Spotlight indexing** is disabled system-wide (`mdutil -a -i off`)
- **App Nap** is disabled globally (`NSAppSleepDisabled`)
- **Automatic software updates** are turned off

**Power management** (`pmset`) is configured as:

| Setting                       | Value      |
|-------------------------------|------------|
| System sleep                  | Disabled   |
| Display sleep                 | Disabled   |
| Disk sleep                    | Disabled   |
| Auto-restart on power failure | Enabled    |
| Auto-restart on kernel panic  | 15 seconds |
| Wake on network access        | Enabled    |

---

### Ollama Configuration

A production `LaunchDaemon` (`com.ollama.headless`) is installed that starts Ollama automatically on boot with the following performance flags:

| Environment Variable       | Value                        | Effect                                                                                |
|----------------------------|------------------------------|---------------------------------------------------------------------------------------|
| `OLLAMA_HOST`              | `0.0.0.0:11434`              | Binds to all interfaces — accessible from LAN / Tailscale                             |
| `OLLAMA_FLASH_ATTENTION`   | `1`                          | Enables Flash Attention on Metal, cutting prefill latency 2–3× on long prompts        |
| `OLLAMA_KV_CACHE_TYPE`     | `q8_0`                       | Quantises the KV cache to 8-bit, saving ~50% context RAM with negligible quality loss |
| `OLLAMA_KEEP_ALIVE`        | `-1`                         | Keeps the model pinned in memory indefinitely — no reload delay between requests      |
| `OLLAMA_NUM_PARALLEL`      | `1` (≤64 GB) / `2` (128 GB+) | Concurrent request slots — tuned per RAM tier                                         |
| `OLLAMA_MAX_LOADED_MODELS` | `1`                          | Prevents multiple models competing for RAM                                            |

Logs are written to:
- `stdout` → `/var/log/ollama.log`
- `stderr` → `/var/log/ollama.err`

---

### Homebrew

If Homebrew is not already installed, the script installs it non-interactively. It then appends the following block to `~/.zshrc` (only if not already present):

```zsh
# >>> Homebrew (added by headless-ai-mac setup) >>>
eval "$(/opt/homebrew/bin/brew shellenv)"
# <<< Homebrew <<<
```

This ensures `brew`, `ollama`, and `tailscale` are available in all future shell sessions.

---

### Tailscale & Remote Access

[Tailscale](https://tailscale.com) creates an encrypted WireGuard mesh network, giving you a stable private IP for the Mac regardless of where it or you are physically located.

The script:
1. Installs the Tailscale macOS app via `brew install --cask tailscale`
2. Opens the app for you to sign in via the menu bar

Once connected, you can access the Mac from any device on your Tailscale network:

```bash
# SSH into the Mac
ssh username@<tailscale-ip>

# Access Ollama API remotely
curl http://<tailscale-ip>:11434/api/tags
```

SSH (Remote Login) is also enabled by the script via `systemsetup -setremotelogin on`.

---

## After Setup

### Pulling a Model

The script does not pull a model — that choice is left to you. After setup, SSH into the Mac (or open a terminal) and pull whichever model fits your RAM:

```bash
ollama pull <model-name>
```

**Recommended models by RAM tier:**

| RAM     | Recommended Model     | Size   |
|---------|-----------------------|--------|
| 16 GB   | `qwen3.6:27b` (4-bit) | ~17 GB |
| 32 GB   | `qwen3.8:27b-q4_K_M`  | ~18 GB |
| 64 GB   | `qwen3.8:27b-q8_0`    | ~30 GB |
| 128 GB  | `qwen3.8:27b-mxfp8`   | ~32 GB |
| 256 GB+ | `qwen3.8:27b-bf16`    | ~56 GB |

Browse all available models at [ollama.com/search](https://ollama.com/search).

---

### Useful Commands

```bash
# Check Ollama is running
sudo launchctl list | grep ollama

# Follow Ollama logs
tail -f /var/log/ollama.log

# List loaded models
ollama list

# Check current VRAM limit
sysctl iogpu.wired_limit_mb

# Test the API
curl http://localhost:11434/api/tags

# Chat with a model (CLI)
ollama run <model-name>

# Stop / restart the Ollama daemon
sudo launchctl stop com.ollama.headless
sudo launchctl start com.ollama.headless
```

---

### Connecting an Agent or Client

Ollama exposes an **OpenAI-compatible API** at `http://<mac-ip>:11434/v1`. Any tool that supports a custom OpenAI base URL can connect to it.

**Examples:**

```bash
# OpenAI Python SDK
from openai import OpenAI
client = OpenAI(base_url="http://<mac-ip>:11434/v1", api_key="ollama")

# curl
curl http://<mac-ip>:11434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "qwen3.8:27b-q4_K_M", "messages": [{"role": "user", "content": "Hello"}]}'
```

Compatible tools include: **Continue**, **Open WebUI**, **Cursor**, **VS Code Copilot**, **LangChain**, **llama-index**, **AnythingLLM**, and more.

---

## Connecting a Monitor Later

Nothing the script does prevents you from connecting a monitor. macOS will detect it and the GUI will resume normally. The headless optimisations simply reduce background overhead — they are not destructive.

With a monitor connected you may notice:
- The display never sleeps (pmset setting) — adjust with `sudo pmset -a displaysleep 10`
- Spotlight doesn't return results (indexing is off) — run `sudo mdutil -a -i on` to re-enable
- Some system features (Siri, iCloud) are off — re-enable in **System Settings**

To fully restore all macOS defaults in one step, see the section below.

---

## Reverting Everything

Run the restore flag to undo all changes made by the script:

```bash
sudo python3 headless-ai-mac.py --restore
```

**What gets restored:**

| Setting                       | Restored Value                                               |
|-------------------------------|--------------------------------------------------------------|
| System / display / disk sleep | macOS defaults (1 min display, 10 min disk)                  |
| VRAM limit                    | Reset to macOS dynamic allocation (`iogpu.wired_limit_mb=0`) |
| VRAM LaunchDaemon             | Removed                                                      |
| `/etc/sysctl.conf` entry      | Removed                                                      |
| Spotlight indexing            | Re-enabled (`mdutil -a -i on`)                               |
| Background launch agents      | Re-enabled                                                   |
| App Nap                       | Re-enabled                                                   |
| Siri, iCloud, analytics       | Restored to defaults                                         |
| Automatic updates             | Re-enabled                                                   |
| Ollama daemon                 | Optionally disabled (Ollama stays installed)                 |

> **Homebrew, Ollama, and Tailscale are not removed** — they are useful in desktop mode too. Restart the Mac after restoring for all changes to take full effect.

---

## What Is NOT Changed

- No apps are deleted or modified
- No user data is touched
- No network firewall rules are changed
- No system files outside of `/etc/sysctl.conf` and `/Library/LaunchDaemons/` are written
- `~/.zshrc` is only **appended to** (never overwritten), and only if the entry isn't already present
- The script is fully **idempotent** — safe to run multiple times
