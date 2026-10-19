"""Erőalapú ízületvezérlés a HyperDog Gazebo-szimulációhoz.

A gyári híd a szöget közvetlenül pozícióként küldi, a Gazebo pedig "teleportálja"
a csuklót, ezért a talpak csúsznak. Ez a node szervóként viselkedik: PD-szabályzóval
nyomatékot számol, és azt küldi az effort-controllernek.

  be:  /hyperdog_jointController/commands  (Float32MultiArray, 12 szög fokban, IK-sorrend)
       /joint_states                        (mért szög és szögsebesség)
  ki:  /gazebo_joint_controller/commands   (Float64MultiArray, 12 nyomaték, Nm)

Erősítések futás közben is állíthatók: ros2 param set /pd_bridge kp 40.0
Önellenőrzés ROS nélkül: python3 pd_bridge.py --test
"""
import math
import sys

JOINTS = [f"{leg}_{part}_joint" for leg in ("FR", "FL", "BR", "BL") for part in ("hip", "uleg", "lleg")]


def pd(target, pos, vel, kp, kd, limit):
    """Egy ízület nyomatéka: rugó a célszög felé, csillapítás a sebességre, korlátozva."""
    tau = kp * (target - pos) - kd * vel
    return max(-limit, min(limit, tau))


def demo():
    assert pd(1.0, 1.0, 0.0, 30, 0.5, 10) == 0.0          # célban nincs nyomaték
    assert pd(1.0, 0.9, 0.0, 30, 0.5, 10) > 0             # lemarad: tol előre
    assert pd(0.0, 0.0, 2.0, 30, 0.5, 10) == -1.0         # mozog: fékez
    assert pd(10.0, 0.0, 0.0, 30, 0.5, 10) == 10          # korlát
    print("OK")


def main():
    import rclpy
    from rclpy.node import Node
    from sensor_msgs.msg import JointState
    from std_msgs.msg import Float32MultiArray, Float64MultiArray

    class PdBridge(Node):
        def __init__(self):
            super().__init__("pd_bridge")
            self.kp = self.declare_parameter("kp", 30.0)
            self.kd = self.declare_parameter("kd", 0.6)
            self.limit = self.declare_parameter("effort_limit", 10.0)
            self.target = None
            self.pub = self.create_publisher(Float64MultiArray, "gazebo_joint_controller/commands", 10)
            self.create_subscription(Float32MultiArray, "hyperdog_jointController/commands", self.on_cmd, 10)
            self.create_subscription(JointState, "joint_states", self.on_state, 10)

        def on_cmd(self, msg):
            if len(msg.data) == 12:  # az IK induláskor üres tömböt küld
                self.target = [math.radians(a) for a in msg.data]

        def on_state(self, msg):
            if self.target is None:
                return  # amíg nincs parancs, a robot ernyedt (mint kikapcsolt szervó)
            idx = {n: i for i, n in enumerate(msg.name)}
            kp, kd, lim = (p.value for p in (self.kp, self.kd, self.limit))
            out = Float64MultiArray()
            out.data = [pd(self.target[j], msg.position[idx[n]], msg.velocity[idx[n]], kp, kd, lim)
                        for j, n in enumerate(JOINTS)]
            self.pub.publish(out)

    rclpy.init()
    rclpy.spin(PdBridge())


if __name__ == "__main__":
    demo() if "--test" in sys.argv else main()
