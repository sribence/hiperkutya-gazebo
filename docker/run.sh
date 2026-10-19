#!/bin/bash
# A konténer indítószkriptje: virtuális kijelző + noVNC, Gazebo, vezérlő node-ok, irányítás.
# Irányítás (CONTROL környezeti változó):
#   auto    (alap) gamepad, ha a konténer lát joystickot (/dev/input/js*), különben webes pult
#   gamepad joy_node + hyperdog_teleop_joy_node (az eredeti gamepad-lánc)
#   web     tools/hd_web.py, http://localhost:6081
# A kettő nem futhat egyszerre: mindkettő a /hyperdog_joy_ctrl_cmd topicra küld.
# Célkövetés (TARGET környezeti változó, docs/CELKOVETES.md):
#   off     (alap) nincs célkövetés
#   on      tools/target_follower.py a pult/gamepad és a cmd_manager közé ül, és a
#           /target_point topicra küldött célpont felé fordítja a testet
#   sim     mint az on, és tools/sim_target.py egy mozgó piros labdát követtet
# Naplók: /tmp/sim.log, cmd.log, pd.log, ik.log, és joy.log + teleop.log vagy web.log,
#         célkövetésnél follower.log (+ sim_target.log)
export DISPLAY=:1
rm -f /tmp/.X1-lock /tmp/.X11-unix/X1   # docker restart után a régi lock megakasztja az Xvfb-t
Xvfb :1 -screen 0 1600x900x24 &
sleep 2; fluxbox >/dev/null 2>&1 &
x11vnc -display :1 -forever -shared -nopw -quiet >/dev/null 2>&1 &
websockify --web /usr/share/novnc 6080 localhost:5900 >/dev/null 2>&1 &
. /opt/ros/foxy/setup.bash; . /ws/install/setup.bash
ros2 launch hyperdog_gazebo_sim hyperdog_gazebo_sim.launch.py > /tmp/sim.log 2>&1 &
sleep 20   # a Gazebo és a controllerek betöltése
ros2 run hyperdog_ctrl cmd_manager_node > /tmp/cmd.log 2>&1 &
python3 /opt/hiperkutya/pd_bridge.py > /tmp/pd.log 2>&1 &
ros2 run hyperdog_ctrl IK_node > /tmp/ik.log 2>&1 &

CONTROL=${CONTROL:-auto}
if [ "$CONTROL" = auto ]; then
  ls /dev/input/js* >/dev/null 2>&1 && CONTROL=gamepad || CONTROL=web
fi
TARGET=${TARGET:-off}
echo "irányítás: $CONTROL, célkövetés: $TARGET" > /tmp/control.txt
REMAP=""
if [ "$TARGET" != off ]; then
  # a pult/gamepad nem közvetlenül a cmd_managernek küld, hanem a követőnek
  REMAP="--ros-args -r hyperdog_joy_ctrl_cmd:=teleop_cmd"
  python3 /opt/hiperkutya/target_follower.py --ros-args -p use_sim_time:=true > /tmp/follower.log 2>&1 &
fi
if [ "$TARGET" = sim ]; then
  python3 /opt/hiperkutya/sim_target.py --ros-args -p use_sim_time:=true > /tmp/sim_target.log 2>&1 &
fi
if [ "$CONTROL" = gamepad ]; then
  ros2 run joy joy_node > /tmp/joy.log 2>&1 &
  ros2 run hyperdog_teleop hyperdog_teleop_joy_node $REMAP > /tmp/teleop.log 2>&1 &
  gz camera -c gzclient_camera -f HyperDog   # a kamera kövesse a robotot
else
  python3 /opt/hiperkutya/hd_web.py $REMAP > /tmp/web.log 2>&1 &
fi
sleep infinity
