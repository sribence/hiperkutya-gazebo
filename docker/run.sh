#!/bin/bash
# A konténer indítószkriptje: virtuális kijelző + noVNC, Gazebo, vezérlő node-ok, webes pult.
# Naplók: /tmp/sim.log, cmd.log, pd.log, ik.log, web.log
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
python3 /opt/hiperkutya/hd_web.py > /tmp/web.log 2>&1 &
sleep infinity
