#!/bin/bash
# Apply arcade performance mode: nvpmodel mode 5 (Perf All, no overclock) + CPU governor to performance.
# Place in /home/arcade/scripts/arcade-perf-mode.sh and chmod +x.
#
# NOTE: mode 6 (Perf_OC_All) was causing hard system freezes (GPU driver hang),
# even with no game running. mode 5 (Perf_All) keeps the performance clock floors
# but drops the CPU/GPU overclock, which is what destabilized the Tegra X1.

set -e

# Perf All profile (CPU/GPU floors high, avoids stutter, no overclock)
sudo nvpmodel -m 5

# Pin CPU governor to performance so it doesn't downscale between frames
for cpu in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
  echo performance | sudo tee "$cpu" >/dev/null
done

echo "Arcade performance mode applied."
