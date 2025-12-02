# Control Loop Analysis for Grievous Host

**Date:** November 23, 2025  
**Status:** Analysis Phase

## Current Implementation Analysis

### Main Loop Structure (grievous_host.py lines 137-266)

The main loop in `grievous_host.py` runs at a target of 60 Hz (16.67ms per iteration) and performs the following operations sequentially:

**Step 1: Watchdog Check** (~0.1ms)
- Lines 165-174: Check if commands haven't been received for >500ms
- Calls `robot.xlerobot.stop_base()` if timeout
- Currently disabled (commented out command reception)

**Step 2: Get Observation** (~15-30ms) - BOTTLENECK #1
- Line 178: `robot.get_observation()` 
- Calls `xlerobot.get_observation()` → reads motors + cameras
- Motors: `bus1.sync_read()` + `bus2.sync_read()` for positions (~3-5ms)
- Cameras: 3× `cam.async_read()` for left_wrist, right_wrist, head (~10-25ms total)
- Returns dict with motor states + raw camera numpy arrays

**Step 3: Get Action** (~2-5ms)
- Line 182: `robot.get_action()`
- Reads leader arm positions via `BiSO100Leader.get_action()` over USB serial
- Adds fixed head positions and zero base velocities (from our recent fix)
- Returns complete 17 DoF action dict

**Step 4: Action Processing** (~0.5ms)
- Lines 187-192: Run through processor pipelines
- `teleop_action_processor`: typically identity processor
- `robot_action_processor`: typically identity processor
- Minimal overhead unless processors are configured

**Step 5: Send Action** (~2ms)
- Line 195: `robot.send_action(robot_action)`
- Writes commands to follower arms via USB serial
- `bus1.write()` + `bus2.write()` for motor positions

**Step 6: Encode Camera Images** (~10-20ms) - BOTTLENECK #2
- Lines 199-225: Loop through 3 cameras
- For each camera: `cv2.imencode()` with JPEG quality 90
- Convert to base64 string for JSON transmission
- Left/right wrist (640×480): ~3-7ms each
- Head camera (640×480 now): ~3-7ms
- Total: ~10-20ms for 3 cameras

**Step 7: Send Observation via ZMQ** (~1-2ms)
- Lines 228-248: Send action and observation over network
- Two separate ZMQ sends (action feedback + observation)
- Non-blocking (NOBLOCK flag) so failures are quick
- JSON encoding adds ~0.5ms overhead

**Step 8: Rate Limiting** (~0-5ms)
- Lines 251-255: Sleep to maintain 60 Hz target
- Calculates elapsed time and sleeps remainder
- If loop took >16.67ms, no sleep (running behind)

### Current Performance Breakdown

**Target:** 16.67ms per loop (60 Hz)

**Actual Timing:**
```
Watchdog:            0.1ms     ✓ Fast
Get observation:    20-35ms    ✗ BOTTLENECK (motors + cameras)
Get action:          2-5ms     ✓ Fast
Process action:      0.5ms     ✓ Fast
Send action:         2ms       ✓ Fast
Encode cameras:     10-20ms    ✗ BOTTLENECK (JPEG encoding)
Send ZMQ:            1-2ms     ✓ Fast
Sleep:               0ms       ✗ No time left
──────────────────────────────
Total:              35-65ms    → Only 15-25 Hz actual
```

## Identified Bottlenecks

**Bottleneck #1: Camera Capture in get_observation() (~10-25ms)**
- `xlerobot.get_observation()` reads both motors AND cameras
- Even though cameras use `async_read()` (background threads), the call still takes time
- We read 3 cameras sequentially, each taking ~3-8ms
- No way to skip cameras - method always captures them

**Bottleneck #2: JPEG Encoding in Main Loop (~10-20ms)**
- Encoding happens synchronously in main thread
- Blocks motor control during encoding
- CPU-intensive operation that could run in parallel

**Bottleneck #3: Unnecessary Observation Frequency**
- Recording only needs 30 Hz observations
- But we're trying to get observations at 60 Hz
- Wasting 2× the camera bandwidth and encoding time

## Next Steps for Optimization Discussion

Before proposing solutions, key questions:

1. **Do we need motor states at 200 Hz, or just the control loop?**
   - Control loop (leader read → follower write) should be 200 Hz
   - But do we need to READ follower motor states at 200 Hz?
   - Or can follower state observation be at 30 Hz like cameras?

2. **What's the minimum change to achieve fast control?**
   - Option A: Add `get_observation(include_cameras=False)` parameter
   - Option B: Add separate `get_motor_states()` method
   - Option C: Skip observations entirely in control loop

3. **Where should camera encoding happen?**
   - Keep in main loop but decimate to 30 Hz?
   - Move to separate thread?
   - Both?

Let me know your thoughts on these questions and we can design the minimal-change solution.

