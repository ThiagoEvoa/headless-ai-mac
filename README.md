# 🧠 Headless AI Mac

A Python script that automatically detects your Apple Silicon Mac's hardware configuration and applies a fully optimised setup for running local AI inference — headless, always-on, and accessible remotely.

Designed for **Mac Mini**, **Mac Studio**, and **MacBook** running as a dedicated AI server with no monitor attached.

---

## Table of Contents

- [Why Headless?](#why-headless)
- [What the Script Does](#what-the-script-does)
- [Requirements](#requirements)
- [Prerequisites](#prerequisites)
- [Usage](#usage)
  - [Setup](#setup)
  - [Repair Ollama Only](#repair-ollama-only)
  - [Restore (Desktop Mode)](#restore-desktop-mode)
- [What Gets Configured](#what-gets-configured)
  - [Hardware Detection](#hardware-detection)
  - [VRAM Allocation Table](#vram-allocation-table)
  - [Disabled Services](#disabled-services)
  - [Ollama Configuration](#ollama-configuration)
  - [Homebrew](#homebrew)
  - [Enabling Remote Access (SSH) — manual](#enabling-remote-access-ssh--manual)
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
| **Ollama**      | Validates an existing Ollama install, then applies a `launchd` daemon with production performance flags |
| **SSH**         | Reminds user to enable Remote Login manually — the script cannot enable it automatically |

> **The script does not install Ollama.** It expects the Ollama binary to already be present and only writes the daemon configuration. A prerequisite check runs first and aborts the run if any required binary is missing.


---

## Requirements

- **macOS** on Apple Silicon (M1, M2, M3, M4, M5 — any tier)
- **Python 3** (pre-installed on macOS)
- **`sudo` privileges**

No third-party Python packages are required — the script uses only the standard library.

---

## Prerequisites

The script **does not install** any user-facing applications. It validates that the following binaries are already available on the system before making any changes. If a binary is missing, the run aborts with an install hint.

| Binary       | Why required | Install manually if missing                                             |
|-----------|--------------|----------------------------------------------------------------------|
| `ollama`     | Local inference server the daemon manages | `brew install ollama`     — or download from [ollama.com/download/mac](https://ollama.com/download/mac) |

Homebrew is **installed automatically** by the script if missing — it is not a manual prerequisite. Only `ollama` must be pre-installed.

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
2. Run a **prerequisite check** — if Ollama (or another required binary) is missing, it aborts here and tells you how to install it.
3. Walk through each phase, showing progress for every step.
4. Verify the Ollama daemon is running and owns port `11434` before reporting success.
5. Print a final summary with useful commands when complete.

Run setup from the account that owns your models. The script uses `SUDO_USER` to
resolve that account and its home directory, not root's `$HOME`. When running
from a root shell, specify `--user <non-root-account>`.

Before setup, quit the Ollama desktop app and disable its launch-at-login option.
Stop any existing Homebrew/manual Ollama server too. If another server owns port
`11434`, setup aborts **before applying system changes**; it does not kill processes.
An already-running `com.ollama.headless` daemon is allowed and will be restarted.

> Restarting the daemon interrupts active inference.

> **Note:** The script will automatically re-invoke itself with `sudo` if not already running as root.

---

### Repair Ollama Only

For an existing installation, update the script and run:

```bash
sudo python3 headless-ai-mac.py --ollama-only
# From a root shell (or to choose the model-owning account):
sudo python3 headless-ai-mac.py --ollama-only --user <non-root-account>
```

This updates only the Ollama daemon, log permissions, and its launchd enabled
state. It does not change VRAM, power settings, macOS services, or Homebrew.
Existing `OLLAMA_MODELS` from the daemon plist is preserved. Otherwise, the store
is `<account-home>/.ollama/models`. Models are not moved or recursively chowned;
a custom store must already be accessible to the selected account.

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
| `com.apple.AirPlayXPCHelper`                       | AirPlay                     |
| `com.apple.UsageTrackingAgent`                     | Screen Time tracking        |
| `com.apple.PrivacyAnalyticsUtility`                | Privacy analytics           |

**Screen Sharing is preserved.** Headless setup does not disable remote desktop
access or automatically enable it. Configure Screen Sharing (or Remote Management)
and allowed users under **System Settings → General → Sharing**.

Older script versions disabled `com.apple.screensharing`. Updating the script alone
does not undo that previous setting. Enable the service with
`sudo launchctl enable system/com.apple.screensharing`, then configure Sharing in
System Settings. Restore mode retains support for re-enabling the legacy service.

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

> **Ollama is not installed by this script.** The `ollama` binary must already be present. The prerequisite check aborts the run if it is missing — see [Prerequisites](#prerequisites).

A production `LaunchDaemon` (`com.ollama.headless`) is configured to start Ollama automatically on boot **as the selected non-root account**, with the following performance flags:

Configuration file: `/Library/LaunchDaemons/com.ollama.headless.plist`.
Inspect it with:

```bash
sudo plutil -p /Library/LaunchDaemons/com.ollama.headless.plist
```

The script writes `UserName`, explicit `HOME` and `OLLAMA_MODELS`, and creates or
repairs log files owned by that account without truncating existing logs. It uses
checked `launchctl enable`/`bootstrap` commands and waits up to 30 seconds for the
daemon PID to own the API listener. Startup failures exit nonzero rather than
printing “Setup Complete”.

| Environment Variable       | Value                        | Effect                                                                                |
|----------------------------|------------------------------|---------------------------------------------------------------------------------------|
| `HOME`                    | Selected account home        | Required by Ollama when running under launchd                                           |
| `OLLAMA_MODELS`           | Existing configured store, or `<account-home>/.ollama/models` | Reuses your existing model store                               |
| `OLLAMA_HOST`              | `0.0.0.0:11434`              | Binds to all interfaces — accessible from the LAN / over SSH                             |
| `OLLAMA_FLASH_ATTENTION`   | `1`                          | Enables Flash Attention on Metal, cutting prefill latency 2–3× on long prompts        |
| `OLLAMA_KV_CACHE_TYPE`     | `q8_0`                       | Quantises the KV cache to 8-bit, saving ~50% context RAM with negligible quality loss |
| `OLLAMA_KEEP_ALIVE`        | `-1`                         | Keeps an idle model resident until eviction/model switching; requests can override keep-alive      |
| `OLLAMA_NUM_PARALLEL`      | `1` (<128 GB) / `2` (128 GB+) | Concurrent request slots — tuned per RAM tier                                         |
| `OLLAMA_MAX_LOADED_MODELS` | `1`                          | Prevents multiple models competing for RAM                                            |

Logs are written to:
- `stdout` → `/var/log/ollama.log`
- `stderr` → `/var/log/ollama.err`

> `OLLAMA_HOST=0.0.0.0:11434` exposes the API on all network interfaces. Use only
> on a trusted network, or secure access with firewall rules/an authenticated
> proxy. For SSH-only access, bind to `127.0.0.1:11434` instead.

---

### Homebrew

If Homebrew is not already installed, the script installs it non-interactively. It then appends the following block to `~/.zshrc` (only if not already present):

```zsh
# >>> Homebrew (added by headless-ai-mac setup) >>>
eval "$(/opt/homebrew/bin/brew shellenv)"
# <<< Homebrew <<<
```

This ensures `brew` and `ollama` are available in all future shell sessions.

---

### Enabling Remote Access (SSH) — manual

The script **does not** enable SSH. `systemsetup -setremotelogin` needs a user session and fails in this headless context, so Remote Login is a manual step. After setup, enable it yourself:

```bash
# Option A — System Settings
#   General → Sharing → Remote Login   (turn ON)

# Option B — from a terminal
sudo systemsetup -setremotelogin on

# Verify it is on
sudo systemsetup -getremotelogin
```

Then connect over the network from another host:

```bash
ssh <user>@<mac-ip>
```

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

# List installed models
ollama list

# List currently loaded models
ollama ps

# Check current VRAM limit
sysctl iogpu.wired_limit_mb

# Test the API
curl http://localhost:11434/api/tags

# Chat with a model (CLI)
ollama run <model-name>

# Stop / restart the Ollama daemon
# Stop (KeepAlive would otherwise relaunch it)
sudo launchctl bootout system/com.ollama.headless
# Start
sudo launchctl bootstrap system /Library/LaunchDaemons/com.ollama.headless.plist
# Restart a loaded daemon
sudo launchctl kickstart -k system/com.ollama.headless
```

---

### Troubleshooting Ollama Startup

```bash
sudo launchctl print system/com.ollama.headless
sudo lsof -nP -iTCP:11434 -sTCP:LISTEN
sudo tail -n 40 /var/log/ollama.err
```

The daemon should show `state = running`, and its PID must match the port listener.
Saved plist values alone do not prove which server is answering requests.

- `panic: $HOME is not defined`: update the script and run `--ollama-only`.
- `EX_CONFIG` after changing `UserName`: the repair also fixes root-owned log files.
- Two models loaded despite the limit: confirm the desktop app or another server
  is not owning the port. `OLLAMA_NUM_PARALLEL` controls requests per model, not
  the number of loaded models.
- Old panic traces remain in logs: logs are preserved; check the latest timestamps.

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

> **Homebrew and Ollama are not removed** — they are useful in desktop mode too. Restart the Mac after restoring for all changes to take full effect.

---

## What Is NOT Changed

- No apps are deleted or modified
- **No user-facing applications are installed** — only Homebrew is auto-installed; Ollama must be pre-installed manually
- No user data is touched
- No network firewall rules are changed
- No system files outside of `/etc/sysctl.conf` and `/Library/LaunchDaemons/` are written
- `~/.zshrc` is only **appended to** (never overwritten), and only if the entry isn't already present
- The script is fully **idempotent** — safe to run multiple times

---

## Development / Tests

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile headless-ai-mac.py
```

Tests mock privileged commands and use temporary files. They do not modify macOS
services, system configuration, or your models. Real launchd startup still needs
verification on the target Mac.
