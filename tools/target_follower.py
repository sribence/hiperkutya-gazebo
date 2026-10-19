"""Célkövetés: a robot teste a kapott célpont felé fordul (yaw) és fel/le néz (pitch).

Bemenet:
  /target_point  geometry_msgs/PointStamped   a cél helyzete méterben, a robot testéhez rögzítve
                 (frame "base_link": x előre, y balra, z fel, origó a test közepe).
                 Ha nincs cél, a küldő egyszerűen nem küld. A formátum leírása: docs/CELKOVETES.md
  /teleop_cmd    hyperdog_msgs/JoyCtrlCmds    a gamepad / webes pult parancsa (ide kell átirányítani)
Kimenet:
  /hyperdog_joy_ctrl_cmd                      ugyanaz a parancs, a test yaw/pitch-e felülírva

A node a teleop és a cmd_manager közé ül: amíg van friss cél, a test a cél felé néz,
minden mást (felállás, járás, magasság) továbbra is a gamepad / pult ad. Csak álló, felállt
robotnál fordít, a felállás után settle s-mal; járás közben és ülve a pult/gamepad yaw-ját és
pitch-ét engedi át, és közben nem gyűjti a hibát (különben bekapcsoláskor a határra ugrana).

A bemenetet nem hiszi el vakon: eldobja a nem véges, a túl közeli / távoli, a robot mögötti
és a túl régi pontot, a parancsot szög- és sebességhatárral korlátozza. Ha nincs friss cél,
lost_hold s-ig tart, utána lassan visszaáll egyenesbe.

Paraméterek (--ros-args -p nev:=ertek):
  gain            1/s: a szöghiba ennyi-szeresét javítja másodpercenként (3 = kb. 0,5 s alatt beáll)
  yaw_sign, pitch_sign   +1 / -1: a parancs előjele. Gazebóban mérve: +yaw jobbra, +pitch felfelé
                  fordít, ezért yaw_sign = -1, pitch_sign = +1. A valódi roboton EGYSZER ellenőrizni kell.
  max_yaw, max_pitch     fokban. 150 mm testmagasságnál a javított IK (fixes/apply_fixes.sh 8.)
                  yaw ±30 mellett pitch -10..+5 fokig mindent elér; ezen túl egyes lábak nem érnek
                  le, ilyenkor az IK az előző testhelyzetet tartja. Ezért 30 / 10 az alap.
  max_rate        legfeljebb ennyi fok/s-mal fordul
  min_dist, max_dist     m: ennél közelebbi / távolabbi pontot eldob
  max_age         s: ennél régebbi időbélyegű pontot eldob (0 = nem nézi)
  lost_hold       s: cél nélkül ennyi ideig tartja az irányt, utána visszaáll egyenesbe
  settle          s: felállás után ennyit vár, mielőtt követni kezd
Önellenőrzés ROS nélkül:  python3 target_follower.py --test
"""
import math
import sys


def point_to_angles(x, y, z):
    """A cél iránya fokban: yaw (+ = balra), pitch (+ = felfelé)."""
    return math.degrees(math.atan2(y, x)), math.degrees(math.atan2(z, math.hypot(x, y)))


def valid_point(x, y, z, min_dist, max_dist):
    """Használható-e a pont: véges, előttünk van, és ésszerű távolságban."""
    if not all(math.isfinite(v) for v in (x, y, z)):
        return False
    return x > 0 and min_dist <= math.sqrt(x * x + y * y + z * z) <= max_dist


def step(cur, err, sign, gain_dt, limit, max_delta):
    """Egy szabályozási lépés: a hiba gain·dt-szeresét lépi, szög- és sebességhatárral."""
    target = max(-limit, min(limit, cur + sign * gain_dt * err))
    return cur + max(-max_delta, min(max_delta, target - cur))


def selftest():
    assert point_to_angles(1, 0, 0) == (0, 0)
    yaw, pitch = point_to_angles(1, 1, 0)
    assert abs(yaw - 45) < 1e-9 and pitch == 0
    yaw, pitch = point_to_angles(1, 0, -1)
    assert yaw == 0 and abs(pitch + 45) < 1e-9
    assert valid_point(1.0, 0.2, 0.1, 0.3, 5)
    assert not valid_point(float("nan"), 0, 0, 0.3, 5)
    assert not valid_point(-1.0, 0, 0, 0.3, 5)       # mögöttünk
    assert not valid_point(0.1, 0, 0, 0.3, 5)        # túl közel
    assert not valid_point(9.0, 0, 0, 0.3, 5)        # túl messze
    # zárt hurok: a cél 25°-ra balra, a test fordul, a hiba a fordulással csökken
    cmd, real = 0.0, 0.0
    for _ in range(100):
        err = 25 - real
        cmd = step(cmd, err, -1, 3 * 0.05, 30, 90 * 0.05)
        real = -cmd                                   # Gazebo: +parancs = jobbra
    assert abs(real - 25) < 0.5, real
    # határ: 80°-os cél, de 30°-nál megáll
    cmd = 0.0
    for _ in range(200):
        cmd = step(cmd, 80 + cmd, -1, 0.15, 30, 4.5)
    assert cmd == -30, cmd
    print("target_follower önellenőrzés: OK")


def main():
    import rclpy
    from rclpy.node import Node
    from rclpy.time import Time
    from geometry_msgs.msg import PointStamped
    from hyperdog_msgs.msg import JoyCtrlCmds

    class Follower(Node):
        def __init__(self):
            super().__init__("target_follower")
            p = {"gain": 3.0, "yaw_sign": -1.0, "pitch_sign": 1.0, "max_yaw": 30.0, "max_pitch": 10.0,
                 "max_rate": 60.0, "min_dist": 0.3, "max_dist": 5.0, "max_age": 0.5, "lost_hold": 1.0, "settle": 3.0}
            for k, v in p.items():
                self.declare_parameter(k, v)
            self.p = lambda k: self.get_parameter(k).value
            self.yaw = self.pitch = 0.0
            self.last_seen = self.last_step = None
            self.teleop = None
            self.standing_since = None
            self.rejected = 0
            self.pub = self.create_publisher(JoyCtrlCmds, "hyperdog_joy_ctrl_cmd", 10)
            self.create_subscription(PointStamped, "target_point", self.on_point, 10)
            self.create_subscription(JoyCtrlCmds, "teleop_cmd", self.on_teleop, 10)
            self.create_timer(0.05, self.tick)
            self.create_timer(5.0, self.report)

        def now(self):
            return self.get_clock().now().nanoseconds / 1e9

        def on_teleop(self, msg):
            self.teleop = msg
            standing = msg.states[0] and not msg.states[1]
            if not standing:
                self.standing_since = None
                self.yaw = self.pitch = 0.0
            elif self.standing_since is None:
                self.standing_since = self.now()

        def active(self):
            return self.standing_since is not None and self.now() - self.standing_since >= self.p("settle")

        def on_point(self, msg):
            if not self.active():
                return
            x, y, z = msg.point.x, msg.point.y, msg.point.z
            now = self.now()
            stamp = Time.from_msg(msg.header.stamp).nanoseconds / 1e9
            too_old = self.p("max_age") > 0 and stamp > 0 and now - stamp > self.p("max_age")
            if too_old or not valid_point(x, y, z, self.p("min_dist"), self.p("max_dist")):
                self.rejected += 1
                return
            dt = 0.0 if self.last_step is None else min(now - self.last_step, 0.2)
            self.last_step = self.last_seen = now
            eyaw, epitch = point_to_angles(x, y, z)
            md = self.p("max_rate") * dt
            self.yaw = step(self.yaw, eyaw, self.p("yaw_sign"), self.p("gain") * dt, self.p("max_yaw"), md)
            self.pitch = step(self.pitch, epitch, self.p("pitch_sign"), self.p("gain") * dt, self.p("max_pitch"), md)

        def tick(self):
            if self.teleop is None:
                return                          # amíg a pult/gamepad nem küld, mi sem
            m = self.teleop
            lost = self.last_seen is None or self.now() - self.last_seen > self.p("lost_hold")
            if lost:                            # nincs friss cél: lassan vissza egyenesbe
                self.yaw *= 0.95
                self.pitch *= 0.95
                self.last_step = None
            if self.active() and (not lost or abs(self.yaw) > 0.5 or abs(self.pitch) > 0.5):
                m.pose.orientation.z = float(self.yaw)
                m.pose.orientation.y = float(self.pitch)
            self.pub.publish(m)

        def report(self):
            if self.rejected:
                self.get_logger().warn(f"{self.rejected} célpont eldobva az utolsó 5 s-ban (lásd docs/CELKOVETES.md)")
                self.rejected = 0

    rclpy.init()
    rclpy.spin(Follower())


if __name__ == "__main__":
    selftest() if "--test" in sys.argv else main()
