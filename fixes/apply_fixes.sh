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

# 8. Az IK (get_joint_angles) arccos-os megoldása sok testhelyzetben rossz ágat választ: a talp
#    1-28 cm-rel máshova kerül, mint kellene, és a robot megdől vagy felborul. Helyes csak kb.
#    |yaw| <= 10 fokig (pitch -5..+10 mellett). Pontos inverz ugyanarra a lábgeometriára:
#    csípő atan2-vel, a két combszakasz koszinusztétellel (a térd mindig ugyanarra hajlik).
#    Ez a valódi robot kódja is (hyperdog_ctrl), ott is kell.
IKF=$R/hyperdog_ctrl/IK/InverseKinematics.py
grep -q '# javított IK' $IKF || python3 - "$IKF" <<'EOF'
import re, sys
p = sys.argv[1]; s = open(p).read()
new = '''    def get_joint_angles(self, coord):
        """
            coord: np array with desired leg coordinate -> np.array([x, y, z])
            return: np array with joint angles -> np.array([th0, th1, th2])
        """
        # javított IK: pontos inverz (atan2 + koszinusztétel); az elérhetetlen pontot a hívó kiszűri
        joint_ang = np.zeros([3])
        if self.is_singularity(coord):
            return joint_ang
        x, y, z = coord
        rp = np.sqrt(max(y**2 + z**2 - self.L1**2, 0.0))    # a láb síkjában mért "lefelé" távolság
        th0 = np.arctan2(rp, self.L1) - np.arctan2(z, y)
        k = (x**2 + rp**2 - self.L2**2 - self.L3**2) / (2*self.L2*self.L3)
        q = -np.arccos(np.clip(k, -1.0, 1.0))                  # térdszög a combhoz képest
        a = np.arctan2(rp, x) - np.arctan2(self.L3*np.sin(q), self.L2 + self.L3*np.cos(q))
        joint_ang[:] = th0, np.pi - a, a + q
        return joint_ang

'''
s, n = re.subn(r"    def get_joint_angles\(self, coord\):.*?return joint_ang\n\n", new, s, flags=re.S)
assert n == 1, "get_joint_angles nem található"
# a gyári ellenőrzés csak a csípő-talp távolságot nézi; az is elérhetetlen, ha a talp a csípő
# L1 sugarú körén belülre esne (y-z síkban)
old = "        if r >= self.MIN_LEG_R and r <= self.MAX_LEG_R:"
assert old in s, "is_singularity nem található"
s = s.replace(old, "        if r >= self.MIN_LEG_R and r <= self.MAX_LEG_R and coord[1]**2 + coord[2]**2 > self.L1**2:")
open(p, "w").write(s)
EOF

# 9. Az IK node a szögeket helyben váltja fokba, abban a tömbben, amit az IK "előző jó szögként"
#    tárol. Szingularitás után ezt még egyszer fokba váltaná (45 -> 2578 fok). Másolat kell.
sed -i 's/^\(        ang_[FB][RL] = self.IK.get_[FB][RL]_joint_angles([a-z_]*, eulerAng)\)$/\1.copy()/' \
       $R/hyperdog_ctrl/IK/inverse_kinematic_node.py

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
chk  $IKF '# javított IK' "8. IK pontos inverz"
[ "$(grep -c 'eulerAng).copy()' $R/hyperdog_ctrl/IK/inverse_kinematic_node.py)" = 4 ] || { echo "NEM SIKERÜLT: 9. IK node másolat" >&2; fail=1; }
[ $fail = 0 ] && echo "Mind a 9 javítás rendben."
exit $fail
