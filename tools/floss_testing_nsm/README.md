# Floss Testing NSM

[TOC]

## North Star Metrics (NSM) Calculator for Floss Automated Tests

In brief, the Floss Testing NSM is an indicator about how good the Floss tests are
compared to the tests in a specified Bluez Golden build.

To calculate the NSM, we have to calculate the OSR (Overall Stability Rate)
values for both Bluez and Floss first.

First, manually pick up a Golden Bluez build in which Bluez tests have passed
well. A test is regarded as stable if its pass rate is larger than or equal to
90%. The `num_tests_in_bluez_denominator` is the number of tests in the Bluez
golden build and is a fixed value once a Bluez golden build is chosen. The
definition of OSR is as follows.

```
  OSR = num_stable_tests / num_tests_in_bluez_denominator
```

Hence, we can calculate the OSR values for Floss and Bluez respectively.

```
  Bluez_Golden_OSR = num_stable_tests_in_bluez_golden_build / num_tests_in_bluez_denominator
  Floss_OSR = num_stable_tests_in_a_floss_build / num_tests_in_bluez_denominator
```

Note that the OSR indicates that any unrun Floss tests in the lab are regarded
as failed ones.

To calulate the Floss NSM values, the formula is

```
  Floss_NSM = Floss_OSR / Bluez_Golden_OSR
```

The ChromeOS Bluetooth team keeps track of the Floss NSM values
in a weekly basis. Hence, there will be a number of Floss NSM values generated
in a week for both dev and beta channels. For the dev channel, an average value
is calculated over the Floss OSR values of the dev channel. For the beta
channel, the latest Floss OSR value of the beta channel is used.

Refer to the [details](https://docs.google.com/document/d/18uU1NkM8dAyjA1HHz6LwZLSTLkVR2i2FWD6n3n5vsVk/edit?resourcekey=0-vu6R7Xt-1as1s0Mgp1WnxQ)
about the rationale of the formula.


## Prerequisites (Googlers only)

The `bq_cros_test.py` script uses BigQuery CLI command, `bq`, to extract
test results from BigQuery tables. To make it work, Googlers need to install
the necessary packages and create a credentials file. Follow the
[instructions](https://cloud.google.com/docs/authentication/provide-credentials-adc)
to set up your environment properly.

### Step 1 Install the [gcloud CLI](https://cloud.google.com/sdk/docs/install)

Click on `Google-internal instructions`.
Install and use the [Google Cloud CLI](https://g3doc.corp.google.com/cloud/sdk/g3doc/index.md?cl=head).

Within Google, the only security-approved way to install the public
release on gLinux is via Rapture:

```
  $ sudo apt install -y google-cloud-cli
```

### Step 2 Create your [credential file](https://cloud.google.com/docs/authentication/provide-credentials-adc)

```
  $ gcloud auth application-default login
```

A login screen is displayed. After you log in, your credentials are stored
in the local credential file used by ADC.

The file could be something like
```
  ~/.config/gcloud/application_default_credentials.json
```


## How to run the nsm script

Note: Always run the nsm script for wave 1 devices before those in other waves.
      The reason is that wave 1 has a higher number of tests compared to wave 0
      and wave 2. Data from wave 1 test results are used to identify the
      intersecting tests between the floss tests and the bluez tests. These
      intersecting tests are then used in other waves to identify unexecuted
      tests.

### Step 1 Perform the big queries

Download the cros test results from Big Query, save the results
in a CSV file, and then calculate the NSM values using the CSV file.

```
        $ ./nsm.py nsm2 -w 1 -s 2023-09-10 -e 2023-09-16
        $ ./nsm.py nsm2 -w 0 -s 2023-09-10 -e 2023-09-16
```

The operation will typically take less than 10 seconds to download the results,
and save them as CSV files as below

```
        /tmp/Floss_OSR_2023_0910_to_2023_0916_w1.csv
        /tmp/Floss_OSR_2023_0910_to_2023_0916_w0.csv
```

The NSM calculation takes well less than 1 second.

Note: The `nsm2` command argument represents the second variant used to
      compute the NSM values across two categories: platform and
      non-platform tests. We differentiate these categories because
      non-platform tests tend to be less stable than platform tests.
      As such, it's beneficial to calculate metrics for them independently.
      In the future, to compute metrics for both categories collectively,
      use the `nsm` command argument instead.

### Step 2 Calculate the NSM valuews

You already have a CSV file with the downloaded test results. Simply
Calculate the NSM values using the CSV file.

```
        $ ./nsm.py nsm2 -f /tmp/Floss_OSR_2023_0910_to_2023_0916_w1.csv
        $ ./nsm.py nsm2 -f /tmp/Floss_OSR_2023_0910_to_2023_0916_w0.csv
```
