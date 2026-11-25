"""
ALEX robot receiver - sample code for a Raspberry Pi (or any PC) inside your robot.

ALEX sends every avatar action here as JSON, e.g. {"action":"punch","t":1700000000000}
or {"mode":"danger","t":...}. Fill in the functions below with your real motor / servo code.

Setup on the Pi:   pip install flask
Run:               python robot_receiver.py
In ALEX say:       robot connect http://<pi-ip>:8000/action
(To stop:          robot off)
"""
import json
from flask import Flask, request

app = Flask(__name__)


# ---- put your hardware code here (gpiozero / pigpio / serial to Arduino ...) ----
def punch():      print("ROBOT: punch   -> move arm servo forward")
def kick():       print("ROBOT: kick    -> move leg servo")
def blast():      print("ROBOT: blast   -> LEDs / relay on")
def shield():     print("ROBOT: shield  -> cross arms")
def wave():       print("ROBOT: wave    -> raise and wave arm")
def jump():       print("ROBOT: jump    -> (needs a strong mechanism!)")
def stop_all():   print("ROBOT: stop")


ACTIONS = {"punch": punch, "kick": kick, "blast": blast, "shield": shield,
           "wave": wave, "jump": jump}


def on_mode(mode):
    print("ROBOT: mode ->", mode)
    if mode == "danger":
        print("ROBOT: danger lights ON")   # e.g. red LED + buzzer


@app.route("/action", methods=["POST"])
def action():
    # ALEX sends the body as plain text JSON (no CORS needed)
    data = json.loads(request.get_data(as_text=True) or "{}")
    if "action" in data:
        ACTIONS.get(data["action"], lambda: print("ROBOT: unknown action", data["action"]))()
    if "mode" in data:
        on_mode(data["mode"])
    return "ok"


if __name__ == "__main__":
    # Keep this on your own WiFi only. It has no password.
    app.run(host="0.0.0.0", port=8000)
