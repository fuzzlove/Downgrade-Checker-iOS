# Downgrade-Checker-iOS
iOS Downgrade Party Checker

Based off script from NathansTech revamped to make an alert and recheck in a loop as before with any downgrades possible.

There was some broken issues with the 9yr old script interacting with the API. Maybe this will be helpful someday.

Here’s a strong GitHub repo description you can use (with a professional/security-tool tone):

🍏 Downgrade Party Checker

A real-time iOS firmware monitoring tool that alerts you when Apple is signing older firmware versions — a.k.a. “downgrade parties.”

This tool continuously tracks Apple’s signing status across iPhone models and notifies you the moment a previously unavailable downgrade becomes possible.

🚀 Features
📱 Live iPhone model selection
Dynamically pulls all current iPhone models and lets you choose which devices to monitor.

🔎 Accurate signing checks
Uses the IPSW.me API to detect currently signed firmware versions.

⬇️ Automatic downgrade detection
Identifies when older iOS versions are signed alongside newer ones.

🔔 Real-time notifications (macOS)
Get instant alerts when a new downgrade opportunity appears.

📊 Continuous monitoring loop
Runs in the background and checks every 5 minutes.

🧠 Smart tracking
Only alerts you on new downgrade events — no spam.

💡 What is a “Downgrade Party”?

A “downgrade party” happens when Apple temporarily signs multiple firmware versions at once, allowing devices to be restored to an older iOS version.

These windows are usually:

Short-lived ⏱️
Unpredictable 🎲
Valuable for researchers, jailbreakers, and testers 🔬

🛠️ Use Cases
iOS security research
Jailbreak window tracking
Firmware testing & regression analysis
Staying ahead of Apple signing changes

⚙️ Requirements
Python 3.x
macOS (for native notifications via osascript)

▶️ Usage
python3 downgrade_checker.py
Select the iPhone models you want to monitor
Leave it running
Get notified when a downgrade becomes available
📡 Data Source
Firmware & signing status provided by IPSW.me API
⚠️ Disclaimer

This tool is for educational and research purposes only.
Apple’s signing status can change at any time, and downgrades may still be limited by device-specific
