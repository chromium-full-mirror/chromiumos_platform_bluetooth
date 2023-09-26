#!/usr/bin/env python3
# Lint as: python3
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""A module to download cros test data from BigQuery."""

import os
import sys


class FlossTestResultRetriever(object):
    """To retrieve Floss test results of specified date range and wave.

    This class provides a script method to execute queries on Big Query.

    Attributes:
        start_date: start date (format yyyy-mm-dd) of test results being
                retrieved.
        end_date: end date (format yyyy-mm-dd) of test results being
                retrieved.Format yyyy-mm-dd.
        output_dir: output directory of test result CSV file.
                Default "/tmp".
        file_template: output file template. Derived in __init__.
    """

    PROJECT_ID = "cros-test-analytics"
    DATASET_ID = "resultdb"
    RESULT_TABLE = "cros_test_results"

    WAVE1_CHIPS = (
        "INTEL_GFP2_AX211|"
        "INTEL_CCP2_AX200|"
        "INTEL_HRP2_AX201|"
        "INTEL_JFP2_AC9560|"
        "INTEL_THP2_AC9260"
    )
    TEST_PREFIXES = "^(tast|bluetooth|tauto)"
    POOLS = "nearby-share-remote-floss|cross-device-floss|^(bluetooth_floss)"

    # Use `go/floss-tw1o` to derive the corresponding SQL command template.
    # Some modifications are needed:
    # - Use double quotes in the SQL commands as we will need to use single
    #   quotes to enclose the SQL commands in the `bq` command.
    # - Regarding rowHeaderArray and columnHeaderArray, its original syntax
    #       ANY_VALUE([IFNULL(test, '-')]) AS rowHeaderArray,
    #   is replaced with
    #       CONCAT(IFNULL(test, "-")) AS rowHeaderArray,
    #   as `bq` has some difficulties in converting the original results into
    #   csv format.
    # - Replace "git_%" with "git_%%".
    SQL_COMMAND_WAVE = """
            SELECT \
                CONCAT(IFNULL(test, "-")) AS rowHeader, \
                CONCAT(IFNULL(test, "-")) AS rowHeaderArray, \
                CONCAT(IFNULL(build, "-")) AS columnHeader, \
                CONCAT(IFNULL(build, "-")) AS columnHeaderArray, \
                SUM(IF(status IN ("PASS"), 1, 0)) AS pass, \
                SUM(IF(status IN ("WARN"), 1, 0)) AS warn, \
                SUM(IF(status IN ("FAIL", "CRASH", "ABORT"), 1, 0)) AS fail, \
                SUM(IF(status IN ("NOSTATUS"), 1, 0)) AS nostatus, \
                SUM(IF(status IN ("TEST_NA"), 1, 0)) AS testNa, \
                SUM(IF(status IN ("NOT_RUN"), 1, 0)) AS notRun, \
                SUM(IF(status NOT IN ( \
                    "PASS", \
                    "WARN", \
                    "FAIL", \
                    "CRASH", \
                    "ABORT", \
                    "NOSTATUS", \
                    "TEST_NA", \
                    "NOT_RUN"), 1, 0)) AS other \
            FROM cros-test-analytics.resultdb.cros_test_results \
            WHERE ( \
                    queued_time BETWEEN "%s 00:00:00 UTC" \
                    AND "%s 00:00:00 UTC" \
                ) \
                AND ( \
                    status IN UNNEST(["PASS", "FAIL"]) \
                    AND REGEXP_CONTAINS(IFNULL(suite, ""), "%s") \
                    AND REGEXP_CONTAINS(IFNULL(test, ""), "%s") \
                    AND REGEXP_CONTAINS(IFNULL(wifi_chip, ""), "%s") \
                    %s \
                ) \
                AND ( \
                    job_name NOT LIKE "git_%%" \
                    AND ( \
                        suite IS NULL OR NOT \
                        REGEXP_CONTAINS(IFNULL(suite, ""), r"^(au$|paygen_au)")\
                    ) \
                    AND (NOT retried) \
                    AND ( \
                        REGEXP_CONTAINS(IFNULL(build, ""), \
                        r"^R\d+-\d+\.\d+\.\d+$") \
                        OR REGEXP_CONTAINS(IFNULL(image, ""), r"-release-") \
                    ) \
                ) \
            GROUP BY rowHeader, columnHeader
    """

    BOARD_MATCH_BRYA = 'AND REGEXP_CONTAINS(IFNULL(board, ""), "brya")'
    BOARD_MATCH_NOT_SPECIFIED = ""

    # The default max rows in bq is 100. We need to increase the value to
    # download the complete test results.
    # As of 2023 Q3, the floss test results consist of about 2088 rows.
    # Since the platform tests may have a prefix `tauto` or may not, the
    # number of rows may be doubled. To accommodate future growth, let's
    # set the max rows to 10,000.
    BQ_MAX_ROWS = 10000

    # The SQL command has to be enclosed by single quotes instead of
    # double quotes. Save the results into a csv file.
    # It typically takes less than 10 seconds to complete.
    BQ_CMD = (
        f"bq --project_id={PROJECT_ID} --dataset_id={DATASET_ID} "
        "--format=csv query --use_legacy_sql=false "
        f"--max_rows={BQ_MAX_ROWS} '%s' > %s"
    )

    def __init__(self, start_date, end_date, output_dir="/tmp"):
        self.start_date = start_date
        self.end_date = end_date
        self.output_dir = output_dir
        self.file_template = self._create_file_template()

    def _create_file_template(self):
        """Creates a file template with the date range of the test results.

        Example: given start_date '2023-09-20' and end_date '2023-09-26',
                 the created file template is
                 'Floss_OSR_2023_0920_to_2023_0926_w%s.csv'.
        """

        def convert_date(date_str):
            year, month, day = date_str.split("-")
            return f"{year}_{month}{day}"

        conv_start_date = convert_date(self.start_date)
        conv_end_date = convert_date(self.end_date)
        return f"Floss_OSR_{conv_start_date}_to_{conv_end_date}_w%s.csv"

    def _create_sql_cmd(self, wave):
        # Query the test results for wave 0 and wave 1 devices.
        if wave == "0":
            board = self.BOARD_MATCH_BRYA
        elif wave == "1":
            board = self.BOARD_MATCH_NOT_SPECIFIED
        else:
            print("Error: the wave {wave} devices are not supported.")
            sys.exit(-1)

        return self.SQL_COMMAND_WAVE % (
            self.start_date,
            self.end_date,
            self.POOLS,
            self.TEST_PREFIXES,
            self.WAVE1_CHIPS,
            board,
        )

    def query(self, wave):
        """Queries the Floss test results and stores in a CSV file.

        Args:
            wave: only retrieve test results from Floss wave in DUTs.
                    Valid values: "0", "1".

        Returns:
            The path to the CSV file that stores the test results.
        """
        csv_filename = self.file_template % wave
        csv_filepath = os.path.join(self.output_dir, csv_filename)
        bq_cmd = self.BQ_CMD % (self._create_sql_cmd(wave), csv_filepath)
        ret = os.system(bq_cmd)
        if ret == 0:
            return csv_filepath

        print("Error in executing bq: {bq_cmd}")
        sys.exit(-1)


if __name__ == "__main__":
    # It is required to query the results for wave 1 before wave 0.
    # Please check out the `How to run the nsm script` section in README.md
    # about the reason.
    test_result_retriever = FlossTestResultRetriever("2023-09-20", "2023-09-27")
    for wave in ("1", "0"):
        csv_filepath = test_result_retriever.query(wave)
        print(f"the wave-{wave} test results are saved in {csv_filepath}")
