#!/bin/bash
# Apply arcade performance mode: nvpmodel mode 5 (Perf All, no overclock) + CPU governor to performance.
# Installed at /home/tagap/scripts/arcade-perf-mode.sh and run at boot by
# config/systemd/system/arcade-perf-mode.service (as root, no sudo prompt).
#
# NOTE: mode 6 (Perf_OC_All) was causing hard system freezes (GPU driver hang),
# even with no game running. mode 5 (Perf_All) keeps the performance clock floors
# but drops the CPU/GPU overclock, which is what destabilized the Tegra X1.

set -e

# Perf All profile (CPU/GPU floors high, avoids stutter, no overclock).
# The systemd system service runs this as root; a manual run still uses sudo.
if [ "$(id -u)" -eq 0 ]; then
  nvpmodel -m 5
else
  sudo nvpmodel -m 5
fi

# Pin CPU governor to performance so it doesn't downscale between frames
for cpu in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
  if [ "$(id -u)" -eq 0 ]; then
    echo performance > "$cpu"
  else
    echo performance | sudo tee "$cpu" >/dev/null
  fi
done

echo "Arcade performance mode applied."
