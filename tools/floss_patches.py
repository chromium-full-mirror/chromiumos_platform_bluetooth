#!/usr/bin/env python3
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""A script for manipulating the Floss upstream/local patches"""

import argparse
import base64
from datetime import datetime
from datetime import timezone
import json
import logging
import os
from pathlib import Path
import re
import shutil
import string
import subprocess
import tempfile
import textwrap
import urllib.error
import urllib.request


class GitHelper(object):
    """Git helper class that runs git commands on a specific path."""

    def __init__(self, path):
        self.path = path
        self.git_command = ["git", "-C", str(self.path)]

    def clone(self, repo_url, branch=None, depth=None):
        """Clones a remote repo to local.

        Args:
            repo_url: The remote repo URL str.
            branch: The target branch name. If None, clones all branches.
            depth: The history depth. If None, clones the full history.
        """
        cmd = ["git", "clone"]
        if branch is not None:
            cmd.append("--branch")
            cmd.append(branch)
        if depth is not None:
            cmd.append("--depth")
            cmd.append(str(depth))
        cmd.append(repo_url)
        cmd.append(str(self.path))
        subprocess.check_call(cmd)

    def add(self):
        """Adds all changes into index."""
        subprocess.check_call(self.git_command + ["add", "."])

    def commit(self, msg):
        """Create a commit containing the current contents of the index

        Args:
            msg: commit message to the new commit
        """
        subprocess.check_call(self.git_command + ["commit", "-m", msg])

    def checkout(self, hash):
        subprocess.check_call(self.git_command + ["checkout", "--quiet", hash])

    def am(self, patches):
        subprocess.check_call(self.git_command + ["am"] + patches)

    def rebase(self, hash):
        subprocess.check_call(self.git_command + ["rebase", hash])

    def diff(self, stat=None):
        """Returns the diff of the cached (staged) changes.

        Args:
            stat: The diff stat format.
        """
        cmd = ["diff", "--cached"]
        if stat is not None:
            cmd.append(f"--stat={stat}")
        return subprocess.check_output(self.git_command + cmd)

    def format_patch(
        self, range, out_dir=None, stdout=False, unified=None, signature=None
    ):
        """Generates patches.

        Args:
            range: The git revision range str. For example HASH1..HASH2
                   generates patches for each commit between HASH1 and HASH2,
                   while HASH1 is not included but HASH2 is.
                   Alternatively, use -<n> to generate patches from the topmost
                   <n> commits.
            out_dir: The output directory path str.
            stdout: If True, don't generate the patch file and dump it to stdout
                    instead.
            unified: An int indicating the lines before and after the changed
                     lines.
            signature: The signature str at the end of the patch file.

        Returns:
            The standard output of the command, decoded with utf-8.
        """
        cmd = ["format-patch", range]
        if out_dir is not None:
            cmd.append("--output-directory")
            cmd.append(out_dir)
        if stdout:
            cmd.append("--stdout")
        if unified is not None:
            cmd.append(f"--unified={unified}")
        if signature is None:
            cmd.append("--no-signature")
        else:
            cmd.append(f"--signature={signature}")
        return subprocess.check_output(self.git_command + cmd).decode("utf-8")

    def fetch(self, repository=None, refspec=None):
        """Fetches a repo from the remote repository.

        Args:
            repository: The remote repo URL str.
            refspec: The target branches spec str. Would be ignored if
                     |repository| is None.
        """
        cmd = self.git_command + ["fetch"]
        if repository:
            cmd.append(repository)
            if refspec:
                cmd.append(refspec)
        subprocess.check_call(cmd)

    def get_head_commit(self):
        return (
            subprocess.check_output(
                self.git_command + ["log", "-1", "--format=format:%H"]
            )
            .decode("utf-8")
            .strip()
        )

    def is_clean(self):
        return (
            subprocess.check_output(
                self.git_command + ["status", "--porcelain"]
            )
            == b""
        )

    def check_is_ancestor(self, lhs, rhs):
        subprocess.check_call(
            self.git_command + ["merge-base", lhs, "--is-ancestor", rhs]
        )


class OverlayHelper(object):
    """Helper for modifying the given chromiumos-overlay repo."""

    GIT_AM_HINT_PREFIX = "DEV_PATCHES=(  # git am hint: "
    REL_PATCHES_START_LINE = "REL_PATCHES=(\n"
    REL_PATCHES_END_LINE = ")  # REL_PATCHES end\n"

    def __init__(self, path, is_upstream):
        self.overlay_path = path

        overlay_name = "floss-upstream" if is_upstream else "floss"
        self.floss_overlay_path = (
            self.overlay_path / "net-wireless" / overlay_name
        )
        if not self.floss_overlay_path.is_dir():
            raise ValueError("Failed to anchor Floss overlay directory path")

        self.ebuild_path = (
            self.floss_overlay_path / f"{overlay_name}-9999.ebuild"
        )
        if not self.ebuild_path.is_file():
            raise ValueError("Failed to anchor Floss ebuild path")

    def floss_update_git_am_hint(self, hint):
        """Updates the git am hint in floss-9999.ebuild.

        The hint indicates the "known good commit" that the upstream patches
        can be applied on without conflicts. There are 2 common timing to
        update it:
            * Some upstream conflicts are fixed
            * A new merge from upstream to local just landed (local and
              upstream tree should be exactly the same on the point of merge,
              if the merge passed CQ then it must be a good commit)

        Args:
            hint: The 40-letters SHA-1 hash.
        """
        if len(hint) != 40 or any(c not in string.hexdigits for c in hint):
            raise ValueError(
                "Invalid git am hint, expect a 40-digits commit hash"
            )

        with open(str(self.ebuild_path), "r") as filehandle:
            floss_build_lines = filehandle.readlines()
        for i in range(len(floss_build_lines)):
            if floss_build_lines[i].startswith(self.GIT_AM_HINT_PREFIX):
                logging.debug(
                    "Changing git am hint from %s to %s",
                    floss_build_lines[i][len(self.GIT_AM_HINT_PREFIX) : -1],
                    hint,
                )
                floss_build_lines[i] = f"{self.GIT_AM_HINT_PREFIX}{hint}\n"
                break
        else:
            raise RuntimeError("Git am hint not found in ebuild")
        logging.debug(
            "Update %s's `git am hint` with the specified hint",
            self.ebuild_path,
        )
        with open(str(self.ebuild_path), "w") as filehandle:
            filehandle.writelines(floss_build_lines)

    def floss_get_git_am_hint(self):
        with open(str(self.ebuild_path), "r") as filehandle:
            for line in filehandle:
                if line.startswith(self.GIT_AM_HINT_PREFIX):
                    return line[len(self.GIT_AM_HINT_PREFIX) : -1]
        raise RuntimeError("Git am hint not found in ebuild")

    def floss_add_new_release_patch(self, subject, content):
        """Adds a new release patch in ChromiumOS overlay.

        Determines the new patch file name, writes the content, and updates the
        floss ebuild.

        Args:
            subject: The subject string of the patch, this is used for
                     determining the patch filename.
            content: The patch file content. This is write to the disk as is.
        """
        with open(str(self.ebuild_path), "r") as filehandle:
            floss_ebuild_lines = filehandle.readlines()

        # Determine the new patch file number by reading the last one.
        rel_patches_end_line = floss_ebuild_lines.index(
            self.REL_PATCHES_END_LINE
        )
        patch_dirpath = '\t"${FILESDIR}"/patches/'
        last_patch_file_line = floss_ebuild_lines[rel_patches_end_line - 1]
        if (
            last_patch_file_line == self.REL_PATCHES_START_LINE
            or last_patch_file_line.startswith(patch_dirpath + "0")
        ):
            # No existing patches or no upstream patches, starts from 1001.
            new_file_num = "1001"
        elif last_patch_file_line.startswith(patch_dirpath):
            # At least one upstream patch exists, use the next number.
            last_patch_file_name = last_patch_file_line[len(patch_dirpath) :]
            last_patch_file_num = last_patch_file_name[
                : last_patch_file_name.index("-")
            ]
            if (
                len(last_patch_file_num) != 4
                or not last_patch_file_num.isdigit()
            ):
                raise RuntimeError(
                    "Invalid patch file name: {}".format(last_patch_file_name)
                )
            new_file_num = str(int(last_patch_file_num, base=10) + 1)
        else:
            raise RuntimeError(
                "Invalid line before REL_PATCHES array end: {}".format(
                    last_patch_file_line
                )
            )

        # Compose the name. Only allow alpha number and separate the words with
        # "-". E.g. "CHROMIUM: Add sco quirk for pixel buds pro" ->
        # "0001-CHROMIUM-Add-sco-quirk-for-pixel-buds-pro.patch"
        new_file_name = "-".join(
            [new_file_num] + re.split("[^a-zA-Z0-9_]+", subject)
        )
        if len(new_file_name) + len(".patch") > 63:
            new_file_name = (
                new_file_name[:57] + ".patch"
            )  # 57 == 63 - len(".patch")
        else:
            new_file_name += ".patch"

        # Update ebuild
        with open(str(self.ebuild_path), "w") as filehandle:
            filehandle.writelines(floss_ebuild_lines[:rel_patches_end_line])
            filehandle.write(patch_dirpath + new_file_name + "\n")
            filehandle.writelines(floss_ebuild_lines[rel_patches_end_line:])

        # Write the content to the disk
        rel_patches_path = self.floss_overlay_path / "files" / "patches"
        if not rel_patches_path.exists():
            os.mkdir(rel_patches_path, mode=0o750)
        if not rel_patches_path.is_dir():
            raise ValueError(f"{rel_patches_path} is not a dir")
        with open(str(rel_patches_path / new_file_name), "w") as filehandle:
            filehandle.write(content)


def gerrit(
    api_name,
    method=None,
    data=None,
    instance="chromium",
    auth=True,
    raw_response=False,
):
    """Sends requests to CrOS external Gerrit instance.

    Args:
        api_name: The Gerrit API name as part of Gerrit request URL.
        method: HTTP method e.g. 'GET', 'POST'.
        data: The HTTP body. It is always converted to JSON.
        instance: The Gerrit server instance such as "chromium" or "android"
        auth: Whether auth should be done for the method.
        raw_response: If True, do not parse the response and return the bytes
                      directly.

    Returns:
        None if no response, the raw bytes of response if |raw_response|, or the
        parsed JSON response.
    """

    def get_git_cookies(path):
        """Returns the user's gitcookies matching the path."""
        cookies = {}
        with open(str(Path.home() / ".gitcookies"), "r") as filehandle:
            for line in filehandle:
                fields = line.strip().split("\t")
                if line.strip().startswith("#") or len(fields) != 7:
                    continue
                domain, xpath, key, value = (
                    fields[0],
                    fields[2],
                    fields[5],
                    fields[6],
                )
                if (
                    domain == "chromium-review.googlesource.com"
                    and path.startswith(xpath)
                ):
                    cookies[key] = value
        if not cookies:
            raise RuntimeError("Valid git cookie not found")
        return "; ".join(f"{k}={v}" for k, v in cookies.items())

    url = f"https://{instance}-review.googlesource.com/"
    headers = {}
    if auth:
        url += "a/"
        headers["Cookie"] = get_git_cookies(f"/a/{api_name}")
    url += api_name
    if data is not None:
        data = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    logging.debug("Calling Gerrit API: URL=%s, method=%s", url, method)
    with urllib.request.urlopen(req) as handle:
        response = handle.read()

    if not response:
        return None

    if raw_response:
        return response

    response = response.decode("utf-8")
    MAGIC_PREFIX = ")]}'"
    if not response.startswith(MAGIC_PREFIX):
        raise RuntimeError("Unexpected Gerrit API response format")
    response = response[len(MAGIC_PREFIX) :]
    return json.loads(response)


def get_upstream_floss_and_overlay_path():
    cros_root = Path(__file__).resolve().parent
    for _ in range(4):
        cros_root = cros_root.parent
    floss_path = (
        cros_root
        / "src"
        / "aosp"
        / "packages"
        / "modules"
        / "Bluetooth"
        / "upstream"
    )
    overlay_path = cros_root / "src" / "private-overlays" / "chromeos-overlay"
    if not floss_path.is_dir():
        raise RuntimeError("Failed to anchor Floss upstream path in CrOS SDK")
    if not overlay_path.is_dir():
        raise RuntimeError("Failed to anchor chromeos-overlay in CrOS SDK")
    return floss_path, overlay_path


def get_chromiumos_overlay_path():
    cros_root = Path(__file__).resolve().parent
    for _ in range(4):
        cros_root = cros_root.parent
    overlay_path = cros_root / "src" / "third_party" / "chromiumos-overlay"
    if not overlay_path.is_dir():
        raise RuntimeError("Failed to anchor chromiumos-overlay in CrOS SDK")
    return overlay_path


def fix_upstream_patches():
    """Fix the upstream patches.

    Implementation of `floss_patches fix_upstream`.
    """
    floss_path, overlay_path = get_upstream_floss_and_overlay_path()
    overlay_helper = OverlayHelper(overlay_path, is_upstream=True)
    patches_path = (
        overlay_helper.floss_overlay_path / "files" / "patches_upstream"
    )

    if not patches_path.exists():
        logging.info("Patches directory doesn't exist; Nothing to be done")
        return
    if not patches_path.is_dir():
        raise ValueError(str(patches_path) + " is not a dir")

    logging.info("Fixing upstream patches, floss repo = %s", floss_path)

    hint = overlay_helper.floss_get_git_am_hint()
    logging.info("Current git am hint: %s", hint)

    git_helper = GitHelper(floss_path)
    if not git_helper.is_clean():
        raise RuntimeError("Floss upstream repo is not clean")
    git_helper.check_is_ancestor(hint, "cros-internal/upstream/main")

    # Am and rebase
    git_helper.checkout(hint)
    git_helper.am([str(p) for p in sorted(patches_path.iterdir())])
    try:
        git_helper.rebase("cros-internal/upstream/main")
    except subprocess.CalledProcessError:
        logging.warning(
            "!!! Please follow the instructions above to resolve the "
            "conflicts, then re-run the script with `--continue` !!!"
        )
        return

    logging.error(
        "Rebased successfully, which means no conflicts! "
        "Leaving the am-ed tree as is and exit."
    )


def fix_upstream_patches_continue():
    """Fix the upstream patches.

    Implementation of `floss_patches fix_upstream`.
    """
    floss_path, overlay_path = get_upstream_floss_and_overlay_path()
    overlay_helper = OverlayHelper(overlay_path, is_upstream=True)
    patches_path = (
        overlay_helper.floss_overlay_path / "files" / "patches_upstream"
    )

    git_helper = GitHelper(floss_path)
    if not git_helper.is_clean():
        raise RuntimeError("Floss upstream repo is not clean")
    if overlay_path.joinpath(".git", "rebase-merge").exists():
        raise RuntimeError(
            "Found .git/rebase-merge in overlay, rebase unfinished?"
        )

    logging.info(
        "Fixing (--continue) upstream patches, floss repo = %s", floss_path
    )

    # Remove old patches first
    if patches_path.exists():
        if not patches_path.is_dir():
            raise ValueError(str(patches_path) + "is not a dir")
        shutil.rmtree(str(patches_path))

    # Generate patches
    logging.info("Generating patch files...")
    rebased_head = git_helper.get_head_commit()
    git_helper.format_patch(
        f"cros-internal/upstream/main..{rebased_head}",
        out_dir=str(patches_path),
        unified=1,
        signature=None,
    )

    # Update hint
    git_helper.checkout("cros-internal/upstream/main")
    new_hint = git_helper.get_head_commit()
    overlay_helper.floss_update_git_am_hint(new_hint)

    logging.info(
        "Fix patches done. "
        "Test it with `USE=floss_upstream emerge-${BOARD} floss-upstream`, "
        "and upload the changes in %s for review.",
        overlay_path,
    )


def land_ag_patch(
    cl_number, hash, branch="main", dest=None, use_local_overlay=False
):
    """Creates a CrOS CL for an internal Bluetooth CL.

    Implementation of `floss_patches land`.
    """
    floss_path, _ = get_upstream_floss_and_overlay_path()
    git_helper = GitHelper(floss_path)
    try:
        patch_content = git_helper.format_patch(
            f"{hash}~..{hash}", unified=1, signature=None, stdout=True
        )
    except subprocess.CalledProcessError:
        response = input(
            "Failed to format patch for the hash, fetch "
            "cros-internal/upstream/main and retry? [N/y]"
        )
        if not response or response[0] not in "Yy":
            logging.info("Exiting")
            return
        git_helper.fetch("cros-internal", "upstream/main")
        patch_content = git_helper.format_patch(
            f"{hash}~..{hash}", unified=1, signature=None, stdout=True
        )

    subject = ""
    description_lines = []

    # Parse content, extract subject and description.
    # Subject could be multiple lines and ends with an empty line. Sample:
    #   Subject: [PATCH] This
    #    is subject
    #
    #   I am description 0.
    #
    #   I am description 1.
    #
    #   ---
    SUBJECT_START_LINE_PREFIX = "Subject: [PATCH] "
    DESCRIPTION_END_LINE = "---"
    parsing_subject = False
    parsing_description = False
    for line in patch_content.splitlines(keepends=False):
        if parsing_description:
            if line == DESCRIPTION_END_LINE:
                break
            else:
                description_lines.append(line)
        else:
            if parsing_subject:
                if line:
                    subject += line
                else:
                    parsing_description = True
            elif line.startswith(SUBJECT_START_LINE_PREFIX):
                subject = line[len(SUBJECT_START_LINE_PREFIX) :]
                parsing_subject = True
    else:
        raise RuntimeError("Failed to extract subject and description")

    # Compose new CL message. Remove floss prefix here to keep it consistent.
    subject = subject.strip()
    if subject[0:6].lower() == "floss:":
        subject = subject[6:].strip()
    # Some tags need to be removed and Bug/Test need renaming.
    description = ""
    bug = ""
    test = ""
    test_maybe_unfinished = False
    for line in description_lines:
        if line.startswith("Test: "):
            test += "TEST={}\n".format(line[len("Test: ") :].strip())
            test_maybe_unfinished = True
        elif line.startswith("Bug: "):
            # Multiple Bug tags in a single line is possible. This handles the
            # below 2 cases although the 2nd is actually not parsed on Gerrit.
            #   - Bug: 1, Bug: 2, Bug: 3
            #   - Bug: 1, 2, 3
            for tok in line.split(sep=","):
                tok = tok.strip()
                if tok.startswith("Bug:"):
                    tok = tok[len("Bug:") :].strip()
                if tok.isdigit():
                    bug += f"BUG=b:{tok}\n"
                else:
                    raise RuntimeError(f"Unexpected char in Bug tag: {tok}")
            test_maybe_unfinished = False
        elif (
            line.startswith("Tag: ")
            or line.startswith("Flag: ")
            or line.startswith("Change-Id: ")
        ):
            # Drop it
            test_maybe_unfinished = False
        else:
            if not line.startswith(" "):
                # If not starting with space, treat the Test tag ended.
                test_maybe_unfinished = False

            if test_maybe_unfinished:
                test += line + "\n"
            else:
                description += line + "\n"

    # If description is not empty, append a blank line to separate it from the
    # following "cherry-pick ... " line.
    description = description.strip()
    if description:
        description += "\n\n"

    cl_message = f"""\
floss UPSTREAM: {subject}

{description}(cherry-pick from http://ag/{cl_number})

{bug.strip() or 'BUG=None'}
{test.strip() or 'TEST=CQ'}
"""

    if use_local_overlay:
        overlay_path = get_chromiumos_overlay_path()
        git_helper = GitHelper(overlay_path)
        if not git_helper.is_clean():
            raise RuntimeError("Local overlay repo is not clean")
        overlay_helper = OverlayHelper(overlay_path, is_upstream=False)
        overlay_helper.floss_add_new_release_patch(
            "UPSTREAM: " + subject, patch_content
        )
        git_helper.add()
        git_helper.commit(msg=cl_message)
        return

    # Generate the overlay diff in a temporary directory.
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir = Path(temp_dir)
        git_helper = GitHelper(temp_dir)
        logging.info("Cloning chromiumos-overlay...")
        # Cloning with depth=1 because the history is really heavy (~2GB).
        git_helper.clone(
            "https://chromium.googlesource.com/chromiumos/overlays/chromiumos-overlay",
            branch=branch,
            depth=1,
        )
        overlay_helper = OverlayHelper(temp_dir, is_upstream=False)
        overlay_helper.floss_add_new_release_patch(
            "UPSTREAM: " + subject, patch_content
        )

        git_helper.add()

        # If --dest is set then we simply generate a patch file and return
        if dest is not None:
            git_helper.commit(msg=cl_message)
            git_helper.format_patch("-1", out_dir=dest)
            return

        # Otherwise continue submitting to Gerrit
        diff = git_helper.diff()

    response = input(
        "@@@@@@@@@@@@@@@@@@@@@@@ description @@@@@@@@@@@@@@@@@@@@@@@@\n"
        f"{cl_message}"
        "@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@\n"
        "\n"
        "@@@@@@@@@@@@@@@@@@@@@@@@@@@ diff @@@@@@@@@@@@@@@@@@@@@@@@@@@\n"
        f"{diff.decode('utf-8')}"
        "@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@\n"
        "CAUTION: You are attempting to create a CL with the above description "
        "and diff, continue? [N/y] "
    )
    if len(response) == 0 or response[0] not in "Yy":
        logging.info("Exiting")
        return
    logging.info("Creating CL...")
    change_input = {
        "project": "chromiumos/overlays/chromiumos-overlay",
        "branch": branch,
        "subject": cl_message,
        "patch": {"patch": base64.b64encode(diff).decode("utf-8")},
    }
    cl = gerrit("changes/", method="POST", data=change_input)
    logging.info("Created CL: https://crrev.com/c/%s", cl["_number"])


def main():
    parser = argparse.ArgumentParser(
        description="Manipulate the Floss upstream/local patches"
    )
    parser.add_argument(
        "--log_level",
        choices=["debug", "info", "quiet"],
        default="info",
        help="Loging level. Default to 'info'",
    )
    subparsers = parser.add_subparsers(
        required=True,
        dest="command",
    )

    parser_fix_upstream = subparsers.add_parser(
        "fix_upstream",
        help=(
            "Helps rebase the upstream patches to ToT. The developer should "
            "resolve the conflicts in the .../Bluetooth/upstream repo on the "
            "local storage, and re-run this script with the '--continue' flag."
        ),
    )
    parser_fix_upstream.add_argument(
        "--continue",
        action="store_true",
        help=(
            "The 'fix_upstream' command stops when there are any conflicts "
            "that require deveplopers to resolve. Re-run the script with this "
            "flag to continue the progress."
        ),
        dest="continue_fix",
    )

    parser_land = subparsers.add_parser(
        "land",
        help=(
            "Lands an internal Android Bluetooth CL to CrOS. "
            "It creates a ChromiumOS overlay CL on CrOS Gerrit."
        ),
    )
    parser_land.add_argument(
        "--cl_number",
        type=int,
        required=True,
        help=(
            "The internal Android CL number (ag/XXXX) that's added in the "
            "commit message."
        ),
    )
    parser_land.add_argument(
        "--hash",
        required=True,
        help="Indicates the commit that is going to be landed to CrOS.",
    )
    parser_land.add_argument(
        "--branch",
        default="main",
        help=(
            "Defines which CrOS branch the 'land' command should land to such "
            "as 'release-R128-15964.B'. Default to 'main'"
        ),
    )
    parser_land.add_argument(
        "--dest",
        help=(
            "If specified, the patch won't be submitted to Gerrit, instead, we "
            "store a format patch under the specified path."
        ),
    )
    parser_land.add_argument(
        "--use_local_overlay",
        action="store_true",
        help=(
            "If specified, the patch won't be submitted to Gerrit, instead, "
            "the result is directly applied to the overlay. "
            "This overwrites arg --dest"
        ),
    )

    args = parser.parse_args()

    if args.log_level != "quiet":
        level = logging.DEBUG if args.log_level == "debug" else logging.INFO
        logging.basicConfig(
            format="%(asctime)s floss_patches: %(levelname)s: %(message)s",
            level=level,
        )

    if args.command == "fix_upstream":
        if args.continue_fix:
            fix_upstream_patches_continue()
        else:
            fix_upstream_patches()
    elif args.command == "land":
        land_ag_patch(
            args.cl_number,
            args.hash,
            branch=args.branch,
            dest=args.dest,
            use_local_overlay=args.use_local_overlay,
        )
    else:
        raise ValueError(f"Invalid command: {args.command}")


if __name__ == "__main__":
    main()
