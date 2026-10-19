"""HyperDog szimuláció böngészős vezérlőpultja (gamepad helyett).

Egyetlen ROS2 node 10 Hz-en küldi a /hyperdog_joy_ctrl_cmd üzenetet, ugyanazt,
amit a teleop a gamepadről. Az állapotot a weboldal gombjai és csúszkái állítják.
Indítás a konténerben: python3 hd_web.py   ->   http://<gép>:6081
"""
import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import rclpy
from hyperdog_msgs.msg import JoyCtrlCmds

state = {"start": False, "walk": False, "side": False, "height": 150.0,
         "roll": 0.0, "pitch": 0.0, "yaw": 0.0, "step_x": 0.0, "step_y": 0.0, "swing": 40.0, "gait": 1}

PAGE = """<!doctype html><html lang=hu><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>HyperDog vezérlő</title>
<style>body{font:16px system-ui;margin:16px;max-width:480px;background:#f4f4f4;color:#222}
button{font:inherit;padding:10px 14px;margin:4px 2px;border:1px solid #888;border-radius:6px;background:#fff}
button:active{background:#ddd}label{display:block;margin-top:12px}input{width:100%}
#st{font:13px monospace;white-space:pre;margin-top:16px;color:#555}</style>
<h2>HyperDog vezérlő</h2>
<p>Billentyűk (nyomva tartva): <b>W/S</b> előre/hátra, <b>A/D</b> oldalazás, <b>Q/E</b> fordulás,
<b>szóköz</b> megáll, <b>F</b> felállás, <b>R</b> reset. Ehhez ez a fül legyen aktív.</p>
<button onclick="s({start:1,walk:0})">Felállás</button><button onclick="s({start:0,walk:0})">Leül</button>
<button onclick="s({walk:0,side:0,step_x:0,step_y:0})">Megáll</button><button onclick="fetch('/reset')">Világ reset</button><br>
<button onclick="s({start:1,walk:1,side:0,step_x:40,step_y:0})">Előre</button><button onclick="s({start:1,walk:1,side:0,step_x:-40,step_y:0})">Hátra</button>
<button onclick="s({start:1,walk:1,side:0,step_x:0,step_y:-30})">Balra</button><button onclick="s({start:1,walk:1,side:0,step_x:0,step_y:30})">Jobbra</button><br>
<button onclick="s({start:1,walk:1,side:1,step_x:0,step_y:-30})">Fordul balra</button><button onclick="s({start:1,walk:1,side:1,step_x:0,step_y:30})">Fordul jobbra</button>
<button onclick="s({start:1,walk:1,step_x:0,step_y:0})">Helyben lép</button>
<label>Járásmód <select onchange="s({gait:this.value})"><option value=1>1 trot</option><option value=2>2 wave gait</option><option value=3>3 gyors trot</option><option value=0>0 pacsi (lefagyasztja a cmd_managert!)</option></select></label>
<label>Magasság (mm) <b id=v_height></b><input type=range id=height min=80 max=240 step=5></label>
<label>Roll (°) <b id=v_roll></b><input type=range id=roll min=-45 max=45></label>
<label>Pitch (°) <b id=v_pitch></b><input type=range id=pitch min=-40 max=40></label>
<label>Yaw (°) <b id=v_yaw></b><input type=range id=yaw min=-50 max=50></label>
<button onclick="s({roll:0,pitch:0,yaw:0})">Dőlés nullázása</button>
<div id=st></div>
<script>
const K=['height','roll','pitch','yaw'];
function show(j){K.forEach(k=>{document.getElementById(k).value=j[k];document.getElementById('v_'+k).textContent=j[k]});
 document.getElementById('st').textContent=JSON.stringify(j,null,1)}
function s(o){fetch('/set?'+new URLSearchParams(o)).then(r=>r.json()).then(show)}
K.forEach(k=>document.getElementById(k).oninput=e=>s({[k]:e.target.value}));
// billentyűzet: nyomva tartva megy, felengedve megáll
const KEYS={w:{walk:1,side:0,step_x:40,step_y:0},s:{walk:1,side:0,step_x:-40,step_y:0},
 a:{walk:1,side:0,step_x:0,step_y:-30},d:{walk:1,side:0,step_x:0,step_y:30},
 q:{walk:1,side:1,step_x:0,step_y:-30},e:{walk:1,side:1,step_x:0,step_y:30}};
onkeydown=ev=>{const k=ev.key.toLowerCase();if(ev.repeat)return;
 if(KEYS[k])s({start:1,...KEYS[k]});else if(k==' ')s({walk:0});else if(k=='f')s({start:1,walk:0});
 else if(k=='r')fetch('/reset')};
onkeyup=ev=>{const k=ev.key.toLowerCase();if('wsadqe'.includes(k))s({walk:0,side:0,step_x:0,step_y:0})};
fetch('/state').then(r=>r.json()).then(show);
</script></html>"""


def to_msg():
    m = JoyCtrlCmds()
    m.states = [state["start"], state["walk"], state["side"]]
    m.gait_type = int(state["gait"])  # 0 = "pacsi" (give_hand), 1 = trot, 2 = wave gait, 3 = gyors trot
    m.pose.position.z = state["height"]
    m.pose.orientation.x, m.pose.orientation.y, m.pose.orientation.z = state["roll"], state["pitch"], state["yaw"]
    m.gait_step.x, m.gait_step.y, m.gait_step.z = state["step_x"], state["step_y"], state["swing"]
    return m


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, body, ctype="application/json"):
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/set":
            for k, v in parse_qs(url.query).items():
                if k in ("start", "walk", "side"):
                    state[k] = v[0] in ("1", "true")
                elif k in state:
                    state[k] = float(v[0])
            subprocess.Popen(["gz", "world", "-p", "0"])  # ha a GUI-ban szünetelt
        elif url.path == "/reset":
            state.update(start=False, walk=False, roll=0.0, pitch=0.0, yaw=0.0, step_x=0.0, step_y=0.0)
            # gz world -r a ros2_control mellett nem teszi vissza a modellt, ezért közvetlenül
            subprocess.Popen(["gz", "model", "-m", "HyperDog", "-x", "0", "-y", "0", "-z", "0.18",
                              "-R", "0", "-P", "0", "-Y", "0"])
            subprocess.Popen(["gz", "camera", "-c", "gzclient_camera", "-f", "HyperDog"])
        elif url.path != "/state":
            return self.reply(PAGE, "text/html")
        self.reply(json.dumps(state))


def main():
    rclpy.init()
    node = rclpy.create_node("hd_web")
    pub = node.create_publisher(JoyCtrlCmds, "hyperdog_joy_ctrl_cmd", 10)
    node.create_timer(0.1, lambda: pub.publish(to_msg()))
    threading.Timer(20, subprocess.Popen, [["gz", "camera", "-c", "gzclient_camera", "-f", "HyperDog"]]).start()  # kamera követi a robotot
    threading.Thread(target=ThreadingHTTPServer(("0.0.0.0", 6081), Handler).serve_forever, daemon=True).start()
    rclpy.spin(node)


if __name__ == "__main__":
    main()
