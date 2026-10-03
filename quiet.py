#!/usr/bin/python3
"""Toggle XFCE Do Not Disturb, or read/set it for the Abide window."""
import subprocess
import sys

BASE = ["xfconf-query", "-c", "xfce4-notifyd", "-p", "/do-not-disturb"]


def status():
    result = subprocess.run(BASE, capture_output=True, text=True, timeout=3)
    if result.returncode:
        if "does not exist" in result.stderr:
            return False
        raise RuntimeError(result.stderr.strip() or "Cannot connect to notification settings.")
    return result.stdout.strip() == "true"


def main():
    argument = sys.argv[1] if len(sys.argv) > 1 else "--toggle"
    if argument not in ["--status", "--toggle", "--on", "--off"]:
        raise SystemExit("Usage: abide-quiet [--status|--toggle|--on|--off]")
    current = status()
    if argument == "--status":
        print(str(current).lower())
        return
    desired = not current if argument == "--toggle" else argument == "--on"
    subprocess.run(BASE + ["-n", "-t", "bool", "-s", str(desired).lower()], check=True, timeout=3)
    print("Quiet mode " + ("on." if desired else "off."))


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error))
