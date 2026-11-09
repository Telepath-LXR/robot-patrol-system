#!/bin/bash
for cpu in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
    echo performance > "$cpu"
done
echo "CPU frequency locked to performance."
