# ErgoAssist Skill – ROS 2 Workspace Vulcanexus

Initial open-source repository for the ErgoAssist skill developed in the POSTURE PoC (ARISE programme).

## Contents

This workspace contains the following ROS 2 packages:

- `ergoassist_msgs`: message, action and service definitions  
  (e.g. `TableState.msg`, `PostureObservation.msg`, `AdjustTableHeight.action`).
- `ergoassist_mission`: mission coordinator skeleton (ROS4HRI skills).
- `ergoassist_table`: ergonomic table controller skeleton.
- `ergoassist_perception`: posture estimation node skeleton.

## Status

This repository provides an initial skeleton for interface validation and early reuse within the ARISE consortium. Full implementations, documentation and tutorials will be added incrementally.

## Requirements

- ROS 2
- `colcon` build system
- Vulcanexus

## Usage

```bash
# Clone the workspace
git clone <REPO_URL> ergoassist_ws
cd ergoassist_ws

# Build
colcon build

# Source
source install/setup.bash    # Linux / macOS
# or
install\setup.bat            # Windows (PowerShell / CMD)
```

## Licence

Apache-2.0.

