# Creating Persistent Udev Names for Motor Controllers and Cameras

This guide shows how to give each USB motor controller and camera a stable device
name on Ubuntu, so they no longer change between `/dev/ttyACM*` or `/dev/video*` numbers.

------------------------------------------------------------------------

## 1. Identify Each Controller's Serial Number

For each motor controller, run:

    lerobot-find-ports

Then identify which /dev/ttyACM* port the motor controller is running on and run:

    udevadm info -a -n /dev/ttyACM0 | grep serial

Record each device's serial number.

------------------------------------------------------------------------

## 2. Create the Udev Rules File

Create a new rules file:

    sudo nano /etc/udev/rules.d/99-motor-controllers.rules

Add one line per controller, using only the **serial** field:

    SUBSYSTEM=="tty", ATTRS{serial}=="###", SYMLINK+="follower_left"
    SUBSYSTEM=="tty", ATTRS{serial}=="###", SYMLINK+="leader_left"
    SUBSYSTEM=="tty", ATTRS{serial}=="###", SYMLINK+="follower_right"
    SUBSYSTEM=="tty", ATTRS{serial}=="###", SYMLINK+="leader_right"

Save and exit.

------------------------------------------------------------------------

## 3. Reload Udev Rules

Apply your changes:

    sudo udevadm control --reload-rules
    sudo udevadm trigger

You may need to unplug and replug the controllers.

------------------------------------------------------------------------

## 4. Verify the Symlinks

List the created symlinks:

    ls -l /dev/follower_left /dev/follower_right /dev/leader_left /dev/leader_right

You should see output similar to:

    /dev/follower_left  -> ttyACM0
    /dev/follower_right -> ttyACM1
    /dev/leader_left    -> ttyACM3
    /dev/leader_right   -> ttyACM2

------------------------------------------------------------------------

## 5. Use the Stable Device Names

You can now always refer to the controllers using:

    /dev/follower_left
    /dev/follower_right
    /dev/leader_left
    /dev/leader_right

These will not change, regardless of USB port order or enumeration.

------------------------------------------------------------------------

# Creating Persistent Udev Names for OpenCV Cameras

This guide shows how to give each USB camera a stable device name on Ubuntu, even when `/dev/video*` numbers change. This method is used when cameras do not have unique serial numbers.

------------------------------------------------------------------------

## 1. Identify Each Camera's USB Port Path

Run the following command:

    lerobot-find-cameras opencv

Then find the output for each camera under /outputs/opencv__dev_video*. Use this to find the /dev/video* path for the two wrist cameras.

Then run:

    udevadm info -a -n /dev/video*

Look for a `KERNELS==` line belonging to a parent USB device. Example values:

    KERNELS=="1-3.1"
    KERNELS=="1-6"

Record each camera's path and assign a name:

- `cam_left` → `KERNELS=="1-3.1"`
- `cam_right` → `KERNELS=="1-6"`

------------------------------------------------------------------------

## 2. Create the Udev Rules File

Create the rules file:

    sudo nano /etc/udev/rules.d/99-wrist-cameras.rules

Add the rules (replace `KERNELS==` values with your actual ones):

    # Wrist Camera Left
    SUBSYSTEM=="video4linux", KERNEL=="video*", KERNELS=="1-3.1", SYMLINK+="cam_left"

    # Wrist Camera Right
    SUBSYSTEM=="video4linux", KERNEL=="video*", KERNELS=="1-6", SYMLINK+="cam_right"

Save and exit.

------------------------------------------------------------------------

## 3. Reload Udev Rules

Apply the rules:

    sudo udevadm control --reload-rules
    sudo udevadm trigger

Unplug and replug the cameras.

------------------------------------------------------------------------

## 4. Verify the Symlinks

Check that the persistent names exist:

    ls -l /dev/cam_left /dev/cam_right

You should see each name point to whichever `/dev/video*` number the system assigned.

------------------------------------------------------------------------

## 5. Use the Stable Device Names

You can now reliably access the cameras using:

    /dev/cam_left
    /dev/cam_right

**Notes:**
- This method works when cameras do not have unique serial numbers.
- USB port paths are stable unless you physically move cables.
- If you move a camera to a different USB port, update the `KERNELS==` value in the rule.
