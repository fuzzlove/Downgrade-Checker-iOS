#!/usr/bin/env python3

import warnings
warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL")

import shutil
import sqlite3
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from remotezip import RemoteZip


DEVICE_API = "https://api.ipsw.me/v4/devices"
FIRMWARE_API = "https://api.ipsw.me/v4/device/{identifier}?type=ipsw"

CHECK_INTERVAL = 300
MAX_WORKERS = 10
RECENT_FIRMWARE_LIMIT = 50

LOCAL_TSSCHECKER = "./tools/tsschecker"

ENABLE_PROJECTDISCOVERY_NOTIFY = False
PROJECTDISCOVERY_NOTIFY_ID = None
PROJECTDISCOVERY_NOTIFY_PROVIDER = None

SHOW_VERBOSE_ERRORS = False

BASE_DIR = Path("downgrade_cache")
MANIFEST_DIR = BASE_DIR / "buildmanifests"
DB_PATH = BASE_DIR / "downgrades.sqlite3"

BASE_DIR.mkdir(exist_ok=True)
MANIFEST_DIR.mkdir(exist_ok=True)


class Color:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    RED = "\033[91m"
    TURQUOISE = "\033[96m"
    YELLOW = "\033[93m"
    WHITE = "\033[97m"
    LIGHT_GRAY = "\033[37m"


def red(text): return f"{Color.RED}{text}{Color.RESET}"
def turquoise(text): return f"{Color.TURQUOISE}{text}{Color.RESET}"
def yellow(text): return f"{Color.YELLOW}{text}{Color.RESET}"
def white(text): return f"{Color.WHITE}{text}{Color.RESET}"
def light(text): return f"{Color.LIGHT_GRAY}{text}{Color.RESET}"
def bold(text): return f"{Color.BOLD}{text}{Color.RESET}"


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
}


CHECKM8_CHIPS = {"A5", "A6", "A7", "A8", "A9", "A10", "A11"}
PALERA1N_CHIPS = {"A8", "A9", "A10", "A11"}


def version_tuple(version):
    parts = []

    for part in str(version).split("."):
        clean = "".join(ch for ch in part if ch.isdigit())
        try:
            parts.append(int(clean))
        except ValueError:
            parts.append(0)

    while len(parts) < 3:
        parts.append(0)

    return tuple(parts)


def version_between(version, minimum, maximum):
    return version_tuple(minimum) <= version_tuple(version) <= version_tuple(maximum)


def major_chip_number(chip):
    if not chip:
        return None

    digits = "".join(ch for ch in chip if ch.isdigit())

    if not digits:
        return None

    return int(digits)


def jailbreak_matches(identifier, version):
    chip = DEVICE_CHIPS.get(identifier)
    chip_num = major_chip_number(chip)
    matches = []

    if chip in CHECKM8_CHIPS:
        matches.append("checkm8")

    if chip in PALERA1N_CHIPS and version_between(version, "15.0", "18.99.99"):
        matches.append("palera1n")

    if version_between(version, "15.0", "15.8.6") and chip_num and 8 <= chip_num <= 16:
        matches.append("Dopamine")

    if version_between(version, "16.0", "16.5") and chip_num and 8 <= chip_num <= 16:
        matches.append("Dopamine")

    if version_tuple(version) == version_tuple("16.5.1") and chip_num and chip_num <= 14:
        matches.append("Dopamine")

    if version_between(version, "16.6", "16.6.1") and chip_num and chip_num <= 11:
        matches.append("Dopamine")

    if version_between(version, "14.0", "14.8.1"):
        matches.append("Taurine")

    if version_between(version, "11.0", "14.3"):
        matches.append("unc0ver")

    return sorted(set(matches))


def format_jailbreaks(identifier, version):
    matches = jailbreak_matches(identifier, version)

    if matches:
        return turquoise("🔓 JB: " + ", ".join(matches))

    return red("❌ no known jailbreak match")


def find_tsschecker():
    local = Path(LOCAL_TSSCHECKER)

    if local.exists():
        return str(local)

    found = shutil.which("tsschecker")

    if found:
        return found

    print(red("[FATAL] tsschecker not found."))
    print(white("Put the binary at: ./tools/tsschecker"))
    print(white("Then run: chmod +x ./tools/tsschecker"))
    raise SystemExit(1)


def find_notify():
    return shutil.which("notify")


TSSCHECKER_PATH = find_tsschecker()
NOTIFY_PATH = find_notify()


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


def already_alerted(key):
    with db() as conn:
        return conn.execute(
            "SELECT 1 FROM seen_alerts WHERE alert_key = ?",
            (key,)
        ).fetchone() is not None


def mark_alerted(key):
    with db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO seen_alerts VALUES (?, ?)",
            (key, int(time.time()))
        )
        conn.commit()


def run_macos_notification(title, message):
    safe_title = title.replace('"', '\\"')
    safe_message = message.replace('"', '\\"')

    subprocess.run([
        "osascript",
        "-e",
        f'display notification "{safe_message}" with title "{safe_title}"'
    ], check=False)


def run_macos_dialog(title, message):
    safe_title = title.replace('"', '\\"')
    safe_message = message.replace('"', '\\"')

    script = (
        f'display dialog "{safe_message}" '
        f'with title "{safe_title}" '
        'buttons {"OK"} default button "OK" with icon caution'
    )

    subprocess.run(["osascript", "-e", script], check=False)


def send_projectdiscovery_notify(message):
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

    subprocess.run(
        cmd,
        input=message,
        text=True,
        capture_output=not SHOW_VERBOSE_ERRORS,
        check=False,
    )


def alert_new_party(title, long_message):
    run_macos_notification(title, long_message[:220])
    run_macos_dialog(title, long_message[:1800])
    send_projectdiscovery_notify(f"{title}\n\n{long_message}")


def get_all_iphones():
    response = requests.get(DEVICE_API, timeout=30)
    response.raise_for_status()

    devices = []

    for device in response.json():
        identifier = device.get("identifier", "")

        if identifier.startswith("iPhone"):
            devices.append({
                "name": device.get("name", identifier),
                "identifier": identifier,
            })

    devices.sort(key=lambda item: item["identifier"])
    return devices


def fetch_firmwares(identifier):
    url = FIRMWARE_API.format(identifier=identifier)

    response = requests.get(url, timeout=30)
    response.raise_for_status()

    firmwares = [
        fw for fw in response.json().get("firmwares", [])
        if fw.get("url") and fw.get("version") and fw.get("buildid")
    ]

    firmwares.sort(
        key=lambda fw: version_tuple(fw["version"]),
        reverse=True
    )

    return firmwares[:RECENT_FIRMWARE_LIMIT]


def download_manifest(ipsw_url, identifier, version, buildid):
    out_dir = MANIFEST_DIR / identifier / version
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = out_dir / f"{buildid}_BuildManifest.plist"

    if manifest_path.exists():
        return manifest_path

    print(light(f"  downloading BuildManifest: iOS {version} ({buildid})"))

    with RemoteZip(ipsw_url) as zip_file:
        data = zip_file.read("BuildManifest.plist")

    manifest_path.write_bytes(data)

    return manifest_path


def tsschecker_is_signed(manifest_path, identifier, version):
    result = subprocess.run(
        [
            TSSCHECKER_PATH,
            "--nocache",
            "--no-baseband",
            "--device", identifier,
            "--ios", version,
            "--build-manifest", str(manifest_path),
        ],
        capture_output=True,
        text=True,
    )

    output = (result.stdout + "\n" + result.stderr).lower()

    if "is being signed" in output:
        return True, "signed"

    if "not being signed" in output or "not signed" in output:
        return False, "not signed"

    if SHOW_VERBOSE_ERRORS:
        return False, output[-700:].strip() or "unknown response"

    return False, "check failed"


def check_firmware(device, firmware):
    identifier = device["identifier"]

    try:
        manifest = download_manifest(
            firmware["url"],
            identifier,
            firmware["version"],
            firmware["buildid"],
        )

        signed, reason = tsschecker_is_signed(
            manifest,
            identifier,
            firmware["version"],
        )

        return {
            "device": device,
            "firmware": firmware,
            "signed": signed,
            "reason": reason,
            "error": None,
        }

    except Exception as error:
        return {
            "device": device,
            "firmware": firmware,
            "signed": False,
            "reason": "check failed",
            "error": str(error),
        }


def check_device(device):
    name = device["name"]
    identifier = device["identifier"]
    chip = DEVICE_CHIPS.get(identifier, "unknown chip")

    print(f"\n{bold('Checking')} {name} {white(f'({identifier}, {chip})')}")

    try:
        firmwares = fetch_firmwares(identifier)
    except Exception as error:
        if SHOW_VERBOSE_ERRORS:
            print(red(f"  [ERROR] Firmware fetch failed: {error}"))
        else:
            print(red("  Firmware fetch failed."))
        return []

    if not firmwares:
        print(red("  No firmware records found."))
        return []

    results = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [
            executor.submit(check_firmware, device, firmware)
            for firmware in firmwares
        ]

        for future in as_completed(futures):
            result = future.result()
            firmware = result["firmware"]
            version = firmware["version"]
            buildid = firmware["buildid"]
            jb_text = format_jailbreaks(identifier, version)

            if result["error"]:
                if SHOW_VERBOSE_ERRORS:
                    print(red(f"  [ERROR] iOS {version} ({buildid}): {result['error']}"))
                else:
                    print(red(f"  not signed: iOS {version} ({buildid}) - check failed ") + jb_text)
            elif result["signed"]:
                print(turquoise(f"  SIGNED: iOS {version} ({buildid}) ") + jb_text)
            else:
                print(red(f"  not signed: iOS {version} ({buildid}) - {result['reason']} ") + jb_text)

            results.append(result)

    signed = [
        result["firmware"]
        for result in results
        if result["signed"]
    ]

    if not signed:
        print(red("  No signed firmwares found."))
        return []

    signed.sort(
        key=lambda fw: version_tuple(fw["version"]),
        reverse=True
    )

    latest_signed = signed[0]["version"]

    downgrades = [
        fw for fw in signed
        if version_tuple(fw["version"]) < version_tuple(latest_signed)
    ]

    if not downgrades:
        print(red("  No downgrade parties."))
        return []

    print(turquoise("  DOWNGRADE PARTIES FOUND:"))

    found_downgrades = []

    for firmware in downgrades:
        version = firmware["version"]
        buildid = firmware["buildid"]
        alert_key = f"{identifier}:{version}:{buildid}"
        jb_names = jailbreak_matches(identifier, version)
        jb_text_plain = ", ".join(jb_names) if jb_names else "No known jailbreak match"

        if jb_names:
            print(turquoise(f"    - iOS {version} ({buildid}) 🔓 JB: {jb_text_plain}"))
        else:
            print(turquoise(f"    - iOS {version} ({buildid}) ") + red("❌ no known jailbreak match"))

        found_downgrades.append({
            "name": name,
            "identifier": identifier,
            "chip": chip,
            "version": version,
            "buildid": buildid,
            "alert_key": alert_key,
            "jailbreaks": jb_text_plain,
        })

        if not already_alerted(alert_key):
            long_message = (
                f"New downgrade party found!\n\n"
                f"Device: {name}\n"
                f"Identifier: {identifier}\n"
                f"Chip: {chip}\n"
                f"Firmware: iOS {version}\n"
                f"Build: {buildid}\n"
                f"Jailbreak match: {jb_text_plain}\n\n"
                f"This firmware is signed according to the current Apple TSS check."
            )

            alert_new_party("New Downgrade Party Found 🎉", long_message)
            mark_alerted(alert_key)

    return found_downgrades


def send_summary_alert(all_downgrades):
    if not all_downgrades:
        return

    count = len(all_downgrades)

    lines = [
        f"{item['name']} ({item['identifier']}, {item['chip']}) → "
        f"iOS {item['version']} ({item['buildid']}) | JB: {item['jailbreaks']}"
        for item in all_downgrades
    ]

    message = "Active downgrade parties:\n\n" + "\n".join(lines[:40])

    if count > 40:
        message += f"\n\n...and {count - 40} more."

    run_macos_notification(f"{count} Downgrade Parties Active 🎉", message[:220])
    send_projectdiscovery_notify(f"{count} Downgrade Parties Active 🎉\n\n{message}")


def print_jailbreak_summary():
    print(yellow("\nJailbreak cross-reference enabled:"))
    print(white("  - checkm8: A5-A11 bootrom exploit class"))
    print(white("  - palera1n: checkm8-based A8-A11 devices, modern iOS support"))
    print(white("  - Dopamine: iOS 15/16 rootless support with device-generation caveats"))
    print(white("  - Taurine: iOS 14.0-14.8.1"))
    print(white("  - unc0ver: conservative official range iOS 11.0-14.3"))
    print(red("  Note: This is best-effort matching. Always verify before restoring.\n"))


def main():
    print(turquoise(r"""
                 .:'
             __ :'__
          .'`__`-'__``.
         :__________.-'
         :_________:
          :_________`-;
           `.__.-.__.'

~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Apple TSS Downgrade Monitor - All iPhones
Jailbreak Cross-Reference Edition
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
"""))

    devices = get_all_iphones()

    print(turquoise(f"Loaded {len(devices)} iPhone models."))
    print(white(f"Using tsschecker: {TSSCHECKER_PATH}"))

    if ENABLE_PROJECTDISCOVERY_NOTIFY:
        if NOTIFY_PATH:
            print(white(f"Using ProjectDiscovery notify: {NOTIFY_PATH}"))
        else:
            print(red("ProjectDiscovery notify enabled, but notify was not found in PATH."))

    print_jailbreak_summary()

    while True:
        all_downgrades = []

        for device in devices:
            all_downgrades.extend(check_device(device))

        send_summary_alert(all_downgrades)

        if all_downgrades:
            print(turquoise(f"\nSUMMARY: {len(all_downgrades)} downgrade parties active."))
            for item in all_downgrades:
                print(turquoise(
                    f"  - {item['name']} ({item['identifier']}, {item['chip']}) "
                    f"iOS {item['version']} ({item['buildid']}) | JB: {item['jailbreaks']}"
                ))
        else:
            print(red("\nSUMMARY: No downgrade parties active."))

        print(white(f"\nChecking again in {CHECK_INTERVAL // 60} minutes...\n"))
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
