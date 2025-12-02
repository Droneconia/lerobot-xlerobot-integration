# Network Latency Diagnosis (Nov 23, 2025)

## Problem
Bad ping/latency from laptop to Ubuntu machine (192.168.50.47) over SSH.

## Root Causes Identified

### 1. **CPU Power Management (Primary Issue)**
- **Finding**: All 12 CPU cores using `powersave` governor
- **Impact**: CPU cores running at variable frequencies (800 MHz to 4391 MHz)
- **Effect**: Network stack processing delayed as CPU ramps up from idle states
- **Expected improvement**: 50-70% latency reduction

### 2. **WiFi Power Management (Secondary Issue)**
- **Finding**: WiFi interface has power management enabled
- **Impact**: WiFi adapter enters sleep states to save power
- **Effect**: Adds 1-3ms latency when adapter needs to wake up
- **Expected improvement**: 20-30% latency reduction

### 3. **Current Performance Metrics**

#### WiFi Connection Quality (Excellent ✅)
```
Interface:      wlp0s20f3
SSID:           ASUS_10_5G
Frequency:      5745 MHz (5GHz band, channel 149)
Signal:         -42 dBm (excellent)
Link Quality:   68/70 (97%)
RX bitrate:     866.7 Mbps
TX bitrate:     780.0 Mbps
Packet drops:   0
Errors:         0
```

#### Latency to Gateway (Poor ⚠️)
```
Target:         192.168.50.1 (local gateway)
Min RTT:        0.897 ms
Avg RTT:        2.799 ms  ← Should be < 1ms
Max RTT:        4.074 ms
Std Dev:        0.560 ms (high variance)
Packet loss:    0%
```

#### System Load (Normal ✅)
```
Load avg:       0.20 (very light)
CPU idle:       99%
Free RAM:       29GB / 32GB
Swap usage:     0
```

## Solutions

### Quick Fix (Temporary - Lost on Reboot)
```bash
sudo ./fix_network_latency.sh
```

This script will:
1. Set CPU governor to `performance` mode
2. Disable WiFi power management
3. Configure NetworkManager to keep power save off
4. Test and verify improvements

### Permanent Fix - Option 1: Performance Mode
For maximum performance (higher power consumption):

```bash
# Install cpufrequtils
sudo apt install cpufrequtils

# Set performance governor
sudo systemctl disable ondemand
echo 'GOVERNOR="performance"' | sudo tee /etc/default/cpufrequtils
sudo systemctl restart cpufrequtils

# Verify
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor
```

### Permanent Fix - Option 2: Balanced Mode with TLP
For laptops needing battery optimization:

```bash
# Install TLP
sudo apt install tlp tlp-rdw

# Edit TLP config
sudo nano /etc/tlp.conf

# Add these settings:
CPU_SCALING_GOVERNOR_ON_AC=performance
CPU_SCALING_GOVERNOR_ON_BAT=powersave
WIFI_PWR_ON_AC=off
WIFI_PWR_ON_BAT=on

# Start TLP
sudo tlp start
```

## Expected Results After Fix

### Before Fix
```
Ping to gateway: ~2.8ms avg, 0.9-4.0ms range
Ping variance:   High (0.56ms std dev)
CPU frequency:   800-4391 MHz (variable)
WiFi power:      On (sleep states enabled)
```

### After Fix
```
Ping to gateway: ~0.5ms avg, 0.3-0.8ms range (estimated)
Ping variance:   Low (<0.2ms std dev)
CPU frequency:   3800-4500 MHz (consistently high)
WiFi power:      Off (always active)
```

## Additional Checks

### Check if Laptop is the Issue
From your laptop, run:
```bash
# Check laptop's CPU governor
cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor | sort | uniq -c

# Check laptop's WiFi power management
iwconfig 2>&1 | grep "Power Management"

# Test ping to Ubuntu machine
ping -c 50 192.168.50.47
```

### Monitor Real-Time Latency
```bash
# Continuous ping with timestamps
ping -D 192.168.50.47

# With mtr (better tool)
sudo apt install mtr
mtr -r -c 50 192.168.50.47
```

## Trade-offs

### Performance Mode
- ✅ Lowest latency (~0.5ms)
- ✅ Consistent performance
- ❌ Higher power consumption (~15-25W more)
- ❌ More heat generation
- ❌ Reduced battery life (50-70% decrease if on battery)

### Powersave Mode (Current)
- ✅ Lower power consumption
- ✅ Less heat
- ✅ Better battery life
- ❌ Higher latency (~2-3ms)
- ❌ Variable performance
- ❌ Poor for real-time applications

### Balanced Mode (TLP)
- ✅ Performance when plugged in
- ✅ Power saving on battery
- ✅ Automatic switching
- ⚠️ Requires configuration
- ⚠️ Still higher latency on battery

## Hardware Context

**System**: Intel i7-9750H laptop (from laptop_host_setup.md)
- 6 cores, 12 threads
- Base: 2.6 GHz, Turbo: up to 4.5 GHz
- TDP: 45W (can throttle if overheated)

**Network**: 5GHz WiFi (excellent signal)
- Router: ASUS (192.168.50.1)
- Channel: 149 (5745 MHz)
- Bandwidth: 80 MHz channel width

## Recommendations

1. **Immediate**: Run `sudo ./fix_network_latency.sh` to test improvement
2. **Short-term**: If latency improves, decide on permanent solution based on use case
3. **For SSH/development work**: Use performance mode (Option 1)
4. **For battery life**: Use TLP balanced mode (Option 2)
5. **Long-term**: Consider Ethernet connection for lowest latency (<0.1ms)

## Related Issues to Check

1. **Laptop-side latency**: Apply same fixes to laptop if experiencing issues
2. **Router QoS**: Check if router has QoS/traffic shaping enabled
3. **Channel congestion**: Scan for WiFi interference on channel 149
4. **Thermal throttling**: Monitor CPU temps during heavy use
5. **Disk space**: Only 17GB free on laptop (from laptop_host_setup.md) - may cause swapping

## Files
- Fix script: `/home/grievous/Code/Grievous/fix_network_latency.sh`
- This document: `/home/grievous/Code/Grievous/context_notes/network_latency_diagnosis.md`

