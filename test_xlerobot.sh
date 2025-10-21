#!/bin/bash

# Test XLerobot with bimanual leader-follower control using lerobot-teleoperate CLI
#
# Hardware: 2x SO101 leader arms + XLerobot follower
# Usage: ./test_xlerobot.sh

# Port Configuration - EDIT THESE TO MATCH YOUR HARDWARE
LEADER_1_PORT="/dev/ttyACM3"
LEADER_2_PORT="/dev/ttyACM2"
FOLLOWER_1_PORT="/dev/ttyACM0"
FOLLOWER_2_PORT="/dev/ttyACM1"

# Robot IDs
XLEROBOT_ID="my_xlerobot"
LEADER_ID="my_bimanual_leader"

echo "Starting XLerobot bimanual leader-follower teleoperation..."
echo ""
echo "Leader arms:"
echo "  Leader 1: $LEADER_1_PORT"
echo "  Leader 2: $LEADER_2_PORT"
echo ""
echo "XLerobot follower:"
echo "  Follower 1: $FOLLOWER_1_PORT"
echo "  Follower 2: $FOLLOWER_2_PORT"
echo ""
echo "Press Ctrl+C to stop"
echo ""

# Run lerobot-teleoperate
lerobot-teleoperate \
    --robot.type=bi_so100_follower \
    --robot.id=$XLEROBOT_ID \
    --robot.left_arm_port=$FOLLOWER_1_PORT \
    --robot.right_arm_port=$FOLLOWER_2_PORT \
    --teleop.type=bi_so100_leader \
    --teleop.id=$LEADER_ID \
    --teleop.left_arm_port=$LEADER_1_PORT \
    --teleop.right_arm_port=$LEADER_2_PORT \
    --display_data=true

