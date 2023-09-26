#!/usr/bin/env python3
# Lint as: python3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""A module to calculate the NSM (North Star Metric) of Floss Testing.

To calculate the NSM values for the floss tests, use the following command:
  $ python3 nsm.py nsm -f <floss_csv_file> -b <bluez_csv_file> [-v]

  Assume that there is a floss csv file containing test results stored as
        data/Floss_OSR_2023_0319_to_2023_0325_w1.csv

  Example:
  $ ./nsm.py nsm -f data/Floss_OSR_2023_0319_to_2023_0325_w1.csv
                 -b data/Bluez_OSR_R108-15183.71.0_162tests.csv -v

To calculate the NSM2 values by separating between the platform and
the non-platform tests, use the following command:
  $ ./nsm2.py nsm -f <floss_csv_file> -b <bluez_csv_file> -v

  Example:
  $ ./nsm.py nsm2 -f data/Floss_OSR_2023_0319_to_2023_0325_w1.csv
                  -b data/Bluez_OSR_R108-15183.71.0_162tests.csv -v
"""

import argparse
import collections
import csv
import os
import re
import sys


class NSM(object):
    """The class to calculate NSM values."""

    # These are the fields of the csv file downloaded from BigQuery.
    TESTHAUS = "testhaus"
    STAINLESS = "stainless"
    CSV_FIELDS_STAINLESS = [
        "row",
        "col",
        "pass",
        "warn",
        "fail",
        "other",
        "notrun",
    ]
    CSV_FIELDS_TESTHAUS = [
        "rowHeader",
        "rowHeaderArray",
        "columnHeader",
        "columnHeaderArray",
        "pass",
        "warn",
        "fail",
        "nostatus",
        "testNa",
        "notRun",
        "other",
    ]
    CSV_FIELDS = {
        TESTHAUS: CSV_FIELDS_TESTHAUS,
        STAINLESS: CSV_FIELDS_STAINLESS,
    }

    # Map to TEST_NAME, BUILD_NAME, PASS, FAIL
    TestInfoKey = collections.namedtuple(
        "TestInfoKey", ["name", "build", "pass_count", "fail_count"]
    )
    CSV_KEYS = {
        TESTHAUS: TestInfoKey("rowHeader", "columnHeader", "pass", "fail"),
        STAINLESS: TestInfoKey("row", "col", "pass", "fail"),
    }

    # These tests are not valid in floss since floss does not support the
    # corresponding features yet.
    INVALID_TEST_LIST = [
        # b/238234385
        "bluetooth_AdapterAdvMonitor.advmon_multi_client_tests",
        # b/238234386
        "bluetooth_AdapterAdvMonitor.advmon_suspend_resume_tests",
        # b/238210266
        "bluetooth_AdapterAdvMonitor.advmon_interleaved_scan_tests",
        # b/269327181
        "bluetooth_AdapterSAHealth.sa_adapter_pairable_timeout_test",
        # b/269301493
        "bluetooth_AdapterSRHealth.sr_suspend_delay_while_receiving_bqr",
        # b/238210265
        "bluetooth_AdapterAdvMonitor.advmon_fg_bg_combination_tests",
        # b/262455632
        "bluetooth_AdapterAdvHealth.adv_reboot_advertising_test",
        # b/262455632
        "bluetooth_AdapterEPHealth.ep_check_set_allowlist",
        # b/262455632
        "bluetooth_AdapterLEBetterTogether.smart_unlock_test",
        # b/262455632
        "bluetooth_AdapterQRHealth.qr_check_states_test",
    ]

    # The (number of executed tests / number of floss tests) * 100 must be
    # greater than or equal to this percentage for a build to be valid.
    # To avoid considering a build that produces too few test results, we set a
    # minimum threshold (included) for a valid build: % of tests being executed.
    TESTS_EXEC_PERCENT = 70

    # A test is treated as stable if its pass rate >= the value.
    # OSR stands for Overall Stability Ratio.
    OSR_CRITERION = 0.9

    BT_TEST_PREFIX = "bluetooth_Adapter"

    # The end of csv file names
    WAVE0_FILENAME_SUFFIX = "w0.csv"
    WAVE1_FILENAME_SUFFIX = "w1.csv"
    WAVE0_SUBSTR = "_w0"
    WAVE1_SUBSTR = "_w1"
    INTERSECTION_FILENAME_EXT = ".intersect_test_list"

    # The directory to save temporary intermediate files.
    TMP = "/tmp"
    # The data directory that contains the csv files.
    DATA = "data"

    DENOMINATOR_TEST_LIST = f"{TMP}/denominator_test_list"

    CATEGORY_PLATFORM = "Platform Bluetooth Tests"
    CATEGORY_NON_PLATFORM = "Non-Platform Bluetooth Tests"
    CATEGORY_ALL = "All Tests"

    DEV = "dev"
    BETA = "beta"
    LATEST_BETA_BUILD = "latest-beta-build"
    VALID_OSRS = "valid_osrs"
    FLOSS_DEV_AVE_NSM = "floss_dev_average_nsm"
    FLOSS_LATEST_BETA_BUILD = "floss_latest_beta_build"
    FLOSS_LATEST_BETA_NSM = "floss_latest_beta_nsm"
    FLOSS_DEV_AVE_OSR = "floss_dev_average_osr"
    FLOSS_LATEST_BETA_OSR = "floss_latest_beta_osr"
    BLUEZ_GOLDEN_OSR = "bluez_golden_osr"

    def __init__(
        self,
        bluez_csv_filepath,
        floss_csv_filepath,
        wave=None,
        start=None,
        end=None,
        verbose=False,
    ):
        """The constructor for the NSM class.

        Args:
            bluez_csv_filepath: The path to the bluez CSV file.
            floss_csv_filepath: The path to the floss CSV file.
            wave: the wave of the devices;
                possible values are 1, 2, 3 representing wave-1,
                wave-2, and wave-3 devices respectively.
          start: the start date for the test results
          end: the end date for the test results
          verbose: the flag to enable detailed logging messages.
        """
        self.bluez_csv_filepath = bluez_csv_filepath
        self.floss_csv_filepath = floss_csv_filepath
        self.wave = wave
        self.start = start
        self.end = end
        self.verbose = verbose

    @staticmethod
    def abort(message):
        """Prints the abort message and exits the program with return code 1."""
        print(f"Error: {message}. Aborted.")
        sys.exit(1)

    @staticmethod
    def check_filepath(filepath):
        """Checks whether the filepath exists or not.

        Args:
            filepath: the path of the file.
        """
        if not os.path.isfile(filepath):
            NSM.abort(f"The file {filepath} file does not exist.")

    @classmethod
    def get_and_verify_console_type(cls, csv_filepath):
        """Gets the console type from a CSV file.

        Console means which test result platform the CSV is from. The current
        console is either TESTHAUS or STAINLESS. Note that Stainless will be
        deprecated in 2023Q2.

        Args:
            csv_filepath: The path to the CSV file.

        Returns:
            The console type.
        """
        try:
            with open(csv_filepath, "r") as f:
                line = f.readline()
        except Exception as e:
            cls.abort(f"extract test list: {e}")

        fields = [i.strip() for i in line.split(",")]
        # The fields must strictly match one of the known console types.
        for console_type, console_fields in cls.CSV_FIELDS.items():
            if console_fields == fields:
                return console_type

        cls.abort(
            f"the csv file {csv_filepath} format is not recognized. "
            f"Fields: {fields}"
        )

    @staticmethod
    def strip_tauto_prefix(test_name):
        """Strip the 'tauto' prefix from the test name.

        This makes the test names consistent between Floss and Bluez.

        Returns:
            The test name without the 'tauto' prefix.
        """
        prefix = "tauto."
        if test_name.startswith(prefix):
            test_name = test_name[len(prefix) :]
        return test_name

    def exclude_tests(self, test_list):
        """Excludes the tests that are not valid in Floss.

        We exclude the tests that are not valid in Floss so that it is fair to
        compare the test results of Floss to BlueZ.

        Args:
            test_list: the original list of test names

        Returns:
            A list of test names that excludes those invalid ones.
        """
        return sorted(set(test_list) - set(self.INVALID_TEST_LIST))

    def extract_test_list_from_csv(self, filepath):
        """Extracts a list of test names from a CSV file.

        Args:
            filepath: The path to the CSV file.

        Returns:
            A list of sorted distinct test names.
        """
        self.check_filepath(filepath)
        try:
            with open(filepath, "r") as csvfile:
                console_type = self.get_and_verify_console_type(filepath)
                test_name_key = self.CSV_KEYS[console_type].name
                reader = csv.DictReader(csvfile)

                # Add the test name into a set. Note that duplicate test
                # names from multiple builds will be filtered away.
                distinct_test_names = {
                    self.strip_tauto_prefix(row[test_name_key])
                    for row in reader
                }

        except Exception as e:
            self.abort(f"extract test list: {e}")

        return sorted(distinct_test_names)

    def read_test_list(self, filepath):
        """Read a list of test names from a file.

        Args:
            filepath: The path to the file.

        Returns:
            A list of sorted distinct test names.
        """
        self.check_filepath(filepath)
        try:
            with open(filepath, "r") as file:
                distinct_test_names = {test_name.strip() for test_name in file}
        except Exception as e:
            self.abort(f"read test list: {e}")
        return sorted(distinct_test_names)

    @staticmethod
    def write_test_list(test_list, filepath):
        """Write the list of test names to a file.

        Args:
            test_list: A list of test names.
            filepath: The path to the file.
        """
        try:
            with open(filepath, "w") as f:
                for test in test_list:
                    f.write(test + "\n")
        except Exception as e:
            NSM.abort("Wrting %s: %s" % (filepath, e))

    @staticmethod
    def float_to_percent(value):
        """Convert a float to a percentage.

        Args:
            value: The float to convert.

        Returns:
            The rounded percentage value (0-100), or None if the value is None.
        """
        return None if value is None else round(100 * value)

    @staticmethod
    def removesuffix(line, suffix):
        """Remove the suffix from the line.

        The official removesuffix() is not available before python v3.9.
        Hence, a local version is handy.

        Args:
            suffix: The suffix to remove.
        """
        return line[: -len(suffix)] if line.endswith(suffix) else line

    @classmethod
    def categorize_tests(cls, tests):
        """Categorize the tests into platform and non-platform categories.

        Platform tests: tests owned by the ChromeOS Platform team.
        Non-platform tests: tests owned by the other teams, e.g.,
                the cross-device team. Such tests include tast.* and
                bluetooth_FastPair.* tests.

        Args:
            tests: The list of test names.

        Returns:
            A dictionary with two keys: CATEGORY_PLATFORM for platform tests
                and CATEGORY_NON_PLATFORM for non-platform tests.
        """
        platform_tests = []
        non_platform_tests = []
        for t in tests:
            if t.startswith(cls.BT_TEST_PREFIX):
                platform_tests.append(t)
            else:
                non_platform_tests.append(t)

        return {
            cls.CATEGORY_PLATFORM: platform_tests,
            cls.CATEGORY_NON_PLATFORM: non_platform_tests,
        }

    def calc_intersect_floss(self, bluez_test_list, floss_test_list):
        """Compute the intersection of floss with the bluez test list.

        Note that there are some possibilities.
        - floss_test_name = bluez_test_name + '.floss'
        - floss_test_name = bluez_test_name + '_floss'
        - floss_test_name = bluez_test_name + '-floss'
        - floss_test_name = bluez_test_name + '.floss_enabled'
        - floss_test_name = bluez_test_name + '.floss_enabled_oobe'

        A special case
        - tast.bluetooth.ToggleBluetoothFromQuickSettings.floss_disabled
        - tast.bluetooth.ToggleBluetoothFromQuickSettings.floss_enabled

        Args:
            bluez_test_list: The list of bluez test names.
            floss_test_list: The list of floss test names.

        Returns:
            A sorted list of Floss test names which have the BlueZ counterpart.
        """
        bluez_set = set(bluez_test_list)
        floss_name_re = re.compile(r"(.+).floss")
        floss_intersect_set = set()
        for ftest in floss_test_list:
            m = floss_name_re.search(ftest)
            if not m:
                self.abort(f"Check and fix: 'floss' is missing in {ftest}")
            btest = m[1]
            btest_variant = m[1] + ".floss_disabled"
            if btest in bluez_set or btest_variant in bluez_set:
                floss_intersect_set.add(ftest)
        return sorted(floss_intersect_set)

    @classmethod
    def is_wave1_csv(cls, csv_filepath):
        """Is the csv filepath for wave-1 devices?

        A csv file for wave-1 devices looks like
            Floss_OSR_2023_0312_to_2023_0318_w1.csv
        A csv file for wave-0 devices looks like
            Floss_OSR_2023_0312_to_2023_0318_w0.csv

        Args:
            csv_filepath: The path to the CSV file.

        Returns:
            True if the CSV file is a Wave-1 CSV file, False otherwise.
        """
        return csv_filepath.endswith(cls.WAVE1_FILENAME_SUFFIX)

    @classmethod
    def get_intersect_filepath(cls, csv_filepath, substr_to_remove):
        """Convert a csv filepath to the intersection filepath.

        Given a csv filepath, e.g.,
            ./Floss_OSR_2023_0312_to_2023_0318_w1.csv
        converts it to
            /tmp/Floss_OSR_2023_0312_to_2023_0318.intersect_test_list

        Args:
            csv_filepath: The path to the CSV file.
            substr_to_remove: The substring to remove.

        Returns:
            The resultant string of the file path.
        """
        base, ext = os.path.splitext(os.path.basename(csv_filepath))
        base = cls.removesuffix(base, substr_to_remove)
        intersect_filename = base + cls.INTERSECTION_FILENAME_EXT
        return os.path.join(cls.TMP, intersect_filename)

    def get_intersect_floss(
        self, floss_csv_filepath, floss_test_list, denominator_test_list
    ):
        """Get the intersection of tests between floss and the denominator list.

        If it is the floss csv file the wave-1 devices, calculate the
        intersection with bluez.
        Otherwise, the floss csv file is for wave-0 devices, the
        intersection should be taken from w1 to be complete.
        This is because a test may be missing for wave-0 for a whole week.
        This will impact how the validity of a build.

        Args:
            floss_csv_filepath: The path to the floss CSV file.
            floss_test_list: The list of floss test names.
            denominator_test_list: The list of test names as the denominator.

        Returns:
            The list of test names in the intersection.
        """
        if self.is_wave1_csv(floss_csv_filepath):
            intersect_test_list = self.calc_intersect_floss(
                denominator_test_list, floss_test_list
            )

            # Save the intersection test list derived from w1 so that
            # w0 can use it.
            intersect_filepath = self.get_intersect_filepath(
                floss_csv_filepath, self.WAVE1_SUBSTR
            )
            self.write_test_list(intersect_test_list, intersect_filepath)
            print(f"intersection test list written to {intersect_filepath}")
        else:
            # The w1's intersection test list is read for w0.
            intersect_filepath = self.get_intersect_filepath(
                floss_csv_filepath, self.WAVE0_SUBSTR
            )
            intersect_test_list = self.read_test_list(intersect_filepath)

        return intersect_test_list

    @classmethod
    def get_channel(cls, build_name):
        """Classify a build to a channel.

        A build looks like R112-15359.35.0 which consists of
        <milestone>-<major>.<minor>.<patch>.

        A simple rule: if the minor is not equal to 0, it is considered as a
        beta-to-be build.

        There is an obvious drawback of this rule. For early branched dev
        builds as below, they are considered as beta-to-be builds.
            ...
            R113-15390.0.0,
            R113-15393.0.0,
            R113-15393.2.0,     (dev builds considered as beta-to-be builds)
            R113-15393.4.0,     (dev builds considered as beta-to-be builds)
            R113-15393.5.0,     (dev builds considered as beta-to-be builds)
            ...
            R114-15395.0.0,
            R114-15397.0.0,

        Args:
            build_name: The build name from which to derive the channel.

        Returns:
            The channel of the build name.
        """
        _, minor, _ = build_name.split(".")
        channel = cls.DEV if minor == "0" else cls.BETA
        return channel

    def calc_osrs(
        self, filepath, denominator_test_list, intersect_test_list, test_list
    ):
        """Calculate the OSR values of the list of tests.

        A test is considered stable if its pass rate >= OSR_CRITERION.

        Assume that a test was run 20 times on various boards/models
        in a build, among which 18 of them passed, and 2 of them failed.
        pass rate = 18 / 20 = 90%

        If OSR_CRITERION is set to 90%, this test is considered stable.

        OSR stands for Overall Stability Rate.
        OSR90 (Overall Stability Rate 90) represents the proportion of
        tests with a pass rate of 90% or higher in a build.

        Args:
            filepath: the path to the CSV file.
            denominator_test_list: The list of test names as the denominator.
            intersect_test_list: the list of test names in the intersection.
            test_list: the list of test names used to calculate the OSR values.

        Returns:
            A dictionary mapping keys to OSR values, valid OSR values,
                the test pass rates, the number of total tests, and
                the percentage of unrun tests.
            A dictionary containing the summary of test results
                {
                    "osrs": osr values,
                    "valid_osrs": valid osr values,
                    "test_results": the test results,
                    "num_total_tests": the number of the total tests executed,
                }
        """
        PassFailTuple = collections.namedtuple(
            "PassFailTuple", ["pass_count", "fail_count", "pass_rate"]
        )

        def reset_test_counts_of_build(build_name):
            self.counts[build_name]["stable"] = 0
            self.counts[build_name]["unstable"] = 0
            self.counts[build_name]["unrun"] = 0

        def calc_pass_rate(pass_count, fail_count):
            total = pass_count + fail_count
            if total <= 0:
                return 0.0

            pass_rate = pass_count / total
            return pass_rate

        def print_build_header(build_name):
            if self.verbose:
                print("-" * 60)
                print("%s\n" % build_name)

        def print_unstable_tests(build_name):
            if not self.verbose:
                return

            print(
                "  Unstable tests (%d):" % self.counts[build_name]["unstable"]
            )
            for test_name in self.unstable_tests[build_name]:
                result = self.test_results[build_name][test_name]
                print(
                    "    %s %s %s %.2f"
                    % (
                        test_name,
                        result.pass_count,
                        result.fail_count,
                        result.pass_rate,
                    )
                )
            print()

        def print_unrun_tests(executed_test_list):
            if self.verbose:
                unrun_test_list = list(
                    set(intersect_test_list) - set(executed_test_list)
                )
                unrun_test_list.sort()
                print("  Unrun tests (%d):" % len(unrun_test_list))
                for test_name in unrun_test_list:
                    print("    %s" % test_name)
                print()

        def calc_osr_single_build(
            build_name, tests, intersect_test_list, number_denominator
        ):
            results = tests.values()
            self.counts[build_name]["stable"] = sum(
                [r.pass_rate >= self.OSR_CRITERION for r in results]
            )
            self.counts[build_name]["unstable"] = (
                len(tests) - self.counts[build_name]["stable"]
            )
            self.counts[build_name]["unrun"] = len(intersect_test_list) - len(
                tests
            )

            self.osrs[build_name] = (
                self.counts[build_name]["stable"] / number_denominator
            )

            if self.verbose:
                print(
                    "  OSR: %.2f = stable_tests (%d) / total_tests (%d)"
                    % (
                        self.osrs[build_name],
                        self.counts[build_name]["stable"],
                        number_denominator,
                    )
                )
                print(
                    "              intersect_tests (%d) = stabe_tests (%d) + unstabe_tests (%d) + unrun_tests (%d)"
                    % (
                        len(intersect_test_list),
                        self.counts[build_name]["stable"],
                        self.counts[build_name]["unstable"],
                        self.counts[build_name]["unrun"],
                    )
                )
                print()

        self.denominator_test_list = denominator_test_list
        self.intersect_test_list = intersect_test_list
        num_total_tests = len(set(test_list))

        self.test_results = {}
        self.osrs = {}
        self.unstable_tests = {}
        self.counts = {}
        number_denominator = len(denominator_test_list)
        with open(filepath, "r") as csvfile:
            # Check whether the file is generated by Stainless or Testhaus.
            console_type = self.get_and_verify_console_type(filepath)
            TEST_NAME, BUILD_NAME, PASS, FAIL = self.CSV_KEYS[console_type]
            reader = csv.DictReader(csvfile)

            # A csv file may contain test results of multiple builds.
            # Note: line[BUILD_NAME] denotes the build name, e.g.,
            #           R113-15379.0.0
            #       line[TEST_NAME] denotes the test name, e.g.,
            #           bluetooth_AdapterSAHealth.sa_default_state_test.floss
            for line in sorted(
                reader, key=lambda x: (x[BUILD_NAME], x[TEST_NAME])
            ):
                build_name = line[BUILD_NAME]
                if build_name not in self.test_results:
                    self.test_results[build_name] = {}
                    self.unstable_tests[build_name] = set()
                    self.counts[build_name] = {}
                    reset_test_counts_of_build(build_name)

                test_name = self.strip_tauto_prefix(line[TEST_NAME])
                if test_name in intersect_test_list:
                    pass_count = int(line["pass"])
                    fail_count = int(line["fail"])
                    # If 'test_name' already exists in test_results, it means
                    # we have two tests, with and without the tauto prefix,
                    # whose names are normalized to the same one. Here we merge
                    # the two tests' pass and fail count to update pass rate.
                    if test_name in self.test_results[build_name]:
                        existing_res = self.test_results[build_name][test_name]
                        pass_count += existing_res.pass_count
                        fail_count += existing_res.fail_count
                    pass_rate = calc_pass_rate(pass_count, fail_count)
                    self.test_results[build_name][test_name] = PassFailTuple(
                        pass_count, fail_count, pass_rate
                    )

        # Determine the set of unstable tests.
        for build_name, tests in self.test_results.items():
            for test_name, result in tests.items():
                if result.pass_rate < self.OSR_CRITERION:
                    self.unstable_tests[build_name].add(test_name)

        for build_name, tests in self.test_results.items():
            print_build_header(build_name)
            calc_osr_single_build(
                build_name, tests, intersect_test_list, number_denominator
            )
            print_unstable_tests(build_name)
            print_unrun_tests(tests.keys())

        # The test results for a build are considered valid only if the ratio of
        # executed tests to the total number of tests is higher than the
        # specified threshold self.TESTS_EXEC_PERCENT.
        valid_osrs = {self.DEV: [], self.BETA: [], self.LATEST_BETA_BUILD: ""}
        for build_name in self.test_results:
            run_percent = self.float_to_percent(
                len(self.test_results[build_name])
                / len(self.intersect_test_list)
            )
            if run_percent >= self.TESTS_EXEC_PERCENT:
                channel = self.get_channel(build_name)
                valid_osrs[channel].append(
                    float("{0:0.2f}".format(self.osrs[build_name]))
                )
                if channel == self.BETA:
                    valid_osrs[self.LATEST_BETA_BUILD] = build_name

        result = {
            "osrs": self.osrs,
            self.VALID_OSRS: valid_osrs,
            "test_results": self.test_results,
            "num_total_tests": num_total_tests,
        }
        return result

    @classmethod
    def print_osrs(
        cls,
        csv_filepath,
        category,
        floss_osrs_result,
        denominator_test_list,
        intersect_test_list,
    ):
        """Prints the OSRS results for a CSV file.

        Args:
          csv_filepath: The path to the CSV file.
          category: The category of the tests in the CSV file.
          floss_osrs_result: The OSRS results for the CSV file.
          denominator_test_list: A list of the denominator tests.
          intersect_test_list: A list of the intersect tests.
        """
        osrs = floss_osrs_result["osrs"]
        test_results = floss_osrs_result["test_results"]
        valid_osrs = floss_osrs_result[cls.VALID_OSRS]
        num_total_tests = floss_osrs_result["num_total_tests"]

        print("\n" + "=" * 60)
        print(f"{os.path.basename(csv_filepath)}")
        if category:
            print(f"  Category: {category}")
        print("    intersect_test_list %d" % len(intersect_test_list))
        print("    denominator_test_list %d" % len(denominator_test_list))
        print("    num_total_tests %d" % num_total_tests)

        # The test results for a build are considered valid only if the ratio of
        # executed tests to the total number of tests is higher than the
        # specified threshold.
        print()
        print(
            f'  {"build_name":18s} {"osr":7s} {"tests run":9s} {"%":^7s} '
            f'{"valid":5s}'
        )
        print("  " + "." * 50)
        for build_name in test_results:
            run_percent = cls.float_to_percent(
                len(test_results[build_name]) / len(intersect_test_list)
            )
            valid = run_percent >= cls.TESTS_EXEC_PERCENT
            valid_str = "v" if valid else " "
            print(
                f"  {build_name:18s} {osrs[build_name]:<7.2f} "
                f"{len(test_results[build_name]):>6d} "
                f"{run_percent:>8d} {valid_str:>5s}"
            )

        print(
            '\n  Note: valid builds are marked with "v" if at least '
            "%d%% tests have been run." % cls.TESTS_EXEC_PERCENT
        )

        print(f"\n  valid OSR values:")
        print("    %s" % str(valid_osrs))

    def calc_nsms(self, bluez_valid_osrs, floss_valid_osrs):
        """Calculates the North Star Metrics (NSMs) for floss builds.

        Args:
            bluez_valid_osrs: A dictionary of valid OSRs for BlueZ builds.
            floss_valid_osrs: A dictionary of valid OSRs for Floss builds.

        Returns:
            A dictionary of values about NSMs.
        """
        # Only one OSR value exists in bluez_valid_osrs representing
        # the golden build. There are two possibilities.
        # - R108-15183.71.0, which is in the beta channel.
        # - R117-15526.0.0, which is in the dev channel.
        if bluez_valid_osrs[self.BETA]:
            bluez_golden_osr = bluez_valid_osrs[self.BETA][0]
        elif bluez_valid_osrs[self.DEV]:
            bluez_golden_osr = bluez_valid_osrs[self.DEV][0]
        else:
            self.abort("Failed to find valid OSRs.")

        floss_valid_osrs_dev = floss_valid_osrs[self.DEV]
        floss_valid_osrs_beta = floss_valid_osrs[self.BETA]
        floss_latest_beta_build = floss_valid_osrs[self.LATEST_BETA_BUILD]

        if floss_valid_osrs_dev:
            floss_dev_average_osr = sum(floss_valid_osrs_dev) / len(
                floss_valid_osrs_dev
            )
            floss_dev_average_nsm = floss_dev_average_osr / bluez_golden_osr
        else:
            floss_dev_average_osr = None
            floss_dev_average_nsm = None

        if floss_valid_osrs_beta:
            floss_latest_beta_osr = floss_valid_osrs_beta[-1]
            floss_latest_beta_nsm = floss_latest_beta_osr / bluez_golden_osr
        else:
            floss_latest_beta_osr = None
            floss_latest_beta_nsm = None

        result = {
            self.BLUEZ_GOLDEN_OSR: bluez_golden_osr,
            self.FLOSS_DEV_AVE_OSR: floss_dev_average_osr,
            self.FLOSS_DEV_AVE_NSM: floss_dev_average_nsm,
            self.FLOSS_LATEST_BETA_OSR: floss_latest_beta_osr,
            self.FLOSS_LATEST_BETA_BUILD: floss_latest_beta_build,
            self.FLOSS_LATEST_BETA_NSM: floss_latest_beta_nsm,
        }
        return result

    def print_nsms(self, nsm_results):
        """Print the NSM values.

        Args:
            nsm_results: A dictionary of values about NSMs.
        """
        bluez_golden_osr = self.float_to_percent(
            nsm_results[self.BLUEZ_GOLDEN_OSR]
        )
        floss_dev_average_osr = self.float_to_percent(
            nsm_results[self.FLOSS_DEV_AVE_OSR]
        )
        floss_dev_average_nsm = self.float_to_percent(
            nsm_results[self.FLOSS_DEV_AVE_NSM]
        )
        floss_latest_beta_osr = self.float_to_percent(
            nsm_results[self.FLOSS_LATEST_BETA_OSR]
        )
        floss_latest_beta_nsm = self.float_to_percent(
            nsm_results[self.FLOSS_LATEST_BETA_NSM]
        )
        floss_latest_beta_build = nsm_results[self.FLOSS_LATEST_BETA_BUILD]

        print()
        print("*** NSM values ***")
        print(f"  Bluez golden build OSR value = {bluez_golden_osr:d}%")

        if floss_dev_average_osr:
            print(
                f"  Floss dev average NSM = {floss_dev_average_nsm:d}%  ",
                end="",
            )
            print(f"({floss_dev_average_osr:d}% / {bluez_golden_osr:d}%)")
        else:
            print("  Floss dev average NSM : None")

        if floss_latest_beta_osr:
            print(
                f"  Floss latest beta-to-be NSM = {floss_latest_beta_nsm:d}%  ",
                end="",
            )
            print(
                f"({floss_latest_beta_osr:d}% / {bluez_golden_osr:d}%) ", end=""
            )
            print(f"(build: {floss_latest_beta_build})")
        else:
            print("  Floss latest beta-to-be NSM : None")
        print()

    @classmethod
    def get_num_builds(cls, csv_filepath):
        """Get the number of builds contained in the file.

        Args:
            csv_filepath: The path to the CSV file.

        Returns:
            The number of builds.
        """
        with open(csv_filepath, "r") as csvfile:
            console_type = cls.get_and_verify_console_type(csv_filepath)
            TEST_NAME, BUILD_NAME, PASS, FAIL = cls.CSV_KEYS[console_type]
            reader = csv.DictReader(csvfile)

            build_list = []
            for line in sorted(
                reader, key=lambda x: (x[BUILD_NAME], x[TEST_NAME])
            ):
                build_name = line[BUILD_NAME]
                if build_name not in build_list:
                    build_list.append(build_name)
        return len(build_list)

    @classmethod
    def calc_unrun_percentage(
        cls, cat, csv_filepath, cat_test_list, num_builds
    ):
        """Calculate the percentage of unrun tests.

        Args:
            cat: The category, either CATEGORY_PLATFORM or CATEGORY_NON_PLATFORM
            csv_filepath: The path to the CSV file.
            cat_test_list: The list of test names in the category.
            num_builds: The numbere of builds.
        """
        cat_test_set = set(cat_test_list)

        with open(csv_filepath, "r") as csvfile:
            console_type = cls.get_and_verify_console_type(csv_filepath)
            TEST_NAME, BUILD_NAME, PASS, FAIL = cls.CSV_KEYS[console_type]
            reader = csv.DictReader(csvfile)

            # A csv file may contain test results of multiple builds.
            run_test_list = {}
            for line in sorted(
                reader, key=lambda x: (x[BUILD_NAME], x[TEST_NAME])
            ):
                test_name = cls.strip_tauto_prefix(line[TEST_NAME])
                if test_name not in cat_test_set:
                    # the test is not in this category
                    continue

                build_name = line[BUILD_NAME]
                if build_name not in run_test_list:
                    run_test_list[build_name] = []

                if test_name not in run_test_list[build_name]:
                    run_test_list[build_name].append(test_name)

        num_cat_test_set = len(cat_test_set)
        total_unrun_tests = 0
        for build_name, test_list in run_test_list.items():
            num_run_tests = len(test_list)
            num_unrun_tests = num_cat_test_set - num_run_tests
            total_unrun_tests += num_unrun_tests

        num_missing_builds = num_builds - len(run_test_list)
        total_unrun_tests += num_missing_builds * num_cat_test_set

        percent_unrun_tests = cls.float_to_percent(
            total_unrun_tests / (num_cat_test_set * num_builds)
        )
        print(f"Percentage of unrun tests of {cat} : {percent_unrun_tests:d}%")
        print(
            f"  (Total unrun tests: {total_unrun_tests:d}) / "
            f"((Number of expected tests per build: {num_cat_test_set:d}) * "
            f"(Number of builds: {num_builds:d}))\n"
        )

    def process_nsm_command(self):
        """Process the nsm command.

        This command calculates the NSM with the Floss OSR values and the
        Bluez OSR values.
        """
        bluez_csv_filepath = self.bluez_csv_filepath
        bluez_test_list = self.extract_test_list_from_csv(bluez_csv_filepath)

        floss_csv_filepath = self.floss_csv_filepath
        floss_test_list = self.extract_test_list_from_csv(floss_csv_filepath)

        # For now, the only bluez build is the bluez golden build.
        # All of the bluez tests are contained in denominator_test_list.
        denominator_test_list = self.extract_test_list_from_csv(
            bluez_csv_filepath
        )
        print(
            "Number of tests in the denominator: %d"
            % len(denominator_test_list)
        )

        bluez_intersect_test_list = denominator_test_list

        # Calculate the floss tests in intersection with the bluez golden build.
        floss_intersect_test_list = self.get_intersect_floss(
            floss_csv_filepath, floss_test_list, denominator_test_list
        )

        # Calculate OSR values for both stacks.
        bluez_osrs_result = self.calc_osrs(
            bluez_csv_filepath,
            denominator_test_list,
            bluez_intersect_test_list,
            bluez_test_list,
        )
        floss_osrs_result = self.calc_osrs(
            floss_csv_filepath,
            denominator_test_list,
            floss_intersect_test_list,
            floss_test_list,
        )

        # Calculate the NSM values.
        nsm_results = self.calc_nsms(
            bluez_osrs_result[self.VALID_OSRS],
            floss_osrs_result[self.VALID_OSRS],
        )

        # Print OSR and NSM values.
        self.print_osrs(
            floss_csv_filepath,
            self.CATEGORY_ALL,
            floss_osrs_result,
            denominator_test_list,
            floss_intersect_test_list,
        )
        self.print_nsms(nsm_results)

    def process_nsm2_command_with_floss_file(self):
        """Process the nsm2 command.

        The floss csv file has been generated. Calculate the NSM values based
        on the floss and the bluez csv files.

        This command separates the test list into two categories: platform and
        non-platform test lists. It then calculates the NSM values for both
        types of test lists.
        """
        bluez_csv_filepath = self.bluez_csv_filepath
        bluez_test_list = self.extract_test_list_from_csv(bluez_csv_filepath)

        floss_csv_filepath = self.floss_csv_filepath
        floss_test_list = self.extract_test_list_from_csv(floss_csv_filepath)

        # For now, the only BlueZ build is the BlueZ golden build.
        # All of the BlueZ tests are contained in denominator_test_list
        # with the exception of those listed in INVALID_TEST_LIST.
        denominator_test_list = self.exclude_tests(bluez_test_list)
        print(
            "Number of tests in the denominator: %d"
            % len(denominator_test_list)
        )

        # Calculate the floss tests in intersection with the bluez golden build.
        floss_intersect_test_list = self.get_intersect_floss(
            floss_csv_filepath, floss_test_list, denominator_test_list
        )

        bluez_test_cats = self.categorize_tests(bluez_test_list)
        floss_test_cats = self.categorize_tests(floss_test_list)
        denominator_test_cats = self.categorize_tests(denominator_test_list)
        bluez_intersect_test_cats = denominator_test_cats
        floss_intersect_test_cats = self.categorize_tests(
            floss_intersect_test_list
        )

        bluez_osrs_result = dict()
        floss_osrs_result = dict()
        nsm_results = dict()
        for cat in bluez_test_cats.keys():
            # Calculate the OSR values for both stacks.
            bluez_osrs_result[cat] = self.calc_osrs(
                bluez_csv_filepath,
                denominator_test_cats[cat],
                bluez_intersect_test_cats[cat],
                bluez_test_cats[cat],
            )
            floss_osrs_result[cat] = self.calc_osrs(
                floss_csv_filepath,
                denominator_test_cats[cat],
                floss_intersect_test_cats[cat],
                floss_test_cats[cat],
            )

            # Calculate the NSM values.
            nsm_results[cat] = self.calc_nsms(
                bluez_osrs_result[cat][self.VALID_OSRS],
                floss_osrs_result[cat][self.VALID_OSRS],
            )

        # Print OSR and NSM values.
        for cat in bluez_test_cats.keys():
            self.print_osrs(
                floss_csv_filepath,
                cat,
                floss_osrs_result[cat],
                denominator_test_cats[cat],
                floss_intersect_test_cats[cat],
            )
            self.print_nsms(nsm_results[cat])

        # Calculate the percentage of unrun tests.
        floss_num_builds = self.get_num_builds(floss_csv_filepath)
        print("\n" + "=" * 60)
        for cat in floss_test_cats.keys():
            self.calc_unrun_percentage(
                cat, floss_csv_filepath, floss_test_cats[cat], floss_num_builds
            )

        return bluez_osrs_result, floss_osrs_result, nsm_results

    def retrieve_test_results_for_nsm2(self):
        """Retrieve the test results for the nsm2 command argument.

        This method uses a Big Query script to obtain the test results
        corresponding to the 'nsm2' command argument.
        """
        from bq_cros_test import FlossTestResultRetriever

        bq_obj = FlossTestResultRetriever(self.start, self.end)
        self.floss_csv_filepath = bq_obj.query(self.wave)
        print(f"Big Query test results are saved in {self.floss_csv_filepath}")

    def process_nsm2_command(self):
        """Process the nsm2 command.

        There are two scenarios to compute the NSM values.

        1. Download the test results from the biq query table, save the data
           in a csv file, and then calculate the NSM values accordingly.

        2. The floss csv data file has been generated, possibly through
           the BigQuery Studio:
           https://pantheon.corp.google.com/bigquery?project=cros-test-analytics&ws=!1m0
           Calculate the NSM values from the floss csv file.
        """
        if self.wave and self.start and self.end:
            self.retrieve_test_results_for_nsm2()
            return self.process_nsm2_command_with_floss_file()
        elif self.floss_csv_filepath:
            return self.process_nsm2_command_with_floss_file()
        else:
            self.abort(
                "You should either specify the floss csv filepath or "
                "the wave, the start date, and the end date."
            )


def parse_args():
    """Parse the arguments."""
    parser = argparse.ArgumentParser()

    # Create subparsers for different commands
    subparsers = parser.add_subparsers(dest="command")

    # Create a subparser for the nsm command and its options
    # An example command to calculate the OSR values:
    # $ python3 nsm.py nsm -f /tmp/data/Floss_OSR_2023_0312_to_2023_0318_w1.csv
    #                      -b /tmp/data/Bluez_osr_R108-15183.71.0.csv
    #
    # Add "-v" to show unstable tests and unrun tests of each build.
    nsm_parser = subparsers.add_parser("nsm")
    nsm_parser.add_argument(
        "-b",
        "--bluez",
        type=str,
        help="the bluez csv filepath to calculate testing NSM",
    )
    nsm_parser.add_argument(
        "-f",
        "--floss",
        type=str,
        help="the floss csv filepath to calculate testing NSM",
    )
    nsm_parser.add_argument(
        "-v", "--verbose", action="store_true", help="enable verbose mode"
    )

    # Create a subparser for the nsm2 command and its options
    # An example command to calculate the OSR values:
    # $ python3 nsm.py nsm2 -f /tmp/data/Floss_OSR_2023_0312_to_2023_0318_w1.csv
    #                       -b /tmp/data/Bluez_osr_R108-15183.71.0.csv
    #
    # Add "-v" to show unstable tests and unrun tests of each build.
    nsm_parser = subparsers.add_parser("nsm2")
    nsm_parser.add_argument(
        "-b",
        "--bluez",
        type=str,
        default="data/Bluez_osr_R117-15526.0.0.csv",
        help="the bluez csv filepath to calculate testing NSM",
    )
    nsm_parser.add_argument(
        "-f",
        "--floss",
        type=str,
        help="the floss csv filepath to calculate testing NSM",
    )
    nsm_parser.add_argument(
        "-w",
        "--wave",
        type=str,
        help="the wave of devices",
    )
    nsm_parser.add_argument(
        "-s",
        "--start",
        type=str,
        help="the start date of the test data to query, e.g., 2023-09-20",
    )
    nsm_parser.add_argument(
        "-e",
        "--end",
        type=str,
        help="the end date of the test data to query, e.g., 2023-09-26",
    )
    nsm_parser.add_argument(
        "-v", "--verbose", action="store_true", help="enable verbose mode"
    )

    return parser.parse_args()


def main():
    """The main function to execute the commands supported by this module."""
    args = parse_args()
    nsm = NSM(
        args.bluez, args.floss, args.wave, args.start, args.end, args.verbose
    )
    if args.command == "nsm":
        nsm.process_nsm_command()
    elif args.command == "nsm2":
        nsm.process_nsm2_command()


if __name__ == "__main__":
    main()
