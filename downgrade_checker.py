import json
import time
import urllib.request
import urllib.error
from urllib.parse import quote
import subprocess

DEVICES_API = "https://api.ipsw.me/v4/devices"
FIRMWARE_API = "https://api.ipsw.me/v4/device/{device}?type=ipsw"

seen_downgrades = {}

print(r"""
                 .:'
             __ :'__
          .'`__`-'__``.
         :__________.-'
         :_________:
          :_________`-;
           `.__.-.__.'
""")


def notify(title, message):
    try:
        subprocess.run([
            "osascript",
            "-e",
            f'display notification "{message}" with title "{title}"'
        ])
    except Exception as e:
        print(f"[NOTIFY ERROR] {e}")


def version_tuple(version):
    parts = []
    for part in version.split("."):
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def fetch_json(url):
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as e:
        print(f"[ERROR] Could not reach API: {e}")
        return None
    except json.JSONDecodeError:
        print("[ERROR] Invalid JSON response")
        return None


def fetch_iphone_devices():
    data = fetch_json(DEVICES_API)
    if not data:
        return []

    iphones = []

    for device in data:
        identifier = device.get("identifier", "")
        name = device.get("name", "")

        if identifier.startswith("iPhone"):
            iphones.append({
                "identifier": identifier,
                "name": name
            })

    iphones.sort(key=lambda d: d["name"])
    return iphones


def select_devices_menu(iphones):
    print("\nAvailable iPhone models:\n")

    for index, device in enumerate(iphones, start=1):
        print(f"{index:2}. {device['name']}  ({device['identifier']})")

    print("\nExamples:")
    print("  1,3,5       watch specific models")
    print("  1-5         watch a range")
    print("  all         watch all iPhones")
    print("  q           quit")

    choice = input("\nWhich iPhone models do you want to watch? ").strip().lower()

    if choice == "q":
        raise SystemExit

    if choice == "all":
        return iphones

    selected_indexes = set()

    for part in choice.split(","):
        part = part.strip()

        if "-" in part:
            start, end = part.split("-", 1)
            if start.isdigit() and end.isdigit():
                selected_indexes.update(range(int(start), int(end) + 1))
        elif part.isdigit():
            selected_indexes.add(int(part))

    selected = []

    for index in selected_indexes:
        if 1 <= index <= len(iphones):
            selected.append(iphones[index - 1])

    return selected


def fetch_firmwares(device_identifier):
    url = FIRMWARE_API.format(device=quote(device_identifier))
    return fetch_json(url)


def check_device(device):
    identifier = device["identifier"]

    data = fetch_firmwares(identifier)
    if not data:
        return

    name = data.get("name", device["name"])
    firmwares = data.get("firmwares", [])

    signed = [
        fw for fw in firmwares
        if fw.get("signed") is True and fw.get("version")
    ]

    if not signed:
        print(f"\n{name} ({identifier})")
        print("No signed IPSWs found.")
        return

    signed.sort(key=lambda fw: version_tuple(fw["version"]), reverse=True)

    latest = signed[0]["version"]

    downgrades = [
        fw for fw in signed
        if version_tuple(fw["version"]) < version_tuple(latest)
    ]

    print(f"\n{name} ({identifier})")
    print(f"Latest signed: iOS {latest}")

    if identifier not in seen_downgrades:
        seen_downgrades[identifier] = set()

    if downgrades:
        print("DOWNGRADE PARTIES:")
        for fw in downgrades:
            version = fw.get("version")
            build = fw.get("buildid", "unknown build")
            print(f"  - iOS {version} ({build})")
    else:
        print("No downgrade parties.")

    new_downgrades = []

    for fw in downgrades:
        version = fw.get("version")
        build = fw.get("buildid", "unknown build")
        downgrade_id = f"{version}:{build}"

        if downgrade_id not in seen_downgrades[identifier]:
            new_downgrades.append(fw)

    for fw in new_downgrades:
        version = fw.get("version")
        build = fw.get("buildid", "unknown build")

        notify(
            "Downgrade Party Found 🎉",
            f"{name} ({identifier}) → iOS {version} ({build}) is signed"
        )

        print(f"[NEW] Downgrade found: {name} → iOS {version} ({build})")

        seen_downgrades[identifier].add(f"{version}:{build}")


def main():
    print("""
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Downgrade Party Checker - Live Monitor
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
""")

    iphones = fetch_iphone_devices()

    if not iphones:
        print("Could not load iPhone device list.")
        return

    selected_devices = select_devices_menu(iphones)

    if not selected_devices:
        print("No valid devices selected.")
        return

    print("\nWatching these devices:")
    for device in selected_devices:
        print(f"  - {device['name']} ({device['identifier']})")

    print("\nStarting monitor...\n")

    first_run = True

    while True:
        for device in selected_devices:
            check_device(device)

        if first_run:
            print("\nInitial scan complete. Future newly signed downgrades will trigger alerts.")
            first_run = False

        print("\nChecking again in 5 minutes...\n")
        time.sleep(300)


if __name__ == "__main__":
    main()
