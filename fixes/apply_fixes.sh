#!/bin/bash
# A hyperdog_ros2 (NDHANA94) repó Gazebo-szimulációjának javításai.
# Használat: bash apply_fixes.sh <a hyperdog_ros2 repó gyökere>
# A forrásfájlokat módosítja, utána colcon build kell.
# Többször is lefuttatható: amit már javított, azt nem rontja el.
set -e
R=${1:-.}
SIM=$R/hyperdog_gazebo_sim
GAIT=$R/hyperdog_ctrl/gait_generator/gait_planner.py
[ -d "$SIM" ] && [ -f "$GAIT" ] || { echo "Nem a hyperdog_ros2 gyökere: $R" >&2; exit 1; }

# 1. Fölösleges IDE-import: a launch 'No module named black' hibával leáll
sed -i '/^from black import out/d' $SIM/launch/*.py

# 2. matplotlib Tk-backendet keres grafikus felület mellett ('No module named tkinter'),
#    és a cmd_manager összeomlik. Agg backend: nem rajzol ablakot, nem kell hozzá Tk.
sed -i 's/^import matplotlib.pyplot as plt$/import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt/' $GAIT

# 3. give_hand ("pacsi", gait_type 0, ez az alapérték!) alvás nélküli végtelen ciklus:
#    elfoglalja a Python GIL-t, a cmd_manager nem publikál, a robot lefagy egy felemelt lábbal.
grep -q 'time.sleep(0.01)  # give_hand' $GAIT || \
  sed -i '/def give_hand/,/def run/ s/^\(            self.FR_traj\[2\] = self.cmd.gait.step_len\[1\]\)$/\1\n            time.sleep(0.01)  # give_hand: GIL elengedése/' $GAIT

# 4. Erőalapú vezérlés. Pozíciós módban a Foxy gazebo_ros2_control "teleportálja" a csuklót
#    (SetPosition), a talp nem tud elrugaszkodni, a robot csúszik és nem halad.
#    Helyette nyomaték-parancs (±10 Nm), amit a tools/pd_bridge.py PD-szabályzója számol.
sed -i -e 's/<command_interface name="position">/<command_interface name="effort">/' \
       -e 's|<param name="min">[^<]*</param>|<param name="min">-10</param>|' \
       -e 's|<param name="max">[^<]*</param>|<param name="max">10</param>|' \
       $SIM/description/gazebo_ros2_control_plugin.xacro

# 5. friction="10000" gyakorlatilag befagyasztja a csuklókat; 1 rad/s sebességkorlát járáshoz kevés
sed -i -e 's/friction="10000"/friction="0.0"/' \
       -e 's/name="velocity"       value="1"/name="velocity"       value="20"/' \
       $SIM/description/consts.xacro

# 6. Nyomatékos controller, és 100 Hz helyett 500 Hz (a PD-hez sűrűbb frissítés kell)
sed -i -e 's|forward_command_controller/ForwardCommandController|effort_controllers/JointGroupEffortController|' \
       -e 's/update_rate: 100/update_rate: 500/' \
       $SIM/config/hyperdog_joint_controller.yaml

# 7. A gyári fok->radián pozíciós hidat a pd_bridge.py váltja ki, ezért nem indítjuk
sed -i 's/^    hyperdog_gz_joint_ctrl_node,$/    # hyperdog_gz_joint_ctrl_node,  # helyette: tools\/pd_bridge.py/' \
       $SIM/launch/hyperdog_gazebo_sim.launch.py

# Ellenőrzés: ha a forrás megváltozott és egy javítás nem talált, itt kiderül
fail=0
chk(){ grep -q "$2" "$1" || { echo "NEM SIKERÜLT: $3 ($1)" >&2; fail=1; }; }
nchk(){ ! grep -q "$2" "$1" || { echo "NEM SIKERÜLT: $3 ($1)" >&2; fail=1; }; }
nchk $SIM/launch/hyperdog_gazebo_sim.launch.py '^from black' "1. black import"
chk  $GAIT 'matplotlib.use("Agg")' "2. matplotlib Agg"
chk  $GAIT 'time.sleep(0.01)  # give_hand' "3. give_hand alvás"
nchk $SIM/description/gazebo_ros2_control_plugin.xacro 'command_interface name="position"' "4. effort interfész"
nchk $SIM/description/consts.xacro 'friction="10000"' "5. csuklósúrlódás"
chk  $SIM/config/hyperdog_joint_controller.yaml 'JointGroupEffortController' "6. effort controller"
chk  $SIM/launch/hyperdog_gazebo_sim.launch.py '# hyperdog_gz_joint_ctrl_node' "7. pozíciós híd ki"
[ $fail = 0 ] && echo "Mind a 7 javítás rendben."
exit $fail
