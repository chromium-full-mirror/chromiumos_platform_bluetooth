# SWB on Pipewire

This directory contains a customized patch to enable SWB on Pipewire.

### How to apply the patch

On top of commit 8e6d070148fc018df78a30ec410ed35340b9f53b, apply
`0001-SWB-Patch.patch`. After building Pipewire, modify
`/home/pi/.config/wireplumber/bluetooth.lua.d/50-bluez-config.lua` so that
`bluez5.roles` contains only `hfp_hf` (to support the handsfree role).
Either reboot or run `systemctl --user daemon-reload` after change.

This was tested on Bluez v5.55, Raspbian GNU/Linux 11 (bullseye).

### How to run related autotests

* `test_that --autotest_dir ~/trunk/src/third_party/autotest/files/ \
--args "btpeer_host=$PI update_btpeers=false rssi_check=false" $DUT \
bluetooth_AdapterAUHealth.au_hfp_swb_dut_as_source_test.floss`

* `test_that --autotest_dir ~/trunk/src/third_party/autotest/files/ \
--args "btpeer_host=$PI update_btpeers=false rssi_check=false" $DUT \
bluetooth_AdapterAUHealth.au_hfp_swb_dut_as_sink_test.floss`
