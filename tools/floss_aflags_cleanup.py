#!/usr/bin/env python3
# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""A script for cleaning up the removed Floss Aflags"""

import argparse
from pathlib import Path
import re


AFLAG_PREFIX = (
    "persist.device_config.aconfig_flags.bluetooth.com.android.bluetooth.flags."
)
AFLAG_DECLARATION_REGEX = re.compile(r'^\s*name\s*:\s*"([0-9a-z_]+)"\s*$')


def gen_available_flags(floss_flags_path, overlay_patches_path):
    ret = set()

    def extract_flag_name(line):
        flag_match = AFLAG_DECLARATION_REGEX.match(line)
        if flag_match:
            ret.add(flag_match.group(1))

    for f in Path(floss_flags_path).rglob("*.aconfig"):
        if not f.is_file():
            continue
        with open(str(f), "r") as filehandle:
            for line in filehandle.readlines():
                extract_flag_name(line)
    for f in Path(overlay_patches_path).rglob("*"):
        if not f.is_file():
            continue
        with open(str(f), "r") as filehandle:
            for line in filehandle.readlines():
                # For patch files we only care about the "added" lines
                if line.startswith("+"):
                    extract_flag_name(line[1:])
    return ret


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Clean up the Floss Aflags in chromiumos-overlay that are already "
            "removed in .../Bluetooth/local"
        ),
    )
    parser.add_argument(
        "--upstream",
        action="store_true",
        default=False,
        help="Deal with chromeos-overlay and .../Bluetooth/upstream instead",
    )

    args = parser.parse_args()

    cros_root = Path(__file__).resolve().parents[4]
    floss_flags_path = (
        cros_root
        / "src"
        / "aosp"
        / "packages"
        / "modules"
        / "Bluetooth"
        / ("upstream" if args.upstream else "local")
        / "flags"
    )
    overlay_files_path = (
        cros_root
        / "src"
        / ("private-overlays" if args.upstream else "third_party")
        / ("chromeos-overlay" if args.upstream else "chromiumos-overlay")
        / "net-wireless"
        / ("floss-upstream" if args.upstream else "floss")
        / "files"
    )

    if not floss_flags_path.is_dir():
        raise RuntimeError("Failed to anchor Floss flags path in CrOS SDK")
    if not overlay_files_path.is_dir():
        raise RuntimeError("Failed to anchor overlay files path in CrOS SDK")

    available_flags = gen_available_flags(
        floss_flags_path,
        overlay_files_path
        / ("patches_upstream" if args.upstream else "patches"),
    )

    def keep_line(line):
        # Comments or something else, keep
        if not line.startswith(AFLAG_PREFIX):
            return True
        flag_name = line[len(AFLAG_PREFIX) :].split("=")[0]
        return flag_name in available_flags

    with open(
        str(overlay_files_path / "config" / "aflags.conf"), "r"
    ) as filehandle:
        aflags_conf_lines = [l for l in filehandle.readlines() if keep_line(l)]
    with open(
        str(overlay_files_path / "config" / "aflags.conf"), "w"
    ) as filehandle:
        filehandle.writelines(aflags_conf_lines)

    # No need to check upstream's unstable_aflags.conf as it is empty
    if args.upstream:
        return
    with open(
        str(overlay_files_path / "config" / "unstable_aflags.conf"), "r"
    ) as filehandle:
        missing_flags = [l for l in filehandle.readlines() if not keep_line(l)]
    if missing_flags:
        print("WARNING: The below unstable flags are missing in the codebase!!")
        for line in missing_flags:
            print(line, end="")


if __name__ == "__main__":
    main()
