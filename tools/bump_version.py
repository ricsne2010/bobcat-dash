#!/usr/bin/env python3
"""Set the dash's software version and build date (version.py).

  python3 tools/bump_version.py 1.1.0               version 1.1.0, built today
  python3 tools/bump_version.py 1.1.0 --date 2026-11-02

Afterwards remake the boot splash picture so the Pi's boot screen shows the new number:
  python3 dash.py --boot-splash      (then copy it into Plymouth, see README: Monitor and boot splash)
"""
import argparse
import datetime
import os
import re
import sys

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "version.py")


def main():
    ap = argparse.ArgumentParser(description="Set the software version and build date")
    ap.add_argument("version", help="e.g. 1.1.0")
    ap.add_argument("--date", default=datetime.date.today().isoformat(), help="YYYY-MM-DD (default: today)")
    a = ap.parse_args()
    if not re.fullmatch(r"\d+(\.\d+){1,3}", a.version):
        sys.exit(f"version should look like 1.1.0, not {a.version!r}")
    datetime.date.fromisoformat(a.date)                # rejects a bad date
    s = open(PATH).read()
    s = re.sub(r'^VERSION = ".*"$', f'VERSION = "{a.version}"', s, flags=re.M)
    s = re.sub(r'^BUILD_DATE = ".*"$', f'BUILD_DATE = "{a.date}"', s, flags=re.M)
    open(PATH, "w").write(s)
    print(f"version {a.version}, built {a.date}")


if __name__ == "__main__":
    main()
