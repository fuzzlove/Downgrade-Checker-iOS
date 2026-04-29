import json
import time
import urllib.request
import urllib.error
from urllib.parse import quote
import subprocess

DEVICES = [
    "iPhone13,2",
    "iPhone10,5",
    "iPhone9,4",
    "iPhone9,3",
]

API_URL = "https://api.ipsw.me/v4/device/{device}?type=ipsw"

# Track previously seen downgrade versions
seen_downgrades = {}


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
    return tuple(int(part) for part in version.split(".") if part.isdigit())


def fetch_firmwares(device):
    url = API_URL.format(device=quote(device))

    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as e:
        print(f"[ERROR] {device}: {e}")
        return None
    except json.JSONDecodeError:
        print(f"[ERROR] {device}: Invalid JSON response")
        return None


def check_device(device):
    global seen_downgrades

    data = fetch_firmwares(device)
    if not data:
        return

    name = data.get("name", device)
    firmwares = data.get("firmwares", [])

    signed = [
        fw for fw in firmwares
        if fw.get("signed") is True and fw.get("version")
    ]

    if not signed:
        print(f"\n{name} ({device}) - No signed IPSWs")
        return

    signed.sort(key=lambda fw: version_tuple(fw["version"]), reverse=True)

    latest = signed[0]["version"]

    downgrades = [
        fw["version"] for fw in signed
        if version_tuple(fw["version"]) < version_tuple(latest)
    ]

    print(f"\n{name} ({device})")
    print(f"Latest signed: iOS {latest}")

    if device not in seen_downgrades:
        seen_downgrades[device] = set()

    new_downgrades = set(downgrades) - seen_downgrades[device]

    if downgrades:
        print("DOWNGRADE PARTIES:")
        for v in downgrades:
            print(f"  - iOS {v}")
    else:
        print("No downgrade parties.")

    # 🔥 Trigger popup for NEW ones only
    if new_downgrades:
        for v in new_downgrades:
            notify(
                "Downgrade Party Found 🎉",
                f"{name} ({device}) → iOS {v} is now signed"
            )

        seen_downgrades[device].update(new_downgrades)


def main():
    print("""
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Downgrade Party Checker (Live Monitor)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
""")

    while True:
        for device in DEVICES:
            check_device(device)

        print("\nChecking again in 5 minutes...\n")
        time.sleep(300)


if __name__ == "__main__":
    main()
