ALEX - COMPLETE PACKAGE
=======================

FILES
  app.py                 The ALEX server (brain, voice, memory, laptop control, phone call).
  script.js              The ALEX page logic (avatar, JARVIS, skills, maps, languages, agent...).
  index.html             The ALEX page (has a safety banner if the script fails to start).
  style.css              Your original design (unchanged).
  START_ALEX.bat         Starts ALEX on this PC and opens it.
  START_ALEX_PHONE.bat   Starts ALEX so your phone can open it (same WiFi, HTTPS).
  requirements.txt       Python packages.      env.example   Template for your .env file.
  PHONE_CALL_SETUP.txt   How to call ALEX on a real phone call (optional, costs money).
  robot_receiver.py      Sample code for a physical robot (Raspberry Pi).
  alex_android/          Android app project (build the APK, see below).
  Keep your own: .env, alex_memory.db, background picture, models folder.

FIRST TIME SETUP
  1. Install Python 3.10+.   2. In this folder:  pip install -r requirements.txt
  3. Copy env.example to a file named .env and fill GROQ_API_KEY, ALEX_PASSWORD, FLASK_SECRET_KEY.
  4. Double click START_ALEX.bat, log in with ALEX_PASSWORD.
  (Replacing files in an existing ALEX folder: replace app.py, script.js, index.html only.)

PHONE APP (APK)
  The project is in alex_android/. I could not build the APK for you here.
  Option A (no Android Studio): upload the alex_android folder to your own GitHub repository ->
    Actions tab -> "Build ALEX APK" -> download app-debug.apk from Artifacts.
  Option B: open alex_android in Android Studio -> Build > Build APK.
  The app needs your PC running START_ALEX_PHONE.bat. On first start type the PHONE link it prints.
  Allow the permissions (mic, camera, location, contacts, calls, SMS).

LAPTOP CONTROL (Windows)
  .env: ALEX_COMPUTER_CONTROL=true   |  pip install pyautogui  |  turn computer control ON in ALEX
  settings  |  restart app.py. If something is off, ALEX tells you which one.

THINGS TO SAY (Hindi / English / Hinglish)
  Avatar:     "show avatar", "Jarvis, status report", "alex se baat karni hai", "suit up",
              "hide avatar", "transform", modes: normal, danger, fighting, virus, scanning, power.
  Skills:     punch, kick, uppercut, roundhouse, slash, blast, beam, shield, dodge, jump, flip,
              slam, fly, combo, stance, charge, salute, victory, roar, wave, nod, dance.
  Danger:     "mujhe khatra hai", "bachao"  -> avatar opens + 112 / 108 / 100 links + location.
  Laptop:     "chrome kholo", "youtube par <gaana> play karo", "notepad kholo aur hello likho",
              "volume badhao", "screenshot lo", "laptop lock karo".
  Maps:       "meri location", "Delhi ka route", "nearest hospital", "map par <jagah> dikhao".
  Camera:     "ye kya hai", "samne kya hai", "awareness on/off".
  Build:      "ek todo app banao", "mera project complete karo"  (download link in chat).
  Voice:      "meri awaaz yaad karo", "ladki ki awaaz", "demon voice on", "jarvis voice".
  Language:   "gujarati mein baat karo", "speak tamil", "english mode".
  Robot:      "robot connect http://<pi-ip>:8000/action", "robot off".
  Phone:      "mujhe call karo" (needs phone setup).    News: "aaj ki khabrein", "cricket news".

SAFETY
  - Choose a strong ALEX_PASSWORD. In phone mode your server is open on your WiFi.
  - Never share .env. Camera pictures go to the AI service for analysis. Voice recognition of the
    owner is basic (stored only in your browser) and is NOT a security lock.
  - ALEX is not a replacement for emergency services. In real danger call 112.

TROUBLESHOOTING
  Page stuck on CONNECTING: press Ctrl+Shift+R; the red bar at the bottom shows the error.
  Port busy: close old ALEX windows. Check http://127.0.0.1:5000/health shows "running".
