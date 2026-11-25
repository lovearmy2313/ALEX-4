# ==================================================
# ALEX PHONE: call your AI on a real phone call and give it tasks
# (Twilio Voice webhooks. Disabled unless every security setting is present.)
# ==================================================
import base64 as _p5b64
import hashlib as _p5hash
import hmac as _p5hmac
import secrets as _p5sec
from urllib.parse import urlsplit as _p5split
from xml.sax.saxutils import escape as _p5esc, quoteattr as _p5q
from flask import Response as _P5Response, abort as _p5_abort

P5_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
P5_SID = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
P5_FROM = os.getenv("TWILIO_NUMBER", "").strip()
P5_PIN = re.sub(r"\D", "", os.getenv("ALEX_PHONE_PIN", ""))
P5_ALLOWED = [re.sub(r"[^\d+]", "", x)
              for x in os.getenv("ALEX_PHONE_ALLOWED", "").split(",") if x.strip()]
P5_PUBLIC = os.getenv("ALEX_PUBLIC_URL", "").strip().rstrip("/")
P5_LANG = os.getenv("ALEX_PHONE_LANG", "hi-IN")
P5_VOICE = os.getenv("ALEX_PHONE_VOICE", "Polly.Aditi")
P5_READY = bool(os.getenv("ALEX_PHONE_ENABLED", "0") == "1" and P5_TOKEN
                and len(P5_PIN) >= 4 and P5_ALLOWED and P5_PUBLIC)
P5_CALLS, P5_ONCE = {}, {}
P5_WEBHOOKS = ("/phone/incoming", "/phone/pin", "/phone/listen")
P5_TASK = re.compile(r"\b(open|kholo|khol|chalao|chala|bajao|baja|play|search|dhundo|dhoondo|"
                     r"google|youtube|chrome|notepad|calculator|word|excel|vscode|folder|file|"
                     r"type|likho|likh|write|close|band karo|volume|mute|screenshot|tab|download|"
                     r"scroll|click|minimize|maximize|copy|paste|save|lock|laptop|computer|pc|"
                     r"desktop|window|spotify|gmail|jao|bhejo|bana|create|new|install)\b", re.I)
P5_NOT = re.compile(r"\b(kaise|kyun|why|how|explain|samjha\w*|what is|kya hai|kaun|meaning|matlab)\b", re.I)
P5_BYE = re.compile(r"\b(bye|goodbye|alvida|call (band|cut|disconnect|end)|phone rakh|rakhta hoon|"
                    r"rakhti hoon|disconnect|that's all|bas itna hi)\b", re.I)


@app.before_request
def p5_guard():
    """Through the public tunnel only the three phone webhooks are reachable."""
    if P5_PUBLIC:
        public_host = _p5split(P5_PUBLIC).netloc.lower()
        if request.host.lower() == public_host and request.path not in P5_WEBHOOKS:
            _p5_abort(404)


def p5_signature_ok():
    """Verify that the request really comes from Twilio (HMAC-SHA1 of URL + sorted params)."""
    url = P5_PUBLIC + request.path
    if request.query_string:
        url += "?" + request.query_string.decode()
    data = url
    for key in sorted(request.form.keys()):
        for value in request.form.getlist(key):
            data += key + value
    digest = _p5hmac.new(P5_TOKEN.encode(), data.encode(), _p5hash.sha1).digest()
    expected = _p5b64.b64encode(digest).decode()
    return _p5hmac.compare_digest(expected, request.headers.get("X-Twilio-Signature", ""))


def p5_xml(body):
    return _P5Response('<?xml version="1.0" encoding="UTF-8"?><Response>' + body + "</Response>",
                       mimetype="text/xml")


def p5_say(text, lang=None):
    return ("<Say voice=%s language=%s>%s</Say>"
            % (_p5q(P5_VOICE), _p5q(lang or P5_LANG), _p5esc(text)))


def p5_gather(prompt, state):
    return ('<Gather input="speech" language=%s speechTimeout="auto" method="POST" '
            'actionOnEmptyResult="true" action=%s>%s</Gather>'
            % (_p5q(state["lang"]), _p5q(P5_PUBLIC + "/phone/listen"), p5_say(prompt, state["lang"])))


def p5_state(sid):
    now = time.time()
    for key in [k for k, v in P5_CALLS.items() if now - v["t0"] > 1800]:
        P5_CALLS.pop(key, None)
    return P5_CALLS.get(sid)


def p5_gate():
    """Common checks for every webhook. Returns an error response or None."""
    if not P5_READY:
        _p5_abort(404)
    if not p5_signature_ok():
        _p5_abort(403)
    return None


@app.route("/phone/incoming", methods=["POST"])
def p5_incoming():
    p5_gate()
    sid = request.form.get("CallSid", "")
    caller = re.sub(r"[^\d+]", "", request.form.get("To" if request.form.get("Direction", "")
                                                   .startswith("outbound") else "From", ""))
    once = P5_ONCE.pop(request.args.get("o", ""), None)
    outbound_ok = bool(once and time.time() - once[1] < 300 and once[0] == caller)
    if not outbound_ok and caller not in P5_ALLOWED:
        return p5_xml(p5_say("Ye number authorized nahi hai. Alvida.", "hi-IN") + "<Hangup/>")
    st = {"auth": outbound_ok, "tries": 0, "empty": 0, "turns": 0, "t0": time.time(),
          "hist": [], "pend": None, "lang": P5_LANG}
    P5_CALLS[sid] = st
    if outbound_ok:
        return p5_xml(p5_gather("Namaste. Main ALEX bol raha hoon. Bataiye, kya kaam karna hai?", st))
    return p5_xml('<Gather input="dtmf" numDigits="%d" timeout="10" method="POST" action=%s>%s</Gather>'
                  % (len(P5_PIN), _p5q(P5_PUBLIC + "/phone/pin"),
                     p5_say("Namaste. Apna pin keypad par dabayein.", "hi-IN")) + "<Hangup/>")


@app.route("/phone/pin", methods=["POST"])
def p5_pin():
    p5_gate()
    st = p5_state(request.form.get("CallSid", ""))
    if not st:
        return p5_xml("<Hangup/>")
    digits = re.sub(r"\D", "", request.form.get("Digits", ""))
    if digits and _p5hmac.compare_digest(digits, P5_PIN):
        st["auth"] = True
        return p5_xml(p5_gather("Pin sahi hai. Main ALEX hoon. Bataiye, kya kaam karna hai?", st))
    st["tries"] += 1
    if st["tries"] >= 3:
        return p5_xml(p5_say("Galat pin. Alvida.", "hi-IN") + "<Hangup/>")
    return p5_xml('<Gather input="dtmf" numDigits="%d" timeout="10" method="POST" action=%s>%s</Gather>'
                  % (len(P5_PIN), _p5q(P5_PUBLIC + "/phone/pin"),
                     p5_say("Galat pin. Dobara dabayein.", "hi-IN")) + "<Hangup/>")


def p5_agent(text, confirm=False):
    with app.test_request_context("/plus/agent", method="POST",
                                  json={"task": text, "confirm": confirm}):
        session["authenticated"] = True
        res = p4_agent()
        if isinstance(res, tuple):
            res = res[0]
        return res.get_json() or {}


def p5_think(text, st):
    if st["pend"]:
        task, st["pend"] = st["pend"], None
        if re.search(r"\b(haan|han|yes|kar do|kardo|ok|chalao)\b", text, re.I):
            r = p5_agent(task, True)
            return (r.get("say") or "Ho gaya.") + (" " + r["hint"] if r.get("hint") else "")
        return "Theek hai, cancel kar diya."
    if re.search(r"\b(english|angrezi)\b", text, re.I) and re.search(r"\b(mein|mode|speak)\b", text, re.I):
        st["lang"] = "en-IN"
        return "Okay, I will speak English now."
    if re.search(r"\bhindi\b", text, re.I) and re.search(r"\b(mein|mode|bolo)\b", text, re.I):
        st["lang"] = "hi-IN"
        return "Theek hai, ab Hindi mein baat karte hain."
    if P5_TASK.search(text) and not P5_NOT.search(text) and len(text.split()) >= 2:
        r = p5_agent(text)
        if r.get("needs_confirm"):
            st["pend"] = text
            return (r.get("say") or "Ye kaam sensitive hai.") + " Haan bolein to kar dun?"
        if r.get("handled"):
            return (r.get("say") or "Ho gaya.") + (" " + r["hint"] if r.get("hint") else "")
    ctx = ("PHONE CALL: the user is speaking to you on a phone call. Reply in at most 2 short spoken "
           "sentences, no lists, no markdown, no emojis, in the user's language.")
    reply = ask_groq(text, st["hist"], ctx)
    st["hist"] = (st["hist"] + [{"role": "user", "content": text},
                                {"role": "assistant", "content": reply}])[-8:]
    threading.Thread(target=background_learning_worker, args=(text, reply), daemon=True).start()
    return reply


@app.route("/phone/listen", methods=["POST"])
def p5_listen():
    p5_gate()
    st = p5_state(request.form.get("CallSid", ""))
    if not st or not st["auth"]:
        return p5_xml(p5_say("Pehle pin dena zaroori hai.", "hi-IN") + "<Hangup/>")
    if st["turns"] >= 40 or time.time() - st["t0"] > 600:
        return p5_xml(p5_say("Call ka time khatam. Alvida.", st["lang"]) + "<Hangup/>")
    text = request.form.get("SpeechResult", "").strip()
    if not text:
        st["empty"] += 1
        if st["empty"] >= 2:
            return p5_xml(p5_say("Koi awaaz nahi aayi. Alvida.", st["lang"]) + "<Hangup/>")
        return p5_xml(p5_gather("Mujhe sunayi nahi diya. Dobara bolein.", st))
    st["empty"], st["turns"] = 0, st["turns"] + 1
    if P5_BYE.search(text):
        return p5_xml(p5_say("Theek hai. Dhyan rakhiye. Alvida.", st["lang"]) + "<Hangup/>")
    try:
        reply = p5_think(text, st)
    except Exception as error:
        print("Phone call error:", error)
        reply = "Maaf kijiye, kuch gadbad ho gayi."
    reply = re.sub(r"[*_#`>]", "", str(reply)).strip()[:480] or "Theek hai."
    return p5_xml(p5_gather(reply, st))


@app.route("/phone/callme", methods=["POST"])
@login_required
def p5_callme():
    if not (P5_READY and P5_SID and P5_FROM):
        return jsonify({"success": False, "error": "Phone calling is not set up. See PHONE_CALL_SETUP.txt."}), 400
    to = P5_ALLOWED[0]
    tok = _p5sec.token_urlsafe(12)
    P5_ONCE[tok] = (to, time.time())
    try:
        r = requests.post("https://api.twilio.com/2010-04-01/Accounts/%s/Calls.json" % P5_SID,
                          data={"To": to, "From": P5_FROM, "Url": P5_PUBLIC + "/phone/incoming?o=" + tok},
                          auth=(P5_SID, P5_TOKEN), timeout=10)
        ok = r.status_code in (200, 201)
        return jsonify({"success": ok, "error": "" if ok else r.text[:200]})
    except Exception as error:
        return jsonify({"success": False, "error": str(error)[:200]}), 502


@app.route("/phone/status", methods=["GET"])
@login_required
def p5_status():
    missing = [name for name, ok in [
        ("ALEX_PHONE_ENABLED=1", os.getenv("ALEX_PHONE_ENABLED", "0") == "1"),
        ("TWILIO_AUTH_TOKEN", bool(P5_TOKEN)), ("ALEX_PHONE_PIN (4+ digits)", len(P5_PIN) >= 4),
        ("ALEX_PHONE_ALLOWED", bool(P5_ALLOWED)), ("ALEX_PUBLIC_URL", bool(P5_PUBLIC))] if not ok]
    return jsonify({"success": True, "ready": P5_READY, "missing": missing,
                    "can_call_me": bool(P5_READY and P5_SID and P5_FROM)})
