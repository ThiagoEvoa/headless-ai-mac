#!/usr/bin/env python3
"""
Headless AI Mac Setup Script
Detects Apple Silicon configuration and applies optimized settings for local AI inference.
Includes: Ollama setup, VRAM tuning, sleep prevention, unnecessary app disabling, and Tailscale.
"""

import subprocess
import sys
import os
import re
import json
import platform
import urllib.request
import tempfile
from pathlib import Path

# ─── ANSI colors ──────────────────────────────────────────────────────────────
RED    = "\033[91m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
BLUE   = "\033[94m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def header(msg):   print(f"\n{BOLD}{BLUE}{'─'*60}{RESET}\n{BOLD}{CYAN}{msg}{RESET}\n{'─'*60}")
def info(msg):     print(f"  {GREEN}✔{RESET}  {msg}")
def warn(msg):     print(f"  {YELLOW}⚠{RESET}  {msg}")
def error(msg):    print(f"  {RED}✘{RESET}  {msg}")
def step(msg):     print(f"  {BLUE}→{RESET}  {msg}")

# ─── Helpers ──────────────────────────────────────────────────────────────────

def run(cmd, sudo=False, check=True, capture=False):
    if sudo and os.geteuid() != 0:
        cmd = ["sudo"] + (cmd if isinstance(cmd, list) else cmd.split())
    elif isinstance(cmd, str):
        cmd = cmd.split()
    result = subprocess.run(cmd, capture_output=capture, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{result.stderr}")
    return result

def run_capture(cmd, sudo=False):
    return run(cmd, sudo=sudo, capture=True, check=False).stdout.strip()

def confirm(msg, default="y"):
    resp = input(f"\n  {YELLOW}?{RESET}  {msg} [{default.upper() if default=='y' else 'y'}/{default.upper() if default=='n' else 'N'}]: ").strip().lower()
    return resp in ("y", "yes", "") if default == "y" else resp in ("y", "yes")

def require_sudo():
    if os.geteuid() != 0:
        step("This script requires sudo for system-level changes.")
        step("Re-running with sudo...")
        os.execvp("sudo", ["sudo", sys.executable] + sys.argv)

# ─── Detection ────────────────────────────────────────────────────────────────

def detect_hardware():
    """Detect Apple Silicon chip and RAM."""
    if platform.system() != "Darwin":
        error("This script is for macOS only.")
        sys.exit(1)

    chip_raw = run_capture("sysctl -n machdep.cpu.brand_string")
    if not chip_raw:
        chip_raw = run_capture("system_profiler SPHardwareDataType").split("\n")
        chip_raw = next((l.split(":")[1].strip() for l in chip_raw if "Chip" in l), "Unknown")

    # Detect RAM in GB
    mem_bytes = int(run_capture("sysctl -n hw.memsize"))
    ram_gb = mem_bytes // (1024 ** 3)

    # Detect chip generation (M1/M2/M3/M4/M5) and tier (base/Pro/Max/Ultra)
    chip_gen = "unknown"
    chip_tier = "base"
    chip_match = re.search(r"Apple (M\d+)( Pro| Max| Ultra)?", chip_raw, re.IGNORECASE)
    if chip_match:
        chip_gen  = chip_match.group(1).upper()   # e.g. "M4"
        chip_tier = (chip_match.group(2) or "base").strip().lower()

    return {
        "chip_raw": chip_raw,
        "chip_gen": chip_gen,
        "chip_tier": chip_tier,
        "ram_gb": ram_gb,
    }

def headless_vram_limit_mb(ram_gb):
    """Return aggressive headless VRAM limit in MB (~90% of RAM, leaving ~2-3 GB for OS)."""
    limits = {
        16:  13312,
        24:  20480,
        32:  28672,
        36:  32768,
        48:  45056,
        64:  61440,
        96:  93184,
        128: 124928,
        192: 188416,
        256: 253952,
        384: 376832,
        512: 516096,
    }
    # Find nearest key ≤ ram_gb
    keys = sorted(k for k in limits if k <= ram_gb)
    best = keys[-1] if keys else sorted(limits)[0]
    return limits[best]

# ─── Step 1 – Print detected configuration ────────────────────────────────────

def print_summary(hw):
    header("Detected Hardware Configuration")
    info(f"Chip   : {hw['chip_raw']}")
    info(f"Gen    : {hw['chip_gen']} ({hw['chip_tier'].title()})")
    info(f"RAM    : {hw['ram_gb']} GB Unified Memory")
    vram = headless_vram_limit_mb(hw["ram_gb"])
    info(f"VRAM   : {vram} MB ({vram/1024:.1f} GB) headless limit")
    return vram

# ─── Step 2 – Disable unnecessary services & apps ─────────────────────────────

LAUNCH_AGENTS_TO_DISABLE = [
    "com.apple.photoanalysisd",
    "com.apple.suggestd",
    "com.apple.parsecd",
    "com.apple.knowledge-agent",
    "com.apple.cloudd",
    "com.apple.cloudpaird",
    "com.apple.cloudphotod",
    "com.apple.iCloudHelper",
    "com.apple.bird",                  # iCloud Drive
    "com.apple.coreduetd",             # Spotlight suggestions data
    "com.apple.spotlight.IndexAgent",
    "com.apple.Siri",
    "com.apple.siriknowledged",
    "com.apple.assistantd",
    "com.apple.macos.studentd",
    "com.apple.helpd",
    "com.apple.screensharing",
    "com.apple.AirPlayXPCHelper",
    "com.apple.UsageTrackingAgent",
    "com.apple.PrivacyAnalyticsUtility",
    "com.apple.diagnosticextensions.osx.nsurlsessiond",
]

SYSTEM_PREFS_TO_SET = [
    # Disable Spotlight indexing
    ("com.apple.Spotlight", "useCount", "-int 0"),
    # Disable Siri
    ("com.apple.assistant.support", "Assistant Enabled", "-bool false"),
    # Disable Analytics
    ("com.apple.SubmitDiagInfo", "AutoSubmit", "-bool false"),
    # Disable App Nap globally
    ("NSGlobalDomain", "NSAppSleepDisabled", "-bool YES"),
    # Disable automatic app updates
    ("com.apple.SoftwareUpdate", "AutomaticCheckEnabled", "-bool false"),
    ("com.apple.SoftwareUpdate", "AutomaticDownload", "-bool false"),
    ("com.apple.commerce", "AutoUpdate", "-bool false"),
]

def disable_unnecessary_services():
    header("Disabling Unnecessary Services & Background Apps")

    # Power management – prevent all sleep
    step("Configuring power management (no sleep / auto-restart)...")
    pmset_cmds = [
        ["pmset", "-a", "sleep", "0"],
        ["pmset", "-a", "displaysleep", "0"],
        ["pmset", "-a", "disksleep", "0"],
        ["pmset", "-a", "disablesleep", "1"],
        ["pmset", "-a", "autorestart", "1"],
        ["pmset", "-a", "panicrestart", "15"],
        ["pmset", "-a", "womp", "1"],        # Wake on network access
        ["pmset", "-a", "lidwake", "0"],     # Don't wake on lid (headless)
    ]
    for cmd in pmset_cmds:
        try:
            run(cmd, sudo=True)
        except Exception as e:
            warn(f"pmset: {e}")
    info("Power management configured.")

    # Disable Spotlight indexing on root volume
    step("Disabling Spotlight indexing...")
    try:
        run(["mdutil", "-a", "-i", "off"], sudo=True)
        info("Spotlight indexing disabled.")
    except Exception as e:
        warn(f"mdutil: {e}")

    # Disable Launch Agents
    step("Disabling non-essential Launch Agents...")
    for agent in LAUNCH_AGENTS_TO_DISABLE:
        for domain in ["user", "system"]:
            try:
                r = run(["launchctl", "disable", f"{domain}/{agent}"], sudo=(domain=="system"), check=False, capture=True)
                if r.returncode == 0:
                    info(f"Disabled: {agent} ({domain})")
            except Exception:
                pass

    # System defaults
    step("Applying system defaults (Siri, analytics, App Nap)...")
    for domain, key, value_str in SYSTEM_PREFS_TO_SET:
        tokens = value_str.split()
        kind   = tokens[0]
        val    = tokens[1]
        try:
            run(["defaults", "write", domain, key, kind, val], check=False)
        except Exception:
            pass
    info("System defaults applied.")

    # Disable WindowServer/GUI login items (headless – no GUI)
    step("Setting automatic login and headless mode hints...")
    try:
        run(["defaults", "write", "com.apple.loginwindow", "autoLoginUser", "-string", os.environ.get("USER", "")], check=False)
        run(["defaults", "write", "com.apple.loginwindow", "DisableScreenLock", "-bool", "true"], check=False)
    except Exception:
        pass
    info("Login window configured for headless auto-login.")

# ─── Step 3 – VRAM allocation ─────────────────────────────────────────────────

def configure_vram(vram_mb, ram_gb):
    header("Configuring GPU VRAM Allocation")

    # Apply immediately
    step(f"Setting iogpu.wired_limit_mb = {vram_mb} ({vram_mb/1024:.1f} GB)...")
    try:
        run(["sysctl", f"iogpu.wired_limit_mb={vram_mb}"], sudo=True)
        info(f"VRAM limit applied: {vram_mb} MB")
    except Exception as e:
        warn(f"sysctl (new): {e}")
        # Fallback: legacy param (bytes)
        vram_bytes = vram_mb * 1024 * 1024
        try:
            run(["sysctl", f"iogpu.wired_mem_limit={vram_bytes}"], sudo=True)
            info(f"VRAM limit applied (legacy param): {vram_bytes} bytes")
        except Exception as e2:
            error(f"Could not set VRAM limit: {e2}")

    # Persist via /etc/sysctl.conf
    step("Persisting VRAM limit across reboots (/etc/sysctl.conf)...")
    sysctl_conf = Path("/etc/sysctl.conf")
    marker = "iogpu.wired_limit_mb="
    try:
        lines = sysctl_conf.read_text().splitlines() if sysctl_conf.exists() else []
        lines = [l for l in lines if not l.startswith(marker)]
        lines.append(f"{marker}{vram_mb}")
        sysctl_conf.write_text("\n".join(lines) + "\n")
        info("VRAM limit persisted in /etc/sysctl.conf")
    except Exception as e:
        warn(f"Could not write /etc/sysctl.conf: {e}")

    # LaunchDaemon for guaranteed boot-time application
    step("Installing LaunchDaemon for boot-time VRAM limit...")
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.local.wiredmem</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/sbin/sysctl</string>
        <string>iogpu.wired_limit_mb={vram_mb}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
"""
    plist_path = Path("/Library/LaunchDaemons/com.local.wiredmem.plist")
    try:
        plist_path.write_text(plist)
        run(["chown", "root:wheel", str(plist_path)], sudo=True)
        run(["chmod", "644", str(plist_path)], sudo=True)
        run(["launchctl", "load", "-w", str(plist_path)], sudo=True, check=False)
        info("LaunchDaemon installed: com.local.wiredmem")
    except Exception as e:
        warn(f"LaunchDaemon install failed: {e}")

# ─── Step 4 – Install Homebrew ────────────────────────────────────────────────

ZSHRC = Path.home() / ".zshrc"

BREW_SHELL_BLOCK = """\
# >>> Homebrew (added by headless-ai-mac setup) >>>
eval "$(/opt/homebrew/bin/brew shellenv)"
# <<< Homebrew <<<
"""

def append_to_zshrc(block, marker):
    """Append a block to ~/.zshrc only if the marker line isn't already present."""
    existing = ZSHRC.read_text() if ZSHRC.exists() else ""
    if marker in existing:
        info(f"~/.zshrc already contains: {marker}")
        return
    with ZSHRC.open("a") as f:
        f.write(f"\n{block}")
    info(f"Appended to ~/.zshrc: {marker}")

def install_homebrew():
    header("Homebrew")
    brew_path = run_capture("which brew")
    if not brew_path:
        # Check standard locations in case brew isn't in PATH yet
        for prefix in ["/opt/homebrew/bin", "/usr/local/bin"]:
            if Path(f"{prefix}/brew").exists():
                brew_path = f"{prefix}/brew"
                os.environ["PATH"] = f"{prefix}:{os.environ['PATH']}"
                break

    if brew_path:
        info(f"Homebrew already installed: {brew_path}")
        # Still ensure shellenv is in .zshrc for future sessions
        append_to_zshrc(BREW_SHELL_BLOCK, "brew shellenv")
        return brew_path

    step("Homebrew not found. Installing now (required for Ollama & Tailscale)...")
    try:
        env = os.environ.copy()
        env["NONINTERACTIVE"] = "1"
        subprocess.run(
            '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"',
            shell=True, env=env, check=True
        )
        # Add to PATH for this session
        for prefix in ["/opt/homebrew/bin", "/usr/local/bin"]:
            if Path(f"{prefix}/brew").exists():
                os.environ["PATH"] = f"{prefix}:{os.environ['PATH']}"
                brew_path = f"{prefix}/brew"
                break
        if brew_path:
            info(f"Homebrew installed: {brew_path}")
            append_to_zshrc(BREW_SHELL_BLOCK, "brew shellenv")
            return brew_path
        else:
            error("Homebrew installed but binary not found in expected locations.")
            return None
    except Exception as e:
        error(f"Homebrew install failed: {e}")
        return None

# ─── Step 5 – Install & configure Ollama ─────────────────────────────────────

def install_ollama(brew_path):
    header("Ollama Installation")
    ollama_bin = run_capture("which ollama")
    if ollama_bin:
        version = run_capture("ollama --version")
        info(f"Ollama already installed: {version}")
        return True
    if not brew_path:
        error("Homebrew unavailable. Cannot install Ollama.")
        step("Download manually from https://ollama.com/download/mac")
        return False
    step("Installing Ollama via Homebrew...")
    try:
        run([brew_path, "install", "ollama"])
        info("Ollama installed via Homebrew.")
        return True
    except Exception as e:
        error(f"Ollama install failed: {e}")
        return False

def configure_ollama_launchd(ram_gb):
    header("Configuring Ollama LaunchDaemon (Production Auto-Start)")

    num_parallel = "2" if ram_gb >= 128 else "1"
    ollama_bin = run_capture("which ollama") or "/usr/local/bin/ollama"

    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.ollama.headless</string>
    <key>ProgramArguments</key>
    <array>
        <string>{ollama_bin}</string>
        <string>serve</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>OLLAMA_HOST</key>
        <string>0.0.0.0:11434</string>
        <key>OLLAMA_FLASH_ATTENTION</key>
        <string>1</string>
        <key>OLLAMA_KV_CACHE_TYPE</key>
        <string>q8_0</string>
        <key>OLLAMA_KEEP_ALIVE</key>
        <string>-1</string>
        <key>OLLAMA_NUM_PARALLEL</key>
        <string>{num_parallel}</string>
        <key>OLLAMA_MAX_LOADED_MODELS</key>
        <string>1</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/var/log/ollama.log</string>
    <key>StandardErrorPath</key>
    <string>/var/log/ollama.err</string>
    <key>ProcessType</key>
    <string>Interactive</string>
</dict>
</plist>
"""
    plist_path = Path("/Library/LaunchDaemons/com.ollama.headless.plist")
    try:
        if plist_path.exists():
            run(["launchctl", "unload", str(plist_path)], sudo=True, check=False)
        plist_path.write_text(plist)
        run(["chown", "root:wheel", str(plist_path)], sudo=True)
        run(["chmod", "644", str(plist_path)], sudo=True)
        run(["launchctl", "load", "-w", str(plist_path)], sudo=True)
        info("Ollama LaunchDaemon installed and started.")
        info(f"  OLLAMA_HOST           = 0.0.0.0:11434")
        info(f"  OLLAMA_FLASH_ATTENTION = 1")
        info(f"  OLLAMA_KV_CACHE_TYPE  = q8_0")
        info(f"  OLLAMA_KEEP_ALIVE     = -1 (always loaded)")
        info(f"  OLLAMA_NUM_PARALLEL   = {num_parallel}")
        info(f"  Logs → /var/log/ollama.log")
    except Exception as e:
        error(f"LaunchDaemon setup failed: {e}")

# ─── Step 6 – Tailscale ───────────────────────────────────────────────────────

def install_tailscale(brew_path):
    header("Tailscale – Remote Access")
    if not confirm("Install Tailscale for secure remote access?"):
        warn("Skipping Tailscale.")
        return

    ts_bin = run_capture("which tailscale")
    if ts_bin:
        info("Tailscale already installed.")
    else:
        if not brew_path:
            error("Homebrew unavailable. Download Tailscale from https://tailscale.com/download/mac")
            return
        step("Installing Tailscale via Homebrew Cask...")
        try:
            run([brew_path, "install", "--cask", "tailscale"])
            info("Tailscale installed.")
        except Exception as e:
            error(f"Tailscale install failed: {e}")
            step("Download manually from https://tailscale.com/download/mac")
            return

    step("Enabling Tailscale via launchctl...")
    ts_app = Path("/Applications/Tailscale.app")
    if ts_app.exists():
        subprocess.run(["open", "-a", "Tailscale"], check=False)
        info("Tailscale app opened. Complete login in the menu bar icon.")
    else:
        step("Start Tailscale manually: open -a Tailscale  (or: tailscale up)")

    info("Tip: once connected, access this Mac by hostname or Tailscale IP.")
    info("Tip: enable SSH on this Mac (System Settings → General → Sharing → Remote Login).")

# ─── Step 7 – SSH hardening reminder ──────────────────────────────────────────

def enable_ssh():
    header("SSH / Remote Login")
    step("Enabling Remote Login (SSH)...")
    try:
        run(["systemsetup", "-setremotelogin", "on"], sudo=True)
        info("SSH (Remote Login) enabled.")
    except Exception as e:
        warn(f"Could not enable SSH automatically: {e}")
        step("Enable manually: System Settings → General → Sharing → Remote Login")

# ─── Step 8 – Print final summary ─────────────────────────────────────────────

def print_final_summary(hw, vram_mb):
    header("Setup Complete – Configuration Summary")
    print(f"""
  {BOLD}Hardware:{RESET}
    Chip         : {hw['chip_raw']}
    RAM          : {hw['ram_gb']} GB
    VRAM limit   : {vram_mb} MB  ({vram_mb/1024:.1f} GB headless aggressive)

  {BOLD}Ollama:{RESET}
    Service      : com.ollama.headless (auto-start, keep-alive)
    API          : http://0.0.0.0:11434  (OpenAI-compatible /v1)
    Flash Attn   : ON
    KV Cache     : q8_0 (quantised, ~50% RAM savings)
    Keep Alive   : ∞ (never unloads)
    Logs         : /var/log/ollama.log

  {BOLD}Power:{RESET}
    Sleep        : DISABLED (pmset)
    VRAM daemon  : com.local.wiredmem (boot-time)

  {BOLD}Useful commands:{RESET}
    ollama pull <model>              # pull a model of your choice
    tail -f /var/log/ollama.log
    sudo launchctl list | grep ollama
    sysctl iogpu.wired_limit_mb
    ollama list
    curl http://localhost:11434/api/tags

  {BOLD}To restore macOS defaults (e.g. when connecting a monitor):{RESET}
    sudo python3 headless-ai-mac.py --restore
""")

# ─── Restore mode ─────────────────────────────────────────────────────────────

RESTORE_LAUNCH_AGENTS = [
    "com.apple.photoanalysisd",
    "com.apple.suggestd",
    "com.apple.parsecd",
    "com.apple.knowledge-agent",
    "com.apple.cloudd",
    "com.apple.cloudpaird",
    "com.apple.cloudphotod",
    "com.apple.iCloudHelper",
    "com.apple.bird",
    "com.apple.coreduetd",
    "com.apple.spotlight.IndexAgent",
    "com.apple.Siri",
    "com.apple.siriknowledged",
    "com.apple.assistantd",
    "com.apple.macos.studentd",
    "com.apple.helpd",
    "com.apple.screensharing",
    "com.apple.AirPlayXPCHelper",
    "com.apple.UsageTrackingAgent",
    "com.apple.PrivacyAnalyticsUtility",
    "com.apple.diagnosticextensions.osx.nsurlsessiond",
]

def restore():
    print(f"\n{BOLD}{YELLOW}╔══════════════════════════════════════════════════════╗{RESET}")
    print(f"{BOLD}{YELLOW}║        Restoring macOS Defaults (Desktop Mode)       ║{RESET}")
    print(f"{BOLD}{YELLOW}╚══════════════════════════════════════════════════════╝{RESET}\n")

    if not confirm("This will revert all headless optimisations to macOS defaults. Continue?"):
        warn("Restore aborted.")
        sys.exit(0)

    # 1. Restore power management defaults
    header("Restoring Power Management")
    pmset_cmds = [
        ["pmset", "-a", "sleep", "1"],
        ["pmset", "-a", "displaysleep", "10"],
        ["pmset", "-a", "disksleep", "10"],
        ["pmset", "-a", "disablesleep", "0"],
        ["pmset", "-a", "autorestart", "0"],
        ["pmset", "-a", "lidwake", "1"],
    ]
    for cmd in pmset_cmds:
        try:
            run(cmd, sudo=True)
        except Exception as e:
            warn(f"pmset: {e}")
    info("Power management restored to defaults.")

    # 2. Reset VRAM limit to macOS dynamic allocation
    header("Resetting VRAM Allocation")
    try:
        run(["sysctl", "iogpu.wired_limit_mb=0"], sudo=True)
        info("VRAM limit reset to macOS dynamic allocation.")
    except Exception as e:
        warn(f"sysctl reset: {e}")

    # Remove from /etc/sysctl.conf
    sysctl_conf = Path("/etc/sysctl.conf")
    if sysctl_conf.exists():
        try:
            lines = [l for l in sysctl_conf.read_text().splitlines()
                     if not l.startswith("iogpu.wired_limit_mb=")]
            sysctl_conf.write_text("\n".join(lines) + "\n")
            info("Removed VRAM entry from /etc/sysctl.conf")
        except Exception as e:
            warn(f"Could not update /etc/sysctl.conf: {e}")

    # Unload and remove VRAM LaunchDaemon
    vram_plist = Path("/Library/LaunchDaemons/com.local.wiredmem.plist")
    if vram_plist.exists():
        try:
            run(["launchctl", "unload", str(vram_plist)], sudo=True, check=False)
            vram_plist.unlink()
            info("Removed LaunchDaemon: com.local.wiredmem")
        except Exception as e:
            warn(f"Could not remove VRAM daemon: {e}")

    # 3. Re-enable Spotlight
    header("Re-enabling Spotlight")
    try:
        run(["mdutil", "-a", "-i", "on"], sudo=True)
        info("Spotlight indexing re-enabled.")
    except Exception as e:
        warn(f"mdutil: {e}")

    # 4. Re-enable Launch Agents
    header("Re-enabling Background Services")
    for agent in RESTORE_LAUNCH_AGENTS:
        for domain in ["user", "system"]:
            try:
                run(["launchctl", "enable", f"{domain}/{agent}"],
                    sudo=(domain == "system"), check=False, capture=True)
            except Exception:
                pass
    info("Launch agents re-enabled.")

    # 5. Restore system defaults
    header("Restoring System Defaults")
    restore_defaults = [
        ("com.apple.assistant.support", "Assistant Enabled", "-bool true"),
        ("com.apple.SubmitDiagInfo",    "AutoSubmit",        "-bool true"),
        ("NSGlobalDomain",              "NSAppSleepDisabled", "-bool NO"),
        ("com.apple.SoftwareUpdate",    "AutomaticCheckEnabled", "-bool true"),
        ("com.apple.SoftwareUpdate",    "AutomaticDownload",     "-bool true"),
        ("com.apple.commerce",          "AutoUpdate",            "-bool true"),
    ]
    for domain, key, value_str in restore_defaults:
        tokens = value_str.split()
        try:
            run(["defaults", "write", domain, key, tokens[0], tokens[1]], check=False)
        except Exception:
            pass
    info("System defaults restored.")

    # 6. Stop Ollama LaunchDaemon (leave installed, just stop auto-start)
    header("Ollama Service")
    ollama_plist = Path("/Library/LaunchDaemons/com.ollama.headless.plist")
    if ollama_plist.exists():
        if confirm("Disable Ollama auto-start daemon? (ollama will still be installed)"):
            try:
                run(["launchctl", "unload", "-w", str(ollama_plist)], sudo=True, check=False)
                info("Ollama auto-start disabled. Run 'ollama serve' manually when needed.")
            except Exception as e:
                warn(f"Could not disable Ollama daemon: {e}")
        else:
            info("Ollama daemon left running.")
    else:
        info("No Ollama daemon found — nothing to change.")

    header("Restore Complete")
    print(f"""
  {BOLD}What was restored:{RESET}
    ✔  Sleep / display sleep re-enabled (pmset defaults)
    ✔  VRAM limit reset to macOS dynamic allocation
    ✔  Spotlight indexing re-enabled
    ✔  Background launch agents re-enabled
    ✔  App Nap, Siri, iCloud, analytics defaults restored
    ✔  VRAM LaunchDaemon removed

  {BOLD}Note:{RESET}
    Homebrew, Ollama, and Tailscale remain installed.
    Plug in your monitor and restart to apply all changes cleanly.
""")

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print(f"\n{BOLD}{CYAN}╔══════════════════════════════════════════════════════╗{RESET}")
    print(f"{BOLD}{CYAN}║      Headless AI Mac Setup  –  Apple Silicon         ║{RESET}")
    print(f"{BOLD}{CYAN}╚══════════════════════════════════════════════════════╝{RESET}\n")

    if platform.system() != "Darwin":
        error("macOS required. Exiting.")
        sys.exit(1)

    require_sudo()

    if "--restore" in sys.argv:
        restore()
        sys.exit(0)

    hw = detect_hardware()
    vram_mb = print_summary(hw)

    if not confirm("\nProceed with full setup?"):
        warn("Aborted.")
        sys.exit(0)

    disable_unnecessary_services()
    configure_vram(vram_mb, hw["ram_gb"])
    brew_path = install_homebrew()
    ollama_ok = install_ollama(brew_path)
    if ollama_ok:
        configure_ollama_launchd(hw["ram_gb"])
    enable_ssh()
    install_tailscale(brew_path)
    print_final_summary(hw, vram_mb)

if __name__ == "__main__":
    main()
