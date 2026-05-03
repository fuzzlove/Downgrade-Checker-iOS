#!/usr/bin/env python3
"""
                 .:'
             __ :'__
          .'`__`-'__``.
         :__________.-'
         :_________:
          :_________`-;
           `.__.-.__.'

Apple Downgrade Monitor - Twilio/Notify + Target Watch 
        
       [macOS Daemon Edition]

Install:
  pip3 install requests remotezip

Required:
  ./tools/tsschecker  OR  tsschecker in PATH

##########
Safe secret setup examples:

  export DOWN_EMAIL_USER="xxx@gmail.com"
  export DOWN_EMAIL_PASSWORD="xxx"

  export DOWN_EMAIL_FROM="xxx@gmail.com"
  export DOWN_EMAIL_TO="xxx@mail.xxx"

  export DOWN_ENABLE_NOTIFY=1
  export DOWN_ENABLE_TWILIO=1
  export DOWN_ENABLE_EMAIL=1
  export DOWN_ENABLE_SMS_GATEWAY=1

  export TWILIO_ACCOUNT_SID="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
  export TWILIO_AUTH_TOKEN="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
  export TWILIO_FROM="+5555555555"
  export TWILIO_TO="+15555555555"

Examples:
  python3 down.py
  python3 down.py --mode all
  python3 down.py --mode versions --versions 15.7.1,16.5.1,17.0
  python3 down.py --mode versions --versions 16.5.1 --once
  python3 down.py --test-alerts
  python3 down.py --install-daemon --mode versions --versions 16.5.1,17.0
  python3 down.py --daemon-status
  python3 down.py --uninstall-daemon
##########
"""

from __future__ import annotations

import argparse
import base64
import itertools
import os
import plistlib
import random
import shutil
import smtplib
import sqlite3
import subprocess
import sys
import threading
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import List, Optional, Set, Tuple
from urllib.parse import urlencode

warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL")

try:
    import requests
    from remotezip import RemoteZip
except ImportError as exc:
    print("Missing dependency:", exc)
    print("Install with: pip3 install requests remotezip")
    raise SystemExit(1)


# ============================================================
# CONFIG
# ============================================================

DEVICE_API = "https://api.ipsw.me/v4/devices"
FIRMWARE_API = "https://api.ipsw.me/v4/device/{identifier}?type=ipsw"
APPLE_TSS_SERVER = "https://gs.apple.com/TSS/controller?action=2"

CHECK_INTERVAL = int(os.getenv("DOWN_CHECK_INTERVAL", "300"))
MAX_WORKERS = int(os.getenv("DOWN_MAX_WORKERS", "20"))
RECENT_FIRMWARE_LIMIT = int(os.getenv("DOWN_RECENT_FIRMWARE_LIMIT", "80"))

LOCAL_TSSCHECKER = os.getenv("DOWN_TSSCHECKER", "./tools/tsschecker")
SHOW_VERBOSE_ERRORS = os.getenv("DOWN_VERBOSE_ERRORS", "0") == "1"

BASE_DIR = Path(os.getenv("DOWN_BASE_DIR", "downgrade_cache")).expanduser()
MANIFEST_DIR = BASE_DIR / "buildmanifests"
DB_PATH = BASE_DIR / "downgrades.sqlite3"
LOG_DIR = BASE_DIR / "logs"

BASE_DIR.mkdir(exist_ok=True)
MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

LAUNCHAGENT_LABEL = "com.liquidsky.downgradepartychecker"


# ============================================================
# ALERT CONFIG - use env vars, do not hardcode secrets
# ============================================================

ENABLE_MACOS_NOTIFICATION = os.getenv("DOWN_ENABLE_MACOS_NOTIFICATION", "1") == "1"
ENABLE_MACOS_DIALOG = os.getenv("DOWN_ENABLE_MACOS_DIALOG", "1") == "1"

ENABLE_PROJECTDISCOVERY_NOTIFY = os.getenv("DOWN_ENABLE_NOTIFY", "1") == "1"
PROJECTDISCOVERY_NOTIFY_ID = os.getenv("DOWN_NOTIFY_ID") or None
PROJECTDISCOVERY_NOTIFY_PROVIDER = os.getenv("DOWN_NOTIFY_PROVIDER") or None

ENABLE_EMAIL_ALERTS = os.getenv("DOWN_ENABLE_EMAIL", "0") == "1"
SMTP_HOST = os.getenv("DOWN_SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("DOWN_SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("DOWN_EMAIL_USER", "")
SMTP_PASSWORD = os.getenv("DOWN_EMAIL_PASSWORD", "")
EMAIL_FROM = os.getenv("DOWN_EMAIL_FROM", SMTP_USERNAME)
EMAIL_TO = os.getenv("DOWN_EMAIL_TO", "")

ENABLE_SMS_EMAIL_GATEWAY = os.getenv("DOWN_ENABLE_SMS_GATEWAY", "0") == "1"
SMS_TO = os.getenv("DOWN_SMS_GATEWAY_TO", "")

ENABLE_TWILIO_SMS = os.getenv("DOWN_ENABLE_TWILIO", "0") == "1"
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM = os.getenv("TWILIO_FROM", "")
TWILIO_TO = os.getenv("TWILIO_TO", "")


# ============================================================
# COLORS / TERMINAL UI
# ============================================================

class Color:
    RESET = "\033[0m"; BOLD = "\033[1m"; DIM = "\033[2m"
    RED = "\033[91m"; GREEN = "\033[92m"; YELLOW = "\033[93m"
    BLUE = "\033[94m"; MAGENTA = "\033[95m"; TURQUOISE = "\033[96m"
    WHITE = "\033[97m"; LIGHT_GRAY = "\033[37m"


def colorize(text: str, color: str) -> str:
    if not sys.stdout.isatty():
        return str(text)
    return f"{color}{text}{Color.RESET}"


def red(text): return colorize(text, Color.RED)
def green(text): return colorize(text, Color.GREEN)
def turquoise(text): return colorize(text, Color.TURQUOISE)
def yellow(text): return colorize(text, Color.YELLOW)
def magenta(text): return colorize(text, Color.MAGENTA)
def white(text): return colorize(text, Color.WHITE)
def light(text): return colorize(text, Color.LIGHT_GRAY)
def bold(text): return colorize(text, Color.BOLD)


class Spinner:
    def __init__(self, message="Working"):
        self.message = message
        self.stop_event = threading.Event()
        self.thread = None
        self.frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def start(self):
        if not sys.stdout.isatty():
            return self
        self.thread = threading.Thread(target=self._spin, daemon=True)
        self.thread.start()
        return self

    def _spin(self):
        for frame in itertools.cycle(self.frames):
            if self.stop_event.is_set():
                break
            sys.stdout.write(f"\r{turquoise(frame)} {white(self.message)}")
            sys.stdout.flush()
            time.sleep(0.08)
        sys.stdout.write("\r" + " " * (len(self.message) + 10) + "\r")
        sys.stdout.flush()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=1)


def banner():
    print(turquoise(r"""
                 


⠀⠀⠀⠀⠀⠀           ⠀⠀⠀⠀⠀⠀⠀⠀⣀⣀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀           ⠀⠀⠀⠀⠀⠀⢀⣴⣿⣿⡿⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀           ⠀⠀⠀⠀⠀⠀⢀⣾⣿⣿⠟⠁⠀⠀⠀⠀⠀⠀
⠀         ⠀⠀⢀⣠⣤⣤⣤⣀⣀⠈⠋⠉⣁⣠⣤⣤⣤⣀⡀⠀⠀
         ⠀⢠⣶⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣦⡀
         ⣠⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⠟⠋⠀
         ⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡏⠀⠀⠀
         ⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡇⠀⠀⠀
         ⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣧⠀⠀⠀
         ⠹⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣷⣤⣀
         ⠀⠻⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡿⠁
         ⠀⠀⠙⢿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡟⠁⠀
          ⠀⠀⠀⠈⠙⢿⣿⣿⣿⠿⠟⠛⠻⠿⣿⣿⣿⡿⠋⠀⠀⠀


╔══════════════════════════════════════════════════════╗
║      Apple Downgrade Monitor - All iPhones           ║
║     gs.apple.com Validation + Jailbreak Intel        ║
║     Twilio + Target Watch + Daemon Edition           ║
╚══════════════════════════════════════════════════════╝
"""))


def section(title: str):
    print(turquoise("\n" + "═" * 58))
    print(bold(white(title)))
    print(turquoise("═" * 58))


def tiny_wait_message():
    return random.choice([
        "Consulting Apple's TSS oracle...",
        "Hunting downgrade parties...",
        "Checking SHSH eligibility...",
        "Cross-referencing jailbreak paths...",
        "Scanning firmware timelines...",
        "Looking for rare signing windows...",
    ])


# ============================================================
# VERSION HELPERS
# ============================================================

def version_tuple(version: str) -> Tuple[int, int, int]:
    parts = []
    for part in str(version).split("."):
        clean = "".join(ch for ch in part if ch.isdigit())
        parts.append(int(clean) if clean else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def version_between(version: str, minimum: str, maximum: str) -> bool:
    return version_tuple(minimum) <= version_tuple(version) <= version_tuple(maximum)


def ios_major(version: str) -> int:
    return version_tuple(version)[0]


def major_chip_number(chip: Optional[str]):
    if not chip:
        return None
    digits = "".join(ch for ch in chip if ch.isdigit())
    return int(digits) if digits else None


def parse_versions(raw: Optional[str]) -> Set[str]:
    if not raw:
        return set()
    return {p.strip() for p in raw.replace(";", ",").split(",") if p.strip()}


def version_is_target(version: str, target_versions: Set[str]) -> bool:
    if not target_versions:
        return True
    version_parts = str(version).split(".")
    for target in target_versions:
        if version_tuple(target) == version_tuple(version):
            return True
        target_parts = target.split(".")
        if version_parts[:len(target_parts)] == target_parts:
            return True
    return False


# ============================================================
# DEVICE CHIP MAP
# ============================================================

DEVICE_CHIPS = {
    "iPhone5,1": "A6", "iPhone5,2": "A6", "iPhone5,3": "A6", "iPhone5,4": "A6",
    "iPhone6,1": "A7", "iPhone6,2": "A7",
    "iPhone7,1": "A8", "iPhone7,2": "A8",
    "iPhone8,1": "A9", "iPhone8,2": "A9", "iPhone8,4": "A9",
    "iPhone9,1": "A10", "iPhone9,2": "A10", "iPhone9,3": "A10", "iPhone9,4": "A10",
    "iPhone10,1": "A11", "iPhone10,2": "A11", "iPhone10,3": "A11",
    "iPhone10,4": "A11", "iPhone10,5": "A11", "iPhone10,6": "A11",
    "iPhone11,2": "A12", "iPhone11,4": "A12", "iPhone11,6": "A12", "iPhone11,8": "A12",
    "iPhone12,1": "A13", "iPhone12,3": "A13", "iPhone12,5": "A13", "iPhone12,8": "A13",
    "iPhone13,1": "A14", "iPhone13,2": "A14", "iPhone13,3": "A14", "iPhone13,4": "A14",
    "iPhone14,2": "A15", "iPhone14,3": "A15", "iPhone14,4": "A15", "iPhone14,5": "A15",
    "iPhone14,6": "A15", "iPhone14,7": "A15", "iPhone14,8": "A15",
    "iPhone15,2": "A16", "iPhone15,3": "A16", "iPhone15,4": "A16", "iPhone15,5": "A16",
    "iPhone16,1": "A17 Pro", "iPhone16,2": "A17 Pro",
    "iPhone17,1": "A18 Pro", "iPhone17,2": "A18 Pro", "iPhone17,3": "A18", "iPhone17,4": "A18",
}

CHECKM8_CHIPS = {"A5", "A6", "A7", "A8", "A9", "A10", "A11"}
PALERA1N_CHIPS = {"A8", "A9", "A10", "A11"}


# ============================================================
# JAILBREAK / SEMI-JAILBREAK / PERMASIGN INTELLIGENCE
# ============================================================

@dataclass
class JailbreakInfo:
    name: str
    category: str
    confidence: str
    notes: str
    near_future_score: int = 0


def add_unique(items: List[JailbreakInfo]) -> List[JailbreakInfo]:
    seen = set()
    unique = []
    for item in items:
        key = (item.name, item.category, item.notes)
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def trollstore_matches(version: str) -> List[JailbreakInfo]:
    results = []
    def add(confidence, notes):
        results.append(JailbreakInfo("TrollStore", "permasign/CoreTrust", confidence, notes, 0))

    if version_between(version, "14.0", "16.6.1"):
        add("high", "CoreTrust permasign range; not a jailbreak, but major IPA install/persistence capability.")
    elif version_tuple(version) == version_tuple("16.7"):
        add("verify-build", "Only iOS 16.7 RC build 20H18 is in the known TrollStore range; verify exact build.")
    elif version_tuple(version) == version_tuple("17.0"):
        add("high", "Known TrollStore support range includes iOS 17.0.")
    elif version_between(version, "17.0.1", "17.0.99"):
        add("low", "Close to iOS 17.0 but generally not documented TrollStore range; verify exact status.")
    return results


def semi_jailbreak_tool_matches(identifier: str, version: str) -> List[JailbreakInfo]:
    chip = DEVICE_CHIPS.get(identifier)
    chip_num = major_chip_number(chip)
    results: List[JailbreakInfo] = []

    def add(name, confidence, notes, score=0):
        results.append(JailbreakInfo(name, "semi-jailbreak/tool", confidence, notes, score))

    if version_between(version, "14.0", "16.1.2"):
        add("MacDirtyCow ecosystem", "medium", "Jailed/semi-jailbreak customization class for affected iOS 14-16.1.2 builds.")
    if version_between(version, "16.0", "16.5"):
        add("KFD ecosystem", "medium", "Kernel File Descriptor-era jailed customization/semi-jailbreak tooling range.")
    if version_between(version, "16.5.1", "16.6.1") and chip_num and chip_num <= 14:
        add("KFD-adjacent watchlist", "low", "Device/build dependent; verify before relying on it.", 25)

    if version_between(version, "16.0", "18.1.1"):
        add("Nugget", "medium", "Jailbreak-like customization tool; can enable hidden features on many iOS 16-18.1.1 devices. Not a full jailbreak.")
    elif version_between(version, "18.2", "18.99.99"):
        add("Nugget partial/watchlist", "low", "Newer iOS 18 builds may be partial or feature-limited depending on release/support.", 20)
    elif ios_major(version) >= 19:
        add("Nugget future/partial watchlist", "speculative", "Higher versions may have partial support depending on current Nugget releases and Apple patches.", 15)
    return results


def jailbreak_matches(identifier: str, version: str) -> List[JailbreakInfo]:
    chip = DEVICE_CHIPS.get(identifier)
    chip_num = major_chip_number(chip)
    matches: List[JailbreakInfo] = []

    def add(name, category, confidence, notes, score=0):
        matches.append(JailbreakInfo(name, category, confidence, notes, score))

    if version_between(version, "9.0", "9.0.2"):
        add("Pangu9", "full jailbreak", "high", "Classic iOS 9.0-9.0.2 jailbreak era.")
    if version_between(version, "9.1", "9.1"):
        add("Pangu9 iOS 9.1", "full jailbreak", "medium", "Known iOS 9.1 support on select devices.")
    if version_between(version, "9.2", "9.3.3"):
        add("Pangu / PP iOS 9.2-9.3.3", "semi-untethered jailbreak", "medium", "Semi-untethered iOS 9.2-9.3.3 era.")
    if version_between(version, "9.3.5", "9.3.6") and chip_num and chip_num <= 8:
        add("Phoenix", "semi-untethered jailbreak", "high", "Older-device iOS 9.3.5/9.3.6 jailbreak family.")

    if version_between(version, "10.0", "10.2"):
        add("yalu102", "semi-untethered jailbreak", "medium", "iOS 10.0-10.2 semi-untethered jailbreak era.")
    if version_between(version, "10.0", "10.3.3") and chip in CHECKM8_CHIPS:
        add("checkm8-based research path", "bootrom exploit class", "high", "A5-A11 bootrom exploit class allows low-level research paths.")

    if version_between(version, "11.0", "11.4.1"):
        add("Electra", "semi-untethered jailbreak", "medium", "iOS 11 jailbreak family.")
    if version_between(version, "11.0", "14.3"):
        add("unc0ver", "semi-untethered jailbreak", "high", "unc0ver support family includes iOS 11.0-14.3.")
    if chip in CHECKM8_CHIPS and ios_major(version) >= 11:
        add("checkra1n/checkm8 class", "bootrom jailbreak", "high", "Unpatchable bootrom-class support for A5-A11-era devices.")

    if version_between(version, "12.0", "12.5.7"):
        add("Chimera / unc0ver era", "semi-untethered jailbreak", "medium", "iOS 12 has several jailbreak paths depending on chip/version.")
    if version_between(version, "12.0", "12.4.1"):
        add("Chimera", "semi-untethered jailbreak", "medium", "A12-era jailbreak path for iOS 12.")
    if version_between(version, "12.0", "12.5.7") and chip in CHECKM8_CHIPS:
        add("checkra1n", "bootrom jailbreak", "high", "checkm8-based jailbreak path for supported legacy devices.")

    if version_between(version, "13.0", "13.7") and chip in CHECKM8_CHIPS:
        add("checkra1n", "bootrom jailbreak", "high", "Strong on checkm8 devices.")
    if version_between(version, "13.0", "13.5"):
        add("unc0ver", "semi-untethered jailbreak", "high", "unc0ver supported many iOS 11-13.5 era builds.")

    if version_between(version, "14.0", "14.8.1"):
        add("Taurine", "semi-untethered jailbreak", "high", "Taurine jailbreak family: iOS 14.0-14.8.1.")
    if version_between(version, "14.0", "14.3"):
        add("unc0ver", "semi-untethered jailbreak", "high", "unc0ver range includes iOS 14.0-14.3.")
    if chip in CHECKM8_CHIPS and version_between(version, "14.0", "14.8.1"):
        add("checkra1n", "bootrom jailbreak", "high", "checkm8 devices remain strong candidates on iOS 14.")

    if chip in PALERA1N_CHIPS and version_between(version, "15.0", "99.99.99"):
        add("palera1n", "rootless/rootful checkm8 jailbreak", "high", "A8-A11 iOS 15+ jailbreak with long-running stability in the rootless era; A11 SEP/passcode caveats apply.")

    if chip_num:
        if 8 <= chip_num <= 11 and (version_between(version, "15.0", "15.8.6") or version_between(version, "16.0", "16.6.1")):
            add("Dopamine", "rootless semi-untethered jailbreak", "high", "A8-A11 range: iOS 15.0-15.8.6 and 16.0-16.6.1.")
        elif 12 <= chip_num <= 16 and version_between(version, "15.0", "16.5"):
            add("Dopamine", "rootless semi-untethered jailbreak", "high", "A12-A16 range: iOS 15.0-16.5.")
        elif 12 <= chip_num <= 14 and version_tuple(version) == version_tuple("16.5.1"):
            add("Dopamine", "rootless semi-untethered jailbreak", "high", "A12-A14 special support includes iOS 16.5.1.")

        if 9 <= chip_num <= 10 and version_tuple(version) == version_tuple("15.8.7"):
            add("Dopamine + DarkSword", "rootless beta/watchlist", "beta", "Reported beta path using DarkSword for iOS 15.8.7 on A9-A10; verify current release/issues.", 70)
        if 8 <= chip_num <= 11 and version_between(version, "16.7", "16.7.15"):
            add("Dopamine + DarkSword", "rootless beta/watchlist", "beta", "Reported DarkSword-backed Dopamine expansion for arm64 iOS 16.7-16.7.15; caveats apply.", 70)
        if 12 <= chip_num <= 16 and version_between(version, "16.5.1", "16.6.1"):
            add("Dopamine-adjacent watchlist", "rootless watchlist", "low", "Close to known Dopamine-era ranges; verify current exploit status.", 35)

    if ios_major(version) == 17:
        score = 80 if chip in CHECKM8_CHIPS else (45 if chip_num and chip_num <= 14 else 25)
        add("Near-future jailbreak watchlist", "speculative jailbreak", "speculative", "iOS 17 public full jailbreak coverage is limited; watch exploit chains and PAC/PPL research.", score)

    if ios_major(version) >= 18:
        score = 75 if chip in CHECKM8_CHIPS else 15
        add("Near-future jailbreak watchlist", "speculative jailbreak", "speculative", "iOS 18+ depends on public kernel/PAC/PPL bypass chains; checkm8 devices remain strongest.", score)

    matches.extend(trollstore_matches(version))
    matches.extend(semi_jailbreak_tool_matches(identifier, version))
    return add_unique(matches)


def format_jailbreaks(identifier: str, version: str) -> str:
    matches = jailbreak_matches(identifier, version)
    fullish = [m for m in matches if "jailbreak" in m.category and m.confidence not in {"none", "speculative", "low"}]
    troll = [m for m in matches if m.name == "TrollStore"]
    tools = [m for m in matches if m.category == "semi-jailbreak/tool"]
    speculative = [m for m in matches if m.confidence == "speculative"]
    parts = []

    if fullish:
        parts.append(turquoise("🔓 JB: " + ", ".join(f"{m.name} [{m.confidence}]" for m in fullish[:4])))
    if troll:
        parts.append(magenta(f"🧬 TrollStore [{troll[0].confidence}]"))
    if tools:
        parts.append(yellow("🧰 Tools: " + ", ".join(f"{m.name} [{m.confidence}]" for m in tools[:3])))
    if not parts and speculative:
        parts.append(yellow(f"🕒 watchlist: future likelihood {max(m.near_future_score for m in speculative)}/100"))
    return " ".join(parts) if parts else red("❌ no known jailbreak/tool match")


def jailbreak_plain(identifier: str, version: str) -> str:
    matches = jailbreak_matches(identifier, version)
    if not matches:
        return "No known jailbreak/tool match"
    parts = []
    for m in matches:
        if m.confidence == "speculative":
            parts.append(f"{m.name} ({m.category}) speculative {m.near_future_score}/100")
        elif m.near_future_score:
            parts.append(f"{m.name} ({m.category}) {m.confidence}, score {m.near_future_score}/100")
        else:
            parts.append(f"{m.name} ({m.category}) {m.confidence}")
    return "; ".join(parts)


def print_jailbreak_summary():
    section("Jailbreak / semi-jailbreak / permasign cross-reference enabled")
    print(white("  iOS 9:      Pangu9, Pangu/PP, Phoenix-era references"))
    print(white("  iOS 10:     yalu102, legacy checkm8 research paths"))
    print(white("  iOS 11:     Electra, unc0ver, checkra1n/checkm8"))
    print(white("  iOS 12:     Chimera, unc0ver, checkra1n/checkm8"))
    print(white("  iOS 13:     unc0ver/checkra1n era"))
    print(white("  iOS 14:     Taurine, unc0ver, checkra1n, TrollStore"))
    print(white("  iOS 15+:    palera1n prominently listed for A8-A11 rootless/checkm8 paths"))
    print(white("  iOS 15-16:  Dopamine including mainline ranges and DarkSword beta/watchlist expansion"))
    print(white("  iOS 14-17:  TrollStore/CoreTrust permasign support where applicable"))
    print(white("  iOS 16-18+: Nugget, MDC/KFD/SparseRestore-style tools listed separately from full jailbreaks"))
    print(red("  Note: Best-effort matching. Verify exact device, build, SEP/baseband, and current tool release before restoring.\n"))


# ============================================================
# TOOL DISCOVERY
# ============================================================

def find_tsschecker() -> str:
    local = Path(LOCAL_TSSCHECKER)
    if local.exists():
        return str(local)
    found = shutil.which("tsschecker")
    if found:
        return found
    print(red("[FATAL] tsschecker not found."))
    print(white("Put the binary at ./tools/tsschecker or install it into PATH."))
    raise SystemExit(1)


def find_notify():
    return shutil.which("notify")


TSSCHECKER_PATH = find_tsschecker()
NOTIFY_PATH = find_notify()


def verify_apple_tss_reachable() -> bool:
    try:
        response = requests.get("https://gs.apple.com", timeout=12)
        return response.status_code in {200, 301, 302, 403, 404}
    except Exception:
        return False


def print_tsschecker_version():
    try:
        result = subprocess.run([TSSCHECKER_PATH, "--version"], capture_output=True, text=True, timeout=10)
        output = (result.stdout + result.stderr).strip()
        if output:
            print(light(f"tsschecker: {output.splitlines()[0]}"))
    except Exception:
        pass


# ============================================================
# DATABASE
# ============================================================

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS seen_alerts (
            alert_key TEXT PRIMARY KEY,
            created_at INTEGER NOT NULL
        )
    """)
    conn.commit()
    return conn


def already_alerted(key: str) -> bool:
    with db() as conn:
        return conn.execute("SELECT 1 FROM seen_alerts WHERE alert_key = ?", (key,)).fetchone() is not None


def mark_alerted(key: str):
    with db() as conn:
        conn.execute("INSERT OR IGNORE INTO seen_alerts VALUES (?, ?)", (key, int(time.time())))
        conn.commit()


# ============================================================
# ALERTS
# ============================================================

def escape_applescript(text: str) -> str:
    return str(text).replace("\\", "\\\\").replace('"', '\\"')


def run_macos_notification(title: str, message: str):
    if not ENABLE_MACOS_NOTIFICATION:
        return
    subprocess.run(
        ["osascript", "-e", f'display notification "{escape_applescript(message)}" with title "{escape_applescript(title)}"'],
        check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def run_macos_dialog(title: str, message: str):
    if not ENABLE_MACOS_DIALOG:
        return
    script = (
        f'display dialog "{escape_applescript(message)}" '
        f'with title "{escape_applescript(title)}" '
        'buttons {"OK"} default button "OK" with icon caution'
    )
    subprocess.run(["osascript", "-e", script], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def send_projectdiscovery_notify(message: str):
    if not ENABLE_PROJECTDISCOVERY_NOTIFY:
        return
    if not NOTIFY_PATH:
        if SHOW_VERBOSE_ERRORS:
            print(red("[notify] ProjectDiscovery notify not found in PATH."))
        return
    cmd = [NOTIFY_PATH, "-bulk"]
    if PROJECTDISCOVERY_NOTIFY_ID:
        cmd.extend(["-id", PROJECTDISCOVERY_NOTIFY_ID])
    if PROJECTDISCOVERY_NOTIFY_PROVIDER:
        cmd.extend(["-provider", PROJECTDISCOVERY_NOTIFY_PROVIDER])
    subprocess.run(cmd, input=message, text=True, capture_output=not SHOW_VERBOSE_ERRORS, check=False)


def send_email_alert(subject: str, body: str, recipient: str):
    if not recipient:
        return
    if not SMTP_USERNAME or not SMTP_PASSWORD:
        if SHOW_VERBOSE_ERRORS:
            print(red("[email] DOWN_EMAIL_USER or DOWN_EMAIL_PASSWORD missing."))
        return
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM or SMTP_USERNAME
    msg["To"] = recipient
    msg.set_content(body)
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as smtp:
            smtp.starttls()
            smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
            smtp.send_message(msg)
    except Exception as error:
        if SHOW_VERBOSE_ERRORS:
            print(red(f"[email] failed: {error}"))


def send_twilio_sms(body: str):
    if not ENABLE_TWILIO_SMS:
        return
    missing = [name for name, value in {
        "TWILIO_ACCOUNT_SID": TWILIO_ACCOUNT_SID,
        "TWILIO_AUTH_TOKEN": TWILIO_AUTH_TOKEN,
        "TWILIO_FROM": TWILIO_FROM,
        "TWILIO_TO": TWILIO_TO,
    }.items() if not value]
    if missing:
        if SHOW_VERBOSE_ERRORS:
            print(red(f"[twilio] missing env vars: {', '.join(missing)}"))
        return

    url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Messages.json"
    auth_header = base64.b64encode(f"{TWILIO_ACCOUNT_SID}:{TWILIO_AUTH_TOKEN}".encode()).decode()
    payload = urlencode({"From": TWILIO_FROM, "To": TWILIO_TO, "Body": body[:1500]})

    try:
        response = requests.post(
            url,
            data=payload,
            headers={"Authorization": f"Basic {auth_header}", "Content-Type": "application/x-www-form-urlencoded"},
            timeout=20,
        )
        if response.status_code >= 400 and SHOW_VERBOSE_ERRORS:
            print(red(f"[twilio] failed: {response.status_code} {response.text[:500]}"))
    except Exception as error:
        if SHOW_VERBOSE_ERRORS:
            print(red(f"[twilio] failed: {error}"))


def send_all_remote_alerts(subject: str, body: str):
    if ENABLE_EMAIL_ALERTS:
        send_email_alert(subject, body, EMAIL_TO)
    if ENABLE_SMS_EMAIL_GATEWAY:
        send_email_alert(subject, body[:1400], SMS_TO)
    if ENABLE_TWILIO_SMS:
        send_twilio_sms(f"{subject}\n\n{body[:1300]}")


def alert_new_party(title: str, long_message: str):
    run_macos_notification(title, long_message[:220])
    run_macos_dialog(title, long_message[:1800])
    send_projectdiscovery_notify(f"{title}\n\n{long_message}")
    send_all_remote_alerts(title, long_message)


# ============================================================
# FIRMWARE FETCHING
# ============================================================

def get_all_iphones():
    response = requests.get(DEVICE_API, timeout=30)
    response.raise_for_status()
    devices = []
    for device in response.json():
        identifier = device.get("identifier", "")
        if identifier.startswith("iPhone"):
            devices.append({"name": device.get("name", identifier), "identifier": identifier})
    devices.sort(key=lambda item: item["identifier"])
    return devices


def fetch_firmwares(identifier: str):
    response = requests.get(FIRMWARE_API.format(identifier=identifier), timeout=30)
    response.raise_for_status()
    firmwares = [fw for fw in response.json().get("firmwares", []) if fw.get("url") and fw.get("version") and fw.get("buildid")]
    firmwares.sort(key=lambda fw: version_tuple(fw["version"]), reverse=True)
    return firmwares[:RECENT_FIRMWARE_LIMIT]


def filter_firmwares(firmwares: List[dict], target_versions: Set[str]) -> List[dict]:
    if not target_versions:
        return firmwares
    return [fw for fw in firmwares if version_is_target(str(fw.get("version", "")), target_versions)]


def download_manifest(ipsw_url: str, identifier: str, version: str, buildid: str) -> Path:
    out_dir = MANIFEST_DIR / identifier / version
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / f"{buildid}_BuildManifest.plist"
    if manifest_path.exists():
        return manifest_path
    print(light(f"  caching BuildManifest: iOS {version} ({buildid})"))
    with RemoteZip(ipsw_url) as zip_file:
        data = zip_file.read("BuildManifest.plist")
    manifest_path.write_bytes(data)
    return manifest_path


def manifest_sanity_check(manifest_path: Path, version: str, buildid: str):
    try:
        data = plistlib.loads(manifest_path.read_bytes())
        product_version = str(data.get("ProductVersion", ""))
        product_build = str(data.get("ProductBuildVersion", ""))
        if product_version and product_version != str(version):
            return False, f"manifest version mismatch: {product_version} != {version}"
        if product_build and product_build != str(buildid):
            return False, f"manifest build mismatch: {product_build} != {buildid}"
        if not data.get("BuildIdentities", []):
            return False, "manifest has no BuildIdentities"
        return True, "manifest ok"
    except Exception as error:
        return False, f"manifest parse failed: {error}"


# ============================================================
# APPLE TSS VALIDATION
# ============================================================

def tsschecker_is_signed(manifest_path: Path, identifier: str, version: str):
    cmd = [
        TSSCHECKER_PATH, "--nocache", "--no-baseband",
        "--device", identifier, "--ios", version,
        "--build-manifest", str(manifest_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    output_raw = result.stdout + "\n" + result.stderr
    output = output_raw.lower()

    official_hint = any(x in output for x in ["gs.apple.com", "tss", "tatsu", "request url", "tss server"])

    if "is being signed" in output:
        return True, "signed by Apple TSS", official_hint
    if "not being signed" in output or "not signed" in output:
        return False, "not signed by Apple TSS", official_hint
    if "status=94" in output or "isn't eligible for the requested build" in output:
        return False, "Apple TSS says device is not eligible", official_hint
    if SHOW_VERBOSE_ERRORS:
        return False, output_raw[-900:].strip() or "unknown Apple TSS response", official_hint
    return False, "Apple TSS check failed", official_hint


def check_firmware(device, firmware):
    identifier = device["identifier"]
    version = firmware["version"]
    buildid = firmware["buildid"]
    try:
        manifest = download_manifest(firmware["url"], identifier, version, buildid)
        ok, reason = manifest_sanity_check(manifest, version, buildid)
        if not ok:
            return {"device": device, "firmware": firmware, "signed": False, "reason": reason, "official_tss": False, "error": None}
        signed, reason, official_tss = tsschecker_is_signed(manifest, identifier, version)
        return {"device": device, "firmware": firmware, "signed": signed, "reason": reason, "official_tss": official_tss, "error": None}
    except subprocess.TimeoutExpired:
        return {"device": device, "firmware": firmware, "signed": False, "reason": "Apple TSS request timed out", "official_tss": True, "error": None}
    except Exception as error:
        return {"device": device, "firmware": firmware, "signed": False, "reason": "check failed", "official_tss": False, "error": str(error)}


# ============================================================
# DEVICE CHECKING
# ============================================================

def check_device(device, target_versions: Set[str]):
    name = device["name"]
    identifier = device["identifier"]
    chip = DEVICE_CHIPS.get(identifier, "unknown chip")
    print(f"\n{bold('Checking')} {name} {white(f'({identifier}, {chip})')}")

    try:
        firmwares = filter_firmwares(fetch_firmwares(identifier), target_versions)
    except Exception as error:
        if SHOW_VERBOSE_ERRORS:
            print(red(f"  [ERROR] Firmware fetch failed: {error}"))
        else:
            print(red("  Firmware fetch failed."))
        return []

    if not firmwares:
        print(yellow("  No matching firmware records found." if target_versions else "  No firmware records found."))
        return []

    results = []
    spinner = Spinner(f"{tiny_wait_message()} {identifier}").start()
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(check_firmware, device, firmware) for firmware in firmwares]
        for future in as_completed(futures):
            results.append(future.result())
    spinner.stop()

    results.sort(key=lambda r: version_tuple(r["firmware"]["version"]), reverse=True)

    for result in results:
        firmware = result["firmware"]
        version = firmware["version"]
        buildid = firmware["buildid"]
        jb_text = format_jailbreaks(identifier, version)
        tss_badge = green("Apple TSS") if result.get("official_tss") else yellow("TSS unconfirmed")

        if result["error"]:
            if SHOW_VERBOSE_ERRORS:
                print(red(f"  [ERROR] iOS {version} ({buildid}): {result['error']}"))
            else:
                print(red(f"  not signed: iOS {version} ({buildid}) - check failed ") + jb_text)
        elif result["signed"]:
            label = "SIGNED TARGET" if target_versions else "SIGNED"
            print(turquoise(f"  {label}: iOS {version} ({buildid}) ") + tss_badge + " " + jb_text)
        else:
            print(red(f"  not signed: iOS {version} ({buildid}) - {result['reason']} ") + jb_text)

    signed = [result["firmware"] for result in results if result["signed"]]
    if not signed:
        print(red("  No signed firmwares found."))
        return []

    signed.sort(key=lambda fw: version_tuple(fw["version"]), reverse=True)

    if target_versions:
        interesting = signed
        print(turquoise("  🎯 SIGNED TARGET VERSION(S) FOUND:"))
    else:
        latest_signed = signed[0]["version"]
        interesting = [fw for fw in signed if version_tuple(fw["version"]) < version_tuple(latest_signed)]
        if not interesting:
            print(red("  No downgrade parties."))
            return []
        print(turquoise("  🎉 DOWNGRADE PARTIES FOUND:"))

    found_items = []
    for firmware in interesting:
        version = firmware["version"]
        buildid = firmware["buildid"]
        alert_kind = "target" if target_versions else "downgrade"
        alert_key = f"{alert_kind}:{identifier}:{version}:{buildid}"
        jb_text_plain = jailbreak_plain(identifier, version)
        jb_text_colored = format_jailbreaks(identifier, version)

        print(turquoise(f"    - iOS {version} ({buildid}) ") + jb_text_colored)

        item = {
            "name": name, "identifier": identifier, "chip": chip,
            "version": version, "buildid": buildid, "alert_key": alert_key,
            "jailbreaks": jb_text_plain, "kind": alert_kind,
        }
        found_items.append(item)

        if not already_alerted(alert_key):
            title = "Watched iOS Version Signed 🎯" if target_versions else "New Downgrade Party Found 🎉"
            intro = "A watched iOS version is currently signed!" if target_versions else "New downgrade party found!"
            long_message = (
                f"{intro}\n\n"
                f"Device: {name}\n"
                f"Identifier: {identifier}\n"
                f"Chip: {chip}\n"
                f"Firmware: iOS {version}\n"
                f"Build: {buildid}\n"
                f"Jailbreak intelligence: {jb_text_plain}\n\n"
                f"Signing source: Apple's live TSS server / gs.apple.com via tsschecker.\n"
                f"Reminder: verify SEP/baseband compatibility before restoring."
            )
            alert_new_party(title, long_message)
            mark_alerted(alert_key)

    return found_items


# ============================================================
# SUMMARY
# ============================================================

def send_summary_alert(all_items, target_versions: Set[str]):
    if not all_items:
        return
    count = len(all_items)
    lines = [
        f"{item['name']} ({item['identifier']}, {item['chip']}) → "
        f"iOS {item['version']} ({item['buildid']}) | JB/tools: {item['jailbreaks']}"
        for item in all_items
    ]

    if target_versions:
        title = f"{count} Watched iOS Signing Match(es) 🎯"
        message = "Active watched-version matches:\n\n" + "\n".join(lines[:40])
    else:
        title = f"{count} Downgrade Parties Active 🎉"
        message = "Active downgrade parties:\n\n" + "\n".join(lines[:40])

    if count > 40:
        message += f"\n\n...and {count - 40} more."

    run_macos_notification(title, message[:220])
    send_projectdiscovery_notify(f"{title}\n\n{message}")
    send_all_remote_alerts(title, message)


def print_final_summary(all_items, target_versions: Set[str]):
    if all_items:
        label = "watched signing match(es)" if target_versions else "downgrade parties"
        print(turquoise(f"\nSUMMARY: {len(all_items)} {label} active."))
        for item in all_items:
            print(turquoise(
                f"  - {item['name']} ({item['identifier']}, {item['chip']}) "
                f"iOS {item['version']} ({item['buildid']}) | JB/tools: {item['jailbreaks']}"
            ))
    else:
        print(red("\nSUMMARY: No watched target versions are currently signed." if target_versions else "\nSUMMARY: No downgrade parties active."))


# ============================================================
# DAEMON / LAUNCHAGENT
# ============================================================

def script_path() -> Path:
    return Path(__file__).resolve()


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHAGENT_LABEL}.plist"


def current_env_for_launchagent() -> dict:
    keys = [
        "PATH", "DOWN_CHECK_INTERVAL", "DOWN_MAX_WORKERS", "DOWN_RECENT_FIRMWARE_LIMIT",
        "DOWN_TSSCHECKER", "DOWN_BASE_DIR", "DOWN_VERBOSE_ERRORS",
        "DOWN_ENABLE_MACOS_NOTIFICATION", "DOWN_ENABLE_MACOS_DIALOG",
        "DOWN_ENABLE_NOTIFY", "DOWN_NOTIFY_ID", "DOWN_NOTIFY_PROVIDER",
        "DOWN_ENABLE_EMAIL", "DOWN_SMTP_HOST", "DOWN_SMTP_PORT",
        "DOWN_EMAIL_USER", "DOWN_EMAIL_PASSWORD", "DOWN_EMAIL_FROM", "DOWN_EMAIL_TO",
        "DOWN_ENABLE_SMS_GATEWAY", "DOWN_SMS_GATEWAY_TO",
        "DOWN_ENABLE_TWILIO", "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM", "TWILIO_TO",
    ]
    env = {k: os.getenv(k) for k in keys if os.getenv(k)}
    env.setdefault("PATH", "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin")
    env.setdefault("DOWN_ENABLE_MACOS_DIALOG", "0")
    return env


def install_daemon(mode: str, target_versions: Set[str]):
    plist_path().parent.mkdir(parents=True, exist_ok=True)

    args = [sys.executable, str(script_path()), "--daemon-run", "--mode", mode, "--no-menu"]
    if target_versions:
        args.extend(["--versions", ",".join(sorted(target_versions))])

    stdout_log = str(LOG_DIR / "daemon.stdout.log")
    stderr_log = str(LOG_DIR / "daemon.stderr.log")

    plist = {
        "Label": LAUNCHAGENT_LABEL,
        "ProgramArguments": args,
        "RunAtLoad": True,
        "KeepAlive": True,
        "WorkingDirectory": str(script_path().parent),
        "StandardOutPath": stdout_log,
        "StandardErrorPath": stderr_log,
        "EnvironmentVariables": current_env_for_launchagent(),
    }

    plist_path().write_bytes(plistlib.dumps(plist, sort_keys=False))
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", str(plist_path())], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    result = subprocess.run(
        ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist_path())],
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        print(green(f"Installed and started LaunchAgent: {LAUNCHAGENT_LABEL}"))
        print(white(f"Plist: {plist_path()}"))
        print(white(f"Logs: {stdout_log}"))
        print(white(f"Errors: {stderr_log}"))
    else:
        print(red("Failed to bootstrap LaunchAgent."))
        print(red(result.stderr.strip() or result.stdout.strip()))
        print(white(f"Plist was written to: {plist_path()}"))


def uninstall_daemon():
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", str(plist_path())], check=False)
    if plist_path().exists():
        plist_path().unlink()
    print(green(f"Uninstalled LaunchAgent: {LAUNCHAGENT_LABEL}"))


def daemon_status():
    result = subprocess.run(
        ["launchctl", "print", f"gui/{os.getuid()}/{LAUNCHAGENT_LABEL}"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print(green(f"LaunchAgent is loaded: {LAUNCHAGENT_LABEL}"))
        print("\n".join(result.stdout.splitlines()[:80]))
    else:
        print(red(f"LaunchAgent is not loaded: {LAUNCHAGENT_LABEL}"))
        print(yellow(f"Plist exists: {plist_path()}" if plist_path().exists() else "Plist does not exist."))


# ============================================================
# MENU / MAIN
# ============================================================

def ask_choice(prompt: str, choices: List[str], default: str) -> str:
    raw = input(f"{prompt} [{' / '.join(choices)}] default={default}: ").strip().lower()
    if not raw:
        return default
    if raw in choices:
        return raw
    print(yellow(f"Invalid choice. Using {default}."))
    return default


def interactive_config(args):
    section("Run mode")
    print(white("1. Watch all versions and alert only if a downgrade party appears"))
    print(white("2. Watch specific iOS versions and alert when any target version is signed"))
    choice = ask_choice("Choose mode", ["1", "2"], "1")

    if choice == "2":
        args.mode = "versions"
        args.versions = input("Enter iOS versions, comma separated, e.g. 15.7.1,16.5.1,17.0: ").strip()
    else:
        args.mode = "all"
        args.versions = ""

    run_choice = ask_choice("Run now, run once, or install daemon", ["now", "once", "daemon"], "now")
    if run_choice == "once":
        args.once = True
    elif run_choice == "daemon":
        args.install_daemon = True
    return args


def print_startup(mode: str, target_versions: Set[str], daemon_run: bool):
    banner()
    print(white("Signing source of truth: ") + turquoise(APPLE_TSS_SERVER))
    print(light("IPSW.me is used only for firmware metadata and BuildManifest links."))

    print(green("Apple TSS reachable: yes") if verify_apple_tss_reachable() else red("Apple TSS reachable: no or blocked"))
    print(white(f"Using tsschecker: {TSSCHECKER_PATH}"))
    print_tsschecker_version()

    print(yellow(f"Watch mode: target versions -> {', '.join(sorted(target_versions))}") if target_versions else yellow("Watch mode: all versions / downgrade parties"))
    if daemon_run:
        print(white("Daemon mode: enabled"))

    if ENABLE_PROJECTDISCOVERY_NOTIFY:
        print(white(f"ProjectDiscovery notify enabled: {NOTIFY_PATH}") if NOTIFY_PATH else red("ProjectDiscovery notify enabled, but notify not found."))
    if ENABLE_EMAIL_ALERTS:
        print(white(f"Email alerts enabled: {EMAIL_TO or 'missing DOWN_EMAIL_TO'}"))
    if ENABLE_SMS_EMAIL_GATEWAY:
        print(white(f"SMS gateway alerts enabled: {SMS_TO or 'missing DOWN_SMS_GATEWAY_TO'}"))
    if ENABLE_TWILIO_SMS:
        print(white(f"Twilio SMS enabled: {TWILIO_TO or 'missing TWILIO_TO'}"))

    print_jailbreak_summary()


def run_monitor(mode: str, target_versions: Set[str], once: bool, daemon_run: bool):
    print_startup(mode, target_versions, daemon_run)

    spinner = Spinner("Loading iPhone model list").start()
    devices = get_all_iphones()
    spinner.stop()

    print(turquoise(f"Loaded {len(devices)} iPhone models."))

    while True:
        all_items = []
        for device in devices:
            all_items.extend(check_device(device, target_versions))

        send_summary_alert(all_items, target_versions)
        print_final_summary(all_items, target_versions)

        if once:
            break

        print(white(f"\nChecking again in {CHECK_INTERVAL // 60} minutes...\n"))
        try:
            time.sleep(CHECK_INTERVAL)
        except KeyboardInterrupt:
            print(yellow("\nStopped by user."))
            break


def build_parser():
    parser = argparse.ArgumentParser(description="Apple TSS Downgrade Monitor with Twilio, target watch, and macOS daemon support.")
    parser.add_argument("--mode", choices=["all", "versions"], default=None)
    parser.add_argument("--versions", default="", help="Comma-separated iOS versions to watch, e.g. 15.7.1,16.5.1,17.0")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--no-menu", action="store_true")

    parser.add_argument("--install-daemon", action="store_true")
    parser.add_argument("--uninstall-daemon", action="store_true")
    parser.add_argument("--daemon-status", action="store_true")
    parser.add_argument("--daemon-run", action="store_true", help=argparse.SUPPRESS)

    parser.add_argument("--test-alerts", action="store_true")
    return parser


def main():
    args = build_parser().parse_args()

    if args.uninstall_daemon:
        uninstall_daemon()
        return
    if args.daemon_status:
        daemon_status()
        return
    if args.test_alerts:
        alert_new_party("Downgrade Monitor Test Alert", "This is a test alert from the downgrade monitor. If you received it, that channel works.")
        print(green("Test alert attempted."))
        return

    if not args.no_menu and not args.daemon_run and not args.install_daemon and args.mode is None:
        args = interactive_config(args)

    mode = args.mode or "all"
    target_versions = parse_versions(args.versions)

    if mode == "versions" and not target_versions:
        print(red("Version watch mode selected, but no versions were provided."))
        print(white("Example: python3 down.py --mode versions --versions 16.5.1,17.0"))
        raise SystemExit(2)

    if args.install_daemon:
        install_daemon(mode, target_versions)
        return

    run_monitor(mode=mode, target_versions=target_versions, once=args.once, daemon_run=args.daemon_run)


if __name__ == "__main__":
    main()

