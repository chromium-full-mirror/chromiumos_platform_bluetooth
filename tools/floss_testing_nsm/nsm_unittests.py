#!/usr/bin/env python3
# Lint as: python3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""The unit tests for nsm.py.

Usage:
    python3 nsm_unittests.py -v > /dev/null
"""

import unittest

import nsm


class TestNSM2(unittest.TestCase):
    """A unittest class for the nsm2 command in nsm.py

    The simple fake csv data are made up manually for verification.
    """

    Bluez_SIMPLE_CSV = "data/Bluez_test_dataset0.csv"
    Floss_SIMPLE_W1_CSV = "data/Floss_test_dataset0_w1.csv"

    def __init__(self, methodName="runTest"):
        super().__init__(methodName=methodName)
        self.nsm = nsm.NSM(self.Bluez_SIMPLE_CSV, self.Floss_SIMPLE_W1_CSV)
        (
            bluez_osrs_result,
            floss_osrs_result,
            nsm_results,
        ) = self.nsm.process_nsm2_command()

        # Platform (pf) tests data
        pf_bluez_osrs = bluez_osrs_result[self.nsm.CATEGORY_PLATFORM]
        pf_floss_osrs = floss_osrs_result[self.nsm.CATEGORY_PLATFORM]
        self.pf_floss_nsm = nsm_results[self.nsm.CATEGORY_PLATFORM]
        self.pf_bluez_valid_osrs = pf_bluez_osrs[self.nsm.VALID_OSRS]
        self.pf_floss_valid_osrs = pf_floss_osrs[self.nsm.VALID_OSRS]

        # Non-Platform (npf) tests data
        npf_bluez_osrs = bluez_osrs_result[self.nsm.CATEGORY_NON_PLATFORM]
        npf_floss_osrs = floss_osrs_result[self.nsm.CATEGORY_NON_PLATFORM]
        self.npf_floss_nsm = nsm_results[self.nsm.CATEGORY_NON_PLATFORM]
        self.npf_bluez_valid_osrs = npf_bluez_osrs[self.nsm.VALID_OSRS]
        self.npf_floss_valid_osrs = npf_floss_osrs[self.nsm.VALID_OSRS]

    def test_platform_bluez_latest_build(self):
        build_name = self.pf_bluez_valid_osrs[self.nsm.LATEST_BETA_BUILD]
        self.assertEqual(build_name, "R113-15393.16.0")

    def test_platform_nsm_bluez_golden_osr(self):
        bluez_golden_osr = self.pf_floss_nsm[self.nsm.BLUEZ_GOLDEN_OSR]
        self.assertAlmostEqual(bluez_golden_osr, 0.85, places=2)

    def test_platform_floss_valid_osrs_dev(self):
        self.assertEqual(self.pf_floss_valid_osrs[self.nsm.DEV], [0.8])

    def test_platform_floss_valid_osrs_beta(self):
        self.assertEqual(self.pf_floss_valid_osrs[self.nsm.BETA], [0.7])

    def test_platform_floss_dev_average_nsm(self):
        floss_dev_ave_nsm = self.pf_floss_nsm[self.nsm.FLOSS_DEV_AVE_NSM]
        self.assertAlmostEqual(floss_dev_ave_nsm, 0.94, places=2)

    def test_platform_floss_latest_beta_nsm(self):
        floss_latest_beta_nsm = self.pf_floss_nsm[
            self.nsm.FLOSS_LATEST_BETA_NSM
        ]
        self.assertAlmostEqual(floss_latest_beta_nsm, 0.82, places=2)

    def test_platform_floss_latest_beta_build(self):
        build_name = self.pf_floss_nsm[self.nsm.FLOSS_LATEST_BETA_BUILD]
        self.assertEqual(build_name, "R113-15393.15.0")

    def test_non_platform_bluez_latest_build(self):
        build_name = self.npf_bluez_valid_osrs[self.nsm.LATEST_BETA_BUILD]
        self.assertEqual(build_name, "R113-15393.16.0")

    def test_non_platform_floss_valid_osrs_dev(self):
        self.assertEqual(self.npf_floss_valid_osrs[self.nsm.DEV], [0.47])

    def test_non_platform_floss_valid_osrs_beta(self):
        self.assertEqual(self.npf_floss_valid_osrs[self.nsm.BETA], [0.4])

    def test_non_platform_nsm_bluez_golden_osr(self):
        bluez_golden_osr = self.npf_floss_nsm[self.nsm.BLUEZ_GOLDEN_OSR]
        self.assertAlmostEqual(bluez_golden_osr, 0.87, places=2)

    def test_non_platform_floss_dev_average_nsm(self):
        floss_dev_ave_nsm = self.npf_floss_nsm[self.nsm.FLOSS_DEV_AVE_NSM]
        self.assertAlmostEqual(floss_dev_ave_nsm, 0.54, places=2)

    def test_non_platform_floss_latest_beta_nsm(self):
        floss_latest_beta_nsm = self.npf_floss_nsm[
            self.nsm.FLOSS_LATEST_BETA_NSM
        ]
        self.assertAlmostEqual(floss_latest_beta_nsm, 0.46, places=2)

    def test_non_platform_floss_latest_beta_build(self):
        build_name = self.npf_floss_nsm[self.nsm.FLOSS_LATEST_BETA_BUILD]
        self.assertEqual(build_name, "R113-15393.15.0")


if __name__ == "__main__":
    unittest.main()
