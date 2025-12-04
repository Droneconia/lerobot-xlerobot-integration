# Remote Policy Implementation Plan

## Goal
Enable remote policy inference on Grievous robot where the policy runs on a GPU server (e.g., RunPod) while the robot hardware runs on a local host (RPi5/Laptop). The implementation follows the proven `xlerobot` pattern: simple bidirectional communication with watchdog safety. **Recording mode remains completely untouched** by creating a separate inference host script.

## Test Organization

All test scripts have been moved to `tests/grievous_inference/` directory for better organization.

## Implementation Checklist

### Phase 1: Verification & Understanding
- [x] Read and verify `src/lerobot/robots/grievous/grievous.py` to understand how `Grievous` instantiates both follower and leader arms
  - **Finding:** `Grievous.__init__` always creates both `XLerobot` (line 72) and `BiSO100Leader` (line 83). Cannot avoid instantiation, but we can simply not call `get_action()` or read leader state.
- [x] Verify that we can instantiate `Grievous` and simply not read/use leader arms (for future overwrite feature)
  - **Confirmed:** We can instantiate `Grievous`, connect it, and only use `send_action()` and `get_observation()`. Leader arms will be connected but unused.
- [x] Verify the current ZMQ socket configuration in both `grievous_host.py` and `grievous_client.py` matches what we documented (PUSH/PUSH mismatch for commands)
  - **Confirmed:** `grievous_host.py` line 71 uses `zmq.PUSH`, `grievous_client.py` line 198 uses `zmq.PUSH` - mismatch confirmed.
- [x] Review `src/lerobot/robots/xlerobot/xlerobot_host.py` to understand the reference implementation pattern (lines 29-127) - use as template for control loop structure
  - **Pattern identified:** Control loop at lines 69-113: receive action (non-blocking), execute, check watchdog, get observation, encode images, send observation, rate limit.
- [x] Check `src/lerobot/robots/grievous/config_grievous.py` to see if `GrievousHostConfig` exists or if we need to create it
  - **Found:** `GrievousHostConfig` exists (lines 104-118) with all required fields: ports (5555/5556), connection_time_s (3600), watchdog_timeout_ms (500), max_loop_freq_hz (60).
- [x] **Decision:** Use `Grievous` class (not `XLerobot`) to enable future leader arm overwrite capability without refactoring

### Phase 2: Client-Side Changes (Enable Action Sending)
- [x] Modify `src/lerobot/robots/grievous/grievous_client.py`:
  - [x] Uncomment the `send_action` ZMQ transmission line (Line 478)
  - [x] Add logging to confirm actions are being sent successfully (debug-level log added)
  - [x] Ensure error handling is adequate for network failures during action transmission (existing `zmq.Again` and `Exception` handlers are sufficient)
- [x] Test the client in isolation:
  - [x] Create a simple test script that instantiates `GrievousClient` and calls `send_action` with dummy data
    - **Created:** `test_grievous_client_send.py` - sets up ZMQ receiver, connects client, sends action, verifies JSON format
  - [x] Verify the ZMQ message is properly formatted as JSON
    - **Result:** ✓ TEST PASSED - Message received, valid JSON, all action keys present
  - [ ] Confirm that enabling `send_action` doesn't break existing recording workflow (Host ignores it)
    - **Note:** Will verify in Phase 7 (Recording Workflow Verification)

### Phase 3: Create Inference Host Script
- [x] Create new file `src/lerobot/robots/grievous/grievous_inference_host.py`:
  - [x] Copy control loop structure from `xlerobot_host.py` as template
  - [x] Create `GrievousInferenceHost` class with ZMQ socket setup:
    - [x] Command socket: `zmq.PULL` bound to port 5555
    - [x] Observation socket: `zmq.PUSH` bound to port 5556
  - [x] Implement `main()` function:
    - [x] Instantiate `Grievous` robot class (includes both follower and leader, but we won't actively use leader arms initially)
    - [x] Connect robot
    - [x] Create host with ZMQ sockets
    - [x] Implement control loop (based on `xlerobot_host.py` pattern):
      - [x] Try to receive network action (non-blocking `recv_string(zmq.NOBLOCK)`)
      - [x] If action received: Execute via `robot.send_action()` + Reset watchdog timer
      - [x] If timeout: Check watchdog → Stop base if >500ms elapsed (via `robot.xlerobot.stop_base()`)
      - [x] Read observation via `robot.get_observation()` (follower state + cameras only)
      - [x] Encode camera images to base64 (JPEG, quality 90)
      - [x] Send observation to network (non-blocking)
      - [x] Rate limit loop to target frequency (50Hz default)
    - [x] **Note:** Leader arms are instantiated but not read/used (enables future overwrite feature)
  - [x] Add proper error handling and cleanup (KeyboardInterrupt, finally block)
  - [x] Add logging for connection status, watchdog events, and timing
- [x] Verify the script structure matches `xlerobot_host.py` control loop pattern
  - **Result:** Control loop structure matches reference pattern, uses `Grievous` robot class, watchdog implemented
- [x] Test host functionality (without robot hardware):
  - [x] Created `test_grievous_inference_host.py` to verify:
    - Host instantiation works
    - ZMQ sockets bind correctly (command PULL, observation PUSH)
    - Host can receive actions via ZMQ
    - Cleanup works properly
  - **Result:** ✓ ALL TESTS PASSED - Host sockets work correctly, action reception verified

### Phase 4: Configuration Setup
- [x] Check if `GrievousHostConfig` exists in `config_grievous.py`:
  - [x] If exists: Verify it has required fields (ports, timeouts, loop frequency)
    - **Found:** `GrievousHostConfig` exists (lines 104-118) with all required fields
    - **Fields:** port_zmq_cmd (5555), port_zmq_observations (5556), connection_time_s (3600), watchdog_timeout_ms (500), max_loop_freq_hz (60)
  - [x] If missing: Create `GrievousHostConfig` dataclass with:
    - **Not needed:** Configuration already exists
- [x] Ensure inference host script uses this configuration
  - **Verified:** `grievous_inference_host.py` imports and uses `GrievousHostConfig` correctly
  - **Tested:** Created `test_grievous_host_config.py` - all tests passed
    - Default configuration works
    - Custom configuration values work
    - Host correctly uses configuration values

### Phase 5: Local Testing (Socket Communication)
- [x] Test socket communication on localhost:
  - [x] Run `grievous_inference_host.py` on local machine
    - **Tested:** Created `test_grievous_socket_communication.py` that instantiates both host and client
  - [x] Run a test script that instantiates `GrievousClient` and sends dummy actions
    - **Result:** ✓ Client successfully sends actions to host
  - [x] Verify host receives actions and executes them
    - **Result:** ✓ Host receives actions correctly, action structure verified (17 keys)
  - [x] Verify host sends observations back to client
    - **Result:** ✓ Host sends observations, client receives them correctly (18 keys)
  - [x] Measure round-trip latency (observation → client → action → host)
    - **Result:** Average latency: 10.17ms (Min: 10.13ms, Max: 10.19ms) - Well within <100ms target
  - [ ] Test watchdog: Stop sending actions and verify base stops after 500ms
    - **Note:** Requires actual robot hardware - will test in Phase 6

### Phase 6: Integration Testing (Local Network) - SAFETY CRITICAL

**⚠️ SAFETY PROTOCOL:**
- Always have physical access to robot during testing
- Keep leader arms accessible for manual override
- Start with zero/stationary actions before testing movement
- Test watchdog and emergency stop BEFORE full policy execution
- Use short timeouts initially (connection_time_s=60 for first tests)
- Monitor robot behavior closely during first tests

#### Phase 6.1: Pre-Flight Safety Checks
- [x] **Verify robot is in safe starting position:**
  - [x] Arms are in neutral/resting position
  - [x] Base is stationary
  - [x] No obstacles in robot workspace
  - [x] Leader arms are accessible for manual override
- [x] **Verify existing recording workflow still works:**
  - [x] Run `grievous_host.py` on robot (original script)
  - [x] Run `lerobot_record.py --robot.type=grievous_client` on laptop (no policy)
  - [x] Verify leader arms control follower correctly
  - [x] Verify camera observations are received
  - [x] **Result:** Recording workflow verified - no regressions from our changes
- [x] **Created:** `PHASE_6_1_SAFETY_CHECKLIST.md` for manual verification
  - **Status:** All checks completed successfully

#### Phase 6.2: Host Startup Test (No Client Connection)
- [x] **Test inference host startup without client:**
  - [x] Run `grievous_inference_host.py` on robot with `connection_time_s=10` (short test)
    - **Implementation:** Modified script to use `GrievousHostConfig(connection_time_s=10)` for testing
  - [x] Verify host starts without errors
    - **Result:** ✓ Host started successfully, all components initialized
  - [x] Verify sockets bind correctly (check logs)
    - **Result:** ✓ Command socket (PULL) bound to tcp://*:5555, Observation socket (PUSH) bound to tcp://*:5556
  - [x] Verify robot connects (follower + leader arms)
    - **Result:** ✓ All components connected: XLerobot (follower), both SO100Leader arms, all 3 cameras (left_wrist, right_wrist, head RealSense)
  - [x] Verify robot does NOT move (no commands received)
    - **Result:** ✓ Robot remained stationary, no unexpected movements observed
  - [x] Stop host (Ctrl+C) and verify cleanup works
    - **Result:** ✓ Ctrl+C handled correctly, KeyboardInterrupt caught, all cleanup messages present:
      - "Keyboard interrupt received. Shutting down..."
      - All cameras disconnected (left_wrist, right_wrist, head RealSense)
      - XLerobot disconnected
      - Both leader arms disconnected (left and right)
      - ZMQ sockets closed properly
      - "Grievous inference host shutdown complete"
- [x] **Verify watchdog triggers correctly:**
  - [x] Run host again, wait 600ms (longer than 500ms watchdog timeout)
    - **Result:** ✓ Watchdog triggered automatically at 500ms (no commands received)
  - [x] Verify base stops (watchdog should trigger)
    - **Result:** ✓ Base motors stopped successfully via `robot.xlerobot.stop_base()`
  - [x] Check logs confirm watchdog activation
    - **Result:** ✓ Log shows: "Command not received for 500ms. Stopping base for safety." and "Base motors stopped"
  - [x] **CRITICAL:** Verify robot stops safely, no unexpected movements
    - **Result:** ✓ Robot stopped safely, watchdog safety feature working as designed

#### Phase 6.3: Client Connection Test (Zero Actions)
- [x] **Created test script:** `test_phase_6_3_client_connection.py`
  - **Features:** Connects to robot at 192.168.50.47, receives observations for 10 seconds, never sends actions
  - **Verification:** Logs observation structure, counts received observations, verifies cameras + state present
- [x] **Test client connection with zero actions:**
  - [x] Run `grievous_inference_host.py` on robot
    - **Status:** Host running and waiting for commands
  - [x] On laptop, run `test_phase_6_3_client_connection.py`
    - **Result:** ✓ Test completed successfully
  - [x] Verify client connects successfully
    - **Result:** ✓ Client connected to 192.168.50.47 without errors
  - [x] Verify observations are received (check for cameras + state)
    - **Result:** ✓ 97 observations received in 10.1s (9.6 obs/sec average)
    - **Structure:** 21 keys total - 9 camera keys (left_wrist, right_wrist, head), 17 state keys (arm positions, base velocities, head positions)
  - [x] Verify robot remains stationary (no actions sent)
    - **Result:** ✓ Robot remained stationary throughout test (no actions sent, as expected)
  - [x] Run for 10 seconds, verify no unexpected movements
    - **Result:** ✓ No unexpected movements observed, test ran for full 10.1 seconds
  - [x] Stop both scripts, verify cleanup
    - **Result:** ✓ Client disconnected cleanly, no errors in cleanup

#### Phase 6.4: Stationary Action Test (Hold Position) - ✅ COMPLETE
- [x] **Test sending actions that maintain current position:**
  - [x] Run `grievous_inference_host.py` on robot
    - **Result:** ✓ Host running and receiving commands successfully
  - [x] Verify actions are sent successfully from laptop
    - **Result:** ✓ 15 actions sent per test run at 5Hz (100% success rate)
  - [x] Verify host receives actions
    - **Result:** ✓ 25 "Action received and executed: 17 keys" messages per test run
    - **Communication latency:** ~200ms per action at 5Hz send rate
  - [x] Verify robot responds to commands
    - **Test:** Sent +1.15 degree offset to left_arm_shoulder_pan
    - **Result:** ✓ Robot arm moved visibly (~1.15 degrees rotation), then returned to original position
    - **Observation:** Movement was smooth and controlled, exactly as expected
  - [x] Verify watchdog functionality
    - **Result:** ✓ Watchdog triggers correctly after 500ms of no commands
    - **Log confirmation:** "Command not received for 500ms. Stopping base for safety."
  - [x] **CRITICAL:** Robot should not drift or move unexpectedly
    - **Result:** ✓ No drift or unexpected movement observed, position stability verified

**Critical Bugs Fixed:**
1. **ZMQ CONFLATE on PULL socket:** Removed `zmq.CONFLATE` option from command socket (line 67 in `grievous_inference_host.py`). CONFLATE is incompatible with PULL sockets and was blocking all message reception.
2. **Unit verification:** Confirmed observations and actions both use degrees (consistent with dataset recording configuration).

**Communication Status:**
- ✅ ZMQ PUSH→PULL working correctly (laptop → robot)
- ✅ ZMQ PUSH→PULL working correctly (robot → laptop)
- ✅ Actions received and executed on robot
- ✅ Observations received on laptop
- ✅ Watchdog safety mechanism operational

**Documentation Created:**
- `context_notes/why_push_push_seemed_to_work.md` - Explains why PUSH→PUSH appeared to work but didn't
- `context_notes/zmq_noblock_explanation.md` - Explains ZMQ buffer behavior and NOBLOCK flag
- `HOW_TO_RUN_INFERENCE_HOST.md` - Instructions for running inference host correctly

#### Phase 6.5: Small Movement Test (Minimal Displacement) - ✅ SKIPPED (Redundant)
- [x] **SKIPPED: Objectives already achieved in Phase 6.4:**
  - Phase 6.4 already verified robot responds to remote commands with small movements (+1.15 degrees)
  - Robot movement verified as smooth and controlled ✓
  - Position holding verified ✓
  - Testing with even smaller movements provides no additional value
  - **Decision:** Proceed directly to Phase 6.7 (Policy Integration)

#### Phase 6.6: Watchdog Safety Test - ✅ SKIPPED (Behavior Verified)
- [x] **SKIPPED: Watchdog behavior already confirmed:**
  - **Reason:** Watchdog triggers correctly at startup (500ms timeout observed in logs)
  - **Base behavior:** Stops when no commands received ✓
  - **Arms behavior:** Hold position (motors remain torqued) ✓
  - **Safety:** Proven safe - no need to test with moving robot
  - **Decision:** User preference to avoid unnecessary risk during safety testing
  - **Evidence:** Host logs show "Command not received for 500ms. Stopping base for safety." at startup

#### Phase 6.7: Policy Integration Test (Dummy Policy) - ✅ COMPLETE
- [x] **Created StatefulOffsetPolicy:**
  - [x] Created `src/lerobot/policies/stateful_offset/modeling_stateful_offset.py` - Simple policy that outputs `current_state + offset_degrees`
  - [x] Created `src/lerobot/policies/stateful_offset/configuration_stateful_offset.py` - Policy config with `offset_degrees` and `target_joints` parameters
  - [x] Created `src/lerobot/policies/stateful_offset/processor_stateful_offset.py` - Minimal processor (batch dimension + device placement)
  - [x] Created `src/lerobot/policies/stateful_offset/__init__.py` - Module initialization
  - [x] Registered policy in `src/lerobot/policies/factory.py` (both `get_policy_class` and `make_policy_config`)
  - [x] Created `tests/grievous_inference/test_policy_action_order_fix.py` - Unit test verifying correct joint targeting
- [x] **Test policy in isolation:**
  - [x] Run unit tests to verify policy logic ✓
  - [x] Verified action tensor ordering matches dataset feature order ✓
- [x] **Test with full LeRobot pipeline:**
  - [x] Run `grievous_inference_host.py` on robot ✓
  - [x] Run `lerobot-record --robot.type=grievous_client --policy.type=stateful_offset --policy.offset_degrees=1.0 --policy.target_joints='["left_arm_shoulder_pan", "right_arm_shoulder_pan"]'` on laptop ✓
  - [x] Verify observations flow: robot → client → policy ✓
  - [x] Verify actions flow: policy → client → robot ✓
  - [x] Monitor robot behavior - Only targeted motors moved (left and right shoulder_pan) ✓
  - [x] Verify control loop frequency - ~30Hz achieved ✓
  - [x] **CRITICAL:** Robot movements confirmed smooth and predictable ✓

**Critical Bugs Fixed in Phase 6.7:**
1. **Index/Key Ordering Bug:** Policy was using alphabetical sorting of observation keys, causing tensor indices to mismatch with dataset action feature order. Fixed by extracting and using `action_names` from `ds_meta.features["action"]["names"]` to ensure correct index-to-joint mapping.
2. **Velocity Command Bug:** Policy was applying offsets to base velocity commands (`.vel`), causing unwanted base movement. Fixed by skipping velocity commands and only applying offsets to position commands (`.pos`).
3. **action_names Extraction:** Added comprehensive logging and extraction logic in `make_policy()` to populate `action_names` from dataset metadata, enabling targeted joint offsets.

**Test Results:**
- ✅ Only targeted motors moved (shoulder_pan joints)
- ✅ Base remained stationary (velocity commands set to 0)
- ✅ All other arm joints held position
- ✅ Watchdog safety operational
- ✅ End-to-end pipeline functional: Observation → Policy → Action → Robot

**Movement Quality:**
- Movements somewhat jerky at 1.0°/step (30°/sec at 30Hz)
- Recommended: Use 0.2-0.5° offset for smoother motion (6-15°/sec)

**Documentation Created:**
- `tests/grievous_inference/test_action_values_debug.py` - Debug script to verify which motors respond to commands
- `tests/grievous_inference/test_policy_action_order_fix.py` - Unit test for action ordering fix

#### Phase 6.8: Latency and Performance Test - ⏭️ DEFERRED
- [ ] **DEFERRED: Will measure during Phase 8.2 (SmolVLA remote test)**
  - Latency measurement more meaningful with real network latency (RunPod → Robot)
  - Will measure: observation → inference → action → execution
  - Target: <200ms end-to-end for internet connection

#### Phase 6.9: Extended Stability Test - ⏭️ DEFERRED
- [ ] **DEFERRED: Will test during Phase 8.4 (SmolVLA stability test)**
  - Extended stability test more valuable with real policy (SmolVLA)
  - Will run for 2-5 minutes with actual inference load

#### Phase 6.10: Manual Override Test - ⏭️ SKIPPED
- [ ] **SKIPPED: Future feature, not needed for current deployment**
  - Leader arms are connected but unused in current implementation
  - Can revisit when implementing overwrite feature

### Phase 7: Recording Workflow Verification - ⏭️ DEFERRED
- [ ] **DEFERRED: Will verify after SmolVLA testing**
  - Recording workflow should be unaffected by inference changes
  - Can verify when needed for future dataset collection
  - Priority: Get SmolVLA inference working first

### Phase 8: SmolVLA Remote Inference Testing (RunPod → Robot)

**⚠️ SAFETY PROTOCOL:**
- Phase 8.1-8.2: Actions are LOGGED ONLY, NOT EXECUTED
- Phase 8.3+: Actions executed with manual supervision
- Always ready to terminate RunPod script if needed

#### Phase 8.1: RunPod Setup & Environment Preparation
- [ ] **Setup RunPod instance:**
  - [ ] Provision GPU instance (check `setup_runpod.sh` for requirements)
  - [ ] Install lerobot package and dependencies
  - [ ] Copy SmolVLA checkpoint to RunPod
  - [ ] Verify model loads correctly (test inference on dummy data)
- [ ] **Network configuration:**
  - [ ] Get RunPod instance public IP
  - [ ] Configure robot laptop to allow incoming connections from RunPod IP
  - [ ] Test basic network connectivity (ping, telnet to ports 5555/5556)
  - [ ] Document firewall rules if needed
- [ ] **Verify dataset/checkpoint compatibility:**
  - [ ] Confirm SmolVLA expects same observation keys as Grievous provides
  - [ ] Verify action space matches (17 action dimensions)
  - [ ] Check image resolution expectations vs. actual camera feeds

#### Phase 8.2: Dry-Run Test (Latency Measurement, NO ACTION EXECUTION) - 🔄 NEXT
- [ ] **Modify inference host for dry-run mode:**
  - [ ] Add `--dry-run` flag to `grievous_inference_host.py`
  - [ ] In dry-run mode: Receive actions, LOG to file, but skip `robot.send_action()`
  - [ ] Log format: `[timestamp] Action received: {action_dict}`
  - [ ] Keep all other functionality (observations, watchdog, rate limiting)
- [ ] **Run first remote test:**
  - [ ] On robot laptop: `python -m lerobot.robots.grievous.grievous_inference_host --dry-run --log-actions=/tmp/actions_log.txt`
  - [ ] On RunPod: `lerobot-record --robot.type=grievous_client --robot.host=<ROBOT_IP> --policy.path=<SMOLVLA_CHECKPOINT> --dataset.repo_id=test/eval_smolvla_remote`
  - [ ] Let run for 30-60 seconds
  - [ ] Monitor both terminals for errors
- [ ] **Verify communication:**
  - [ ] Confirm RunPod receives observations from robot
  - [ ] Confirm robot receives actions from RunPod
  - [ ] Check `/tmp/actions_log.txt` - should contain action dictionaries
  - [ ] Verify no dropped frames or connection timeouts
- [ ] **Measure latency:**
  - [ ] Add timestamp logging: observation sent → action received
  - [ ] Calculate average, min, max, p95 latency
  - [ ] Target: <200ms end-to-end (internet adds ~50-100ms vs. local network)
  - [ ] Document results in plan
- [ ] **Inspect action quality:**
  - [ ] Review logged actions - do they look reasonable?
  - [ ] Check for NaN, inf, or extreme values
  - [ ] Verify action keys match expected format
  - [ ] Compare action magnitudes to training data ranges

#### Phase 8.3: Enable Action Execution (Supervised)
- [ ] **Safety checklist before enabling:**
  - [ ] Dry-run test completed successfully ✓
  - [ ] Latency measured and acceptable ✓
  - [ ] Actions inspected and look reasonable ✓
  - [ ] Robot in safe starting position ✓
  - [ ] Leader arms accessible for manual override ✓
  - [ ] Clear workspace, no obstacles ✓
- [ ] **First live test:**
  - [ ] Remove `--dry-run` flag from inference host
  - [ ] Start with SHORT test: 10 seconds
  - [ ] Be ready to Ctrl+C on RunPod if robot behaves unexpectedly
  - [ ] Monitor robot movements closely
  - [ ] Verify movements align with policy's training task
- [ ] **Extended test:**
  - [ ] If 10-second test looks good, run for 30 seconds
  - [ ] Monitor for drift, instability, or unexpected behaviors
  - [ ] Verify watchdog triggers if RunPod disconnects

#### Phase 8.4: Performance & Stability Test
- [ ] **Measure performance metrics:**
  - [ ] Control loop frequency (target: >20Hz for VLA)
  - [ ] Action smoothness and consistency
  - [ ] Network stability (packet loss, jitter)
  - [ ] CPU/GPU utilization on both sides
- [ ] **Extended stability test:**
  - [ ] Run for 2-5 minutes continuously
  - [ ] Monitor for memory leaks or degradation
  - [ ] Test recovery from temporary network issues
  - [ ] Verify watchdog behavior during disconnection

#### Phase 8.5: Network Robustness Testing
- [ ] **Test failure modes:**
  - [ ] Terminate RunPod script mid-execution → Verify watchdog stops base
  - [ ] Simulate network lag (if possible) → Measure impact
  - [ ] Test reconnection behavior
- [ ] **Document findings:**
  - [ ] Actual latency vs. target
  - [ ] Any issues encountered
  - [ ] Recommendations for production deployment

### Phase 9: Documentation & Cleanup
- [ ] Update `context_notes/remote_inference_architecture.md` with final implementation details
- [ ] Create a usage guide document:
  - [ ] How to run remote policy inference (`grievous_inference_host.py` + `lerobot_record.py`)
  - [ ] How to run dataset recording (`grievous_host.py` + `lerobot_record.py`)
  - [ ] How to configure network settings (IP, ports)
  - [ ] How to troubleshoot common issues (latency, connection failures, watchdog timeouts)
- [ ] Add inline code comments explaining the control loop logic
- [ ] Remove any debug print statements or reduce log verbosity for production use
- [ ] Create example command-line invocations for both recording and inference modes
- [ ] Document the difference between the two host scripts and when to use each

### Phase 10: Performance Optimization (Optional)
- [ ] Profile the control loop to identify bottlenecks
- [ ] Optimize image encoding (JPEG quality vs. size vs. speed)
- [ ] Consider using msgpack instead of JSON for faster serialization
- [ ] Add metrics logging (loop frequency, latency, dropped frames)
- [ ] Tune watchdog timeout based on empirical latency measurements

## Success Criteria
- Remote policy can control the robot with <100ms latency (target)
- Watchdog safety works: Robot stops within 500ms if policy script terminates
- Existing recording workflow remains functional and completely unaffected
- No regressions in camera streaming or state observation quality
- System is stable for continuous operation (>10 minutes without crashes)
- Clear separation between recording and inference modes (two separate host scripts)

