"""Szimulált célpont-forrás a Gazebóhoz: kamera és felismerő nélkül ad bemenetet a target_follower-nek.

Egy piros labda (Gazebo actor) mozog a robot előtt: oldalra ±sweep fokot (period s alatt),
fel-le ±pitch_sweep fokot (pitch_period s alatt). A node a robot valódi Gazebo-pózából kiszámolja,
hol van a labda a robot testéhez képest, és ugyanolyan üzenetet küld, amilyet a valódi
kamerás feldolgozónak kell majd küldenie (docs/CELKOVETES.md):
  /target_point  geometry_msgs/PointStamped, frame "base_link" (x előre, y balra, z fel, m)
Valósághű nehezítés: 15 Hz, 150 ms késleltetés, 1 cm zaj. Ha a labda kívül esik a kamera
látómezején (hfov × vfov), nem küld semmit, ahogy a valódi felismerő sem látná.

Indítás (a Docker-környezetben a run.sh indítja, ha TARGET=sim):
  python3 sim_target.py --ros-args -p use_sim_time:=true -p sweep:=20.0 -p pitch_sweep:=10.0
A pitch_period a period egész számú osztója legyen, különben a pálya ismétlődéskor ugrik.
"""
import math
import random
import re
import subprocess
import threading
from collections import deque

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import PointStamped

H0 = 0.17           # a test közepének magassága álló robotnál, m


def quat_rotate_inv(q, v):
    """A v világ-koordinátás vektort a q (x, y, z, w) orientációjú test koordinátáiba forgatja."""
    x, y, z, w = q
    x, y, z = -x, -y, -z                                    # inverz (egységkvaternió)
    tx, ty, tz = 2 * (y * v[2] - z * v[1]), 2 * (z * v[0] - x * v[2]), 2 * (x * v[1] - y * v[0])
    return (v[0] + w * tx + y * tz - z * ty,
            v[1] + w * ty + z * tx - x * tz,
            v[2] + w * tz + x * ty - y * tx)


class SimTarget(Node):
    def __init__(self):
        super().__init__("sim_target")
        for k, v in {"target_yaw": 0.0, "sweep": 20.0, "period": 14.0, "target_pitch": 0.0,
                     "pitch_sweep": 8.0, "pitch_period": 7.0, "distance": 0.8,
                     "hfov": 69.0, "vfov": 42.0, "delay": 0.15, "noise": 0.01}.items():
            self.declare_parameter(k, v)
        self.p = lambda k: self.get_parameter(k).value
        self.pose = None
        self.queue = deque()
        self.spawn_ball()
        threading.Thread(target=self.read_pose, daemon=True).start()
        self.pub = self.create_publisher(PointStamped, "target_point", 10)
        self.create_timer(1 / 15, self.tick)

    def ball(self, t):
        """A labda helyzete a világban t időpontban (a robot indulási helye körül)."""
        a = math.radians(self.p("target_yaw") + self.p("sweep") * math.sin(2 * math.pi * t / self.p("period")))
        pitch = self.p("target_pitch") + self.p("pitch_sweep") * math.sin(2 * math.pi * t / self.p("pitch_period"))
        d = self.p("distance")
        return d * math.cos(a), d * math.sin(a), H0 + d * math.tan(math.radians(pitch))

    def spawn_ball(self):
        """Actor: a pályát a Gazebo maga játssza le a szimulációs órával."""
        per = self.p("period")
        pts = "".join(f"<waypoint><time>{t:.2f}</time><pose>{x:.3f} {y:.3f} {z:.3f} 0 0 0</pose></waypoint>"
                      for t in (i * 0.2 for i in range(int(per / 0.2) + 1)) for x, y, z in [self.ball(t)])
        sdf = f"""<?xml version="1.0"?><sdf version="1.6"><actor name="cel"><link name="link">
<visual name="labda"><geometry><sphere><radius>0.04</radius></sphere></geometry>
<material><ambient>0.8 0.1 0.1 1</ambient><diffuse>0.9 0.1 0.1 1</diffuse></material></visual></link>
<script><loop>true</loop><delay_start>0</delay_start><auto_start>true</auto_start>
<trajectory id="0" type="labda">{pts}</trajectory></script></actor></sdf>"""
        open("/tmp/sim_target.sdf", "w").write(sdf)
        # a gazebo_ros spawn_entity actort nem fogad el, a gz factory igen
        subprocess.run(["gz", "model", "-m", "cel", "-f", "/tmp/sim_target.sdf"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def read_pose(self):
        """Egyetlen tartós gz-folyamat olvassa a robot valódi helyzetét és orientációját."""
        num = r"(-?[\d.e+-]+)"
        pat = re.compile(r'name: "HyperDog" id: \d+ position \{ x: %s y: %s z: %s .*?'
                         r'orientation \{ x: %s y: %s z: %s w: %s' % ((num,) * 7))
        gz = subprocess.Popen(["gz", "topic", "-e", "/gazebo/default/pose/info", "-u"],
                              stdout=subprocess.PIPE, text=True)
        for line in gz.stdout:
            m = pat.search(line)
            if m:
                v = list(map(float, m.groups()))
                self.pose = (v[:3], v[3:])

    def tick(self):
        now = self.get_clock().now()
        t = now.nanoseconds / 1e9
        if self.pose:
            pos, q = self.pose
            bx, by, bz = self.ball(t)
            x, y, z = quat_rotate_inv(q, (bx - pos[0], by - pos[1], bz - pos[2]))
            n = self.p("noise")
            x, y, z = x + random.gauss(0, n), y + random.gauss(0, n), z + random.gauss(0, n)
            yaw, pitch = math.degrees(math.atan2(y, x)), math.degrees(math.atan2(z, math.hypot(x, y)))
            if x > 0 and abs(yaw) <= self.p("hfov") / 2 and abs(pitch) <= self.p("vfov") / 2:
                msg = PointStamped()
                msg.header.stamp = now.to_msg()             # a "kamerakép" ideje
                msg.header.frame_id = "base_link"
                msg.point.x, msg.point.y, msg.point.z = x, y, z
                self.queue.append((t + self.p("delay"), msg))
        while self.queue and self.queue[0][0] <= t:
            self.pub.publish(self.queue.popleft()[1])


if __name__ == "__main__":
    if "--test" in __import__("sys").argv:
        # 90°-kal balra fordult test: a világ x iránya a test -y iránya
        q = (0, 0, math.sin(math.pi / 4), math.cos(math.pi / 4))
        r = quat_rotate_inv(q, (1, 0, 0))
        assert all(abs(a - b) < 1e-9 for a, b in zip(r, (0, -1, 0))), r
        print("sim_target önellenőrzés: OK")
    else:
        rclpy.init()
        rclpy.spin(SimTarget())
