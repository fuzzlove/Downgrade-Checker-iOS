# Downgrade-Checker-iOS
iOS Downgrade Party Checker

UPDATE: Added new checks for jailbreaking availability along with checking for the last versions of the iOS and looking for any possibilities that an older release have been approved for downgrade.

---
Ackowledgement:    Thanks n8 for sparking the idea 💡 - also cheers to those that were there for the old party!
     Credit to:         ProjectDiscovery for Notify (Just one of many cool tools)
                           1Conan for tsschecker it made it easier to not rely on just ipsw.
---

Note: The checker is currently being updated for realtime alerts that will notify you and a more verbose list of jailbreaks with up to date version numbers for reliable referencing.

Downgrade Party Checker ✔

A real-time iOS firmware monitoring tool that alerts you when Apple is signing older firmware versions — a.k.a. “downgrade parties.”

This tool continuously tracks Apple’s signing status across iPhone models and notifies you the moment a previously unavailable downgrade becomes possible.

Features
Live iPhone model selection
Dynamically pulls all current iPhone models and lets you choose which devices to monitor.

Accurate signing checks
Uses the IPSW.me API to detect currently signed firmware versions.

Automatic downgrade detection
Identifies when older iOS versions are signed alongside newer ones.

Real-time notifications (macOS)
Get instant alerts when a new downgrade opportunity appears.

Continuous monitoring loop
Runs in the background and checks every 5 minutes.

Smart tracking
Only alerts you on new downgrade events — no spam.

What is a “Downgrade Party”?
A “downgrade party” happens when Apple temporarily signs multiple firmware versions at once, allowing devices to be restored to an older iOS version.

These windows are usually:
1. Short-lived
2. Unpredictable
3. Valuable for researchers, jailbreakers, and testers

Use Cases:
1. iOS security research
2. Jailbreak window tracking
3. Firmware testing & regression analysis
4. Staying ahead of Apple signing changes

Requirements:
Python 3.x
macOS (for native notifications via osascript)

For notifications:
https://github.com/projectdiscovery/notify
https://github.com/1Conan/tsschecker/releases

Usage:
1. python3 downgrade_checker.py
2. Select the iPhone models you want to monitor
3. Leave it running
4. Get notified when a downgrade becomes available
5. Update: Now available with a background daemon thats constantly looking for a potential downgrade party!

Data Source:
Firmware links provided by IPSW API, gs.apple.com used for proper validation.

Disclaimer:
This tool is for educational and research purposes only.
Apple Inc's signing status can change at any time, and downgrades may still be limited by device.
