"""Gamepad nélküli teszt: Xbox-kiosztású gamepad szimulálása a /joy topicon, a teleop kimenetének kiírásával.

Végigjátssza a járáshoz szükséges sorrendet (Start, test fel, LB + d-pad fel, B, Back, jobb bot).
Futtatás: python3 gamepad_teszt.py   (a joy_node helyett, a hyperdog_teleop_joy_node mellett)
"""
import threading
import time
import rclpy
from sensor_msgs.msg import Joy
from hyperdog_msgs.msg import JoyCtrlCmds

rclpy.init()
n = rclpy.create_node("fake_joy")
pub = n.create_publisher(Joy, "joy", 10)
last = [None]
t0 = time.time()


def on_cmd(m):
    k = (list(m.states), m.gait_type, round(m.pose.position.z), round(m.gait_step.x), round(m.gait_step.z))
    if k != last[0]:
        print(f"{time.time()-t0:5.1f}s states={k[0]} gait={k[1]} z={k[2]} step_x={k[3]} swing={k[4]}", flush=True)
        last[0] = k


n.create_subscription(JoyCtrlCmds, "hyperdog_joy_ctrl_cmd", on_cmd, 10)
threading.Thread(target=rclpy.spin, args=(n,), daemon=True).start()


def send(sec, buttons=(), axes=None, label=""):
    if label:
        print(f"{time.time()-t0:5.1f}s >> {label}", flush=True)
    end = time.time() + sec
    while time.time() < end:
        m = Joy()
        m.axes = axes or [0.0] * 8
        m.buttons = [1 if i in buttons else 0 for i in range(11)]
        pub.publish(m)
        time.sleep(0.05)


send(2)
send(0.3, {7}, label="Start"); send(4)
send(0.6, axes=[0.0] * 7 + [1.0], label="d-pad fel"); send(1)
send(0.4, {4}, axes=[0.0] * 7 + [1.0], label="LB + d-pad fel"); send(1)
send(0.3, {1}, label="B"); send(1)
send(0.3, {6}, label="Back"); send(1)
send(10, axes=[0.0, 0.0, 0.0, 0.0, 0.2, 0.0, 0.0, 0.0], label="jobb bot elore 20%")
send(1, label="elengedve")
