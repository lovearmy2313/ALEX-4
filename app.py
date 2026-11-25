
import os
import re
import io
import json
import hmac
import base64
import sqlite3
import asyncio
import subprocess
import webbrowser
import threading
import secrets
import ctypes
import shutil
import platform

from pathlib import Path
from datetime import datetime
from urllib.parse import quote_plus
from difflib import SequenceMatcher
from functools import wraps

import requests
import edge_tts
from dotenv import load_dotenv
from flask import Flask, request, jsonify, send_file, session
from flask_cors import CORS
from groq import Groq

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.15
    COMPUTER_CONTROL_AVAILABLE = True
except Exception:
    pyautogui = None
    COMPUTER_CONTROL_AVAILABLE = False

try:
    import psutil
except Exception:
    psutil = None


# ==================================================
# 1. CONFIGURATION
# ==================================================

BASE_DIR = Path(__file__).resolve().parent
# Cloud hosts can mount persistent storage outside the source directory.
DATA_DIR = Path(os.getenv("ALEX_DATA_DIR", str(BASE_DIR))).expanduser().resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
load_dotenv(BASE_DIR / ".env")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
ALEX_PASSWORD = os.getenv("ALEX_PASSWORD", "").strip()

def load_flask_secret_key():
    configured = os.getenv("FLASK_SECRET_KEY", "").strip()

    if configured:
        return configured

    key_file = DATA_DIR / ".alex_flask_secret"

    try:
        if key_file.exists():
            saved = key_file.read_text(encoding="utf-8").strip()

            if len(saved) >= 32:
                return saved

        generated = secrets.token_hex(32)
        key_file.write_text(generated, encoding="utf-8")

        try:
            key_file.chmod(0o600)
        except OSError:
            pass

        return generated

    except OSError:
        print("WARNING: Could not persist Flask secret key.")
        return secrets.token_hex(32)


FLASK_SECRET_KEY = load_flask_secret_key()

ALEX_MODEL_NAME = os.getenv(
    "ALEX_MODEL_NAME",
    "openai/gpt-oss-20b"
).strip()

ALEX_VISION_MODEL = os.getenv(
    "ALEX_VISION_MODEL",
    "qwen/qwen3.8-27b"
).strip()

ALEX_COMPUTER_CONTROL = (
    os.getenv("ALEX_COMPUTER_CONTROL", "false").strip().lower() == "true"
)

ELEVENLABS_API_KEY = os.getenv(
    "ELEVENLABS_API_KEY", ""
).strip()

ELEVENLABS_MALE_VOICE_ID = os.getenv(
    "ELEVENLABS_MALE_VOICE_ID",
    "pNInz6obpgDQGcFmaJgB"
).strip()

ELEVENLABS_FEMALE_VOICE_ID = os.getenv(
    "ELEVENLABS_FEMALE_VOICE_ID",
    "21m00Tcm4TlvDq8ikWAM"
).strip()

ELEVENLABS_MODEL = os.getenv(
    "ELEVENLABS_MODEL",
    "eleven_multilingual_v2"
).strip()

MAX_HISTORY_MESSAGES = 16
MAX_MESSAGE_LENGTH = 5000
MAX_MEMORY_COUNT = 300
MAX_TASK_COUNT = 300

DB_PATH = DATA_DIR / "alex_memory.db"

app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = (
    os.getenv("ALEX_COOKIE_SECURE", "0").strip().lower() in ("1", "true", "yes", "on")
    or bool(os.getenv("RENDER"))
)
app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024

CORS(
    app,
    resources={
        r"/*": {
            "origins": [
                re.compile(r"^http://(127\.0\.0\.1|localhost)(:\d+)?$")
            ]
        }
    },
    supports_credentials=True,
    allow_headers=["Content-Type", "Authorization"],
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
)

client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None


# ==================================================
# 2. PERSONALITY
# ==================================================

SYSTEM_PROMPT = """
You are ALEX, a personal AI assistant running locally
on the user's computer.

PERSONALITY:
- Friendly, intelligent, natural and professional.
- Understand Hindi, English and Hinglish.
- Reply in the same language the user uses.
- Understand Roman Hindi.
- Remember the conversation context.
- Understand follow-up questions.
- Be helpful, patient and accurate.
- Explain technical things in beginner-friendly language.

MEMORY:
- Use supplied user memories when relevant.
- Do not invent memories.
- Do not claim to remember information that is not supplied.
- Respect requests to forget information.

COMPUTER:
- Never claim a computer action was completed unless
  the action was actually performed.
- Never claim access to files or applications without evidence.
- Ask for clarification when a computer instruction is ambiguous.

GENERAL:
- Do not expose API keys, passwords or private secrets.
- Never invent successful actions.
"""


# ==================================================
# 3. DATABASE
# ==================================================

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def table_exists(conn, table_name):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,)
    ).fetchone()

    return row is not None


def get_columns(conn, table_name):
    if not table_exists(conn, table_name):
        return []

    return [
        row["name"]
        for row in conn.execute(
            f"PRAGMA table_info({table_name})"
        ).fetchall()
    ]


def init_db():
    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS alex_learning (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            category TEXT DEFAULT 'general',
            created_at TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS alex_skills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT NOT NULL,
            enabled INTEGER DEFAULT 1,
            created_at TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS alex_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message TEXT NOT NULL,
            rating TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
    """)

    task_columns = get_columns(conn, "tasks")

    if "updated_at" not in task_columns:
        conn.execute("ALTER TABLE tasks ADD COLUMN updated_at TEXT")

    if "completed_at" not in task_columns:
        conn.execute("ALTER TABLE tasks ADD COLUMN completed_at TEXT")

    if table_exists(conn, "memories"):
        old_columns = get_columns(conn, "memories")

        if "content" in old_columns:
            for row in conn.execute("SELECT * FROM memories").fetchall():
                content = str(row["content"] or "").strip()

                if not content:
                    continue

                created = (
                    row["created_at"]
                    if "created_at" in old_columns
                    else datetime.now().isoformat()
                )

                exists = conn.execute(
                    "SELECT id FROM memory WHERE content=? LIMIT 1",
                    (content,)
                ).fetchone()

                if not exists:
                    conn.execute(
                        "INSERT INTO memory(content, created_at) VALUES(?, ?)",
                        (content, created)
                    )

    if table_exists(conn, "alex_settings"):
        old_columns = get_columns(conn, "alex_settings")

        if "setting" in old_columns and "value" in old_columns:
            for row in conn.execute(
                "SELECT setting, value FROM alex_settings"
            ).fetchall():
                conn.execute(
                    "INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)",
                    (row["setting"], row["value"])
                )

    if table_exists(conn, "alex_tasks"):
        old_columns = get_columns(conn, "alex_tasks")

        if "task" in old_columns:
            for row in conn.execute("SELECT * FROM alex_tasks").fetchall():
                task_text = str(row["task"] or "").strip()

                if not task_text:
                    continue

                status = (
                    row["status"]
                    if "status" in old_columns
                    else "pending"
                )

                created = (
                    row["created_at"]
                    if "created_at" in old_columns
                    else datetime.now().isoformat()
                )

                exists = conn.execute(
                    "SELECT id FROM tasks WHERE task=? AND status=? LIMIT 1",
                    (task_text, status)
                ).fetchone()

                if not exists:
                    conn.execute("""
                        INSERT INTO tasks(task, status, created_at, updated_at)
                        VALUES(?, ?, ?, ?)
                    """, (task_text, status, created, created))

    defaults = {
        "voice": "male",
        "auto_memory": "true",
        "auto_learning": "true",
        "auto_tasks": "true",
        "computer_control": "false"
    }

    for key, value in defaults.items():
        conn.execute(
            "INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)",
            (key, value)
        )

    built_in_skills = [
        ("google_search", "Search the internet using Google."),
        ("open_application", "Open an approved local application."),
        ("tell_time", "Tell the current local time."),
        ("battery_status", "Check the computer battery."),
        ("open_website", "Open an approved website.")
    ]

    for name, description in built_in_skills:
        conn.execute("""
            INSERT OR IGNORE INTO alex_skills(
                name, description, enabled, created_at
            )
            VALUES(?, ?, 1, ?)
        """, (name, description, datetime.now().isoformat()))

    conn.commit()
    conn.close()


init_db()


# ==================================================
# 4. SETTINGS HELPERS
# ==================================================

def get_saved_setting(key, default=""):
    conn = get_db()

    row = conn.execute(
        "SELECT value FROM settings WHERE key=?",
        (key,)
    ).fetchone()

    conn.close()

    return row["value"] if row else default


def save_setting(key, value):
    conn = get_db()

    conn.execute(
        "INSERT OR REPLACE INTO settings(key, value) VALUES(?, ?)",
        (key, str(value))
    )

    conn.commit()
    conn.close()


def setting_enabled(key, default=True):
    fallback = "true" if default else "false"
    value = str(get_saved_setting(key, fallback)).strip().lower()

    return value in ("true", "1", "yes", "on")


def parse_bool(value, default=None):
    if isinstance(value, bool):
        return value

    if isinstance(value, int) and value in (0, 1):
        return bool(value)

    if isinstance(value, str):
        normalized = value.strip().lower()

        if normalized in ("true", "1", "yes", "on", "enabled"):
            return True

        if normalized in ("false", "0", "no", "off", "disabled"):
            return False

    return default


# ==================================================
# 5. AUTHENTICATION
# ==================================================

def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not session.get("authenticated"):
            return jsonify({
                "success": False,
                "error": "Please login first."
            }), 401

        return func(*args, **kwargs)

    return wrapper


@app.route("/login", methods=["POST"])
def login():
    if not ALEX_PASSWORD:
        return jsonify({
            "success": False,
            "error": "ALEX_PASSWORD is missing in .env."
        }), 500

    data = request.get_json(silent=True) or {}
    password = str(data.get("password", ""))

    if hmac.compare_digest(password, ALEX_PASSWORD):
        session.clear()
        session["authenticated"] = True
        session["voice"] = get_saved_setting("voice", "male")

        return jsonify({
            "success": True,
            "message": "Welcome to ALEX.",
            "voice": session["voice"]
        })

    return jsonify({
        "success": False,
        "error": "Incorrect password."
    }), 401


@app.route("/session", methods=["GET"])
def check_session():
    return jsonify({
        "authenticated": bool(session.get("authenticated")),
        "voice": session.get("voice", "male")
    })


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"success": True})


@app.route("/set-voice", methods=["POST"])
@login_required
def set_voice():
    data = request.get_json(silent=True) or {}
    voice = str(data.get("voice", "male")).lower().strip()

    if voice not in ("male", "female"):
        return jsonify({
            "success": False,
            "error": "Voice must be male or female."
        }), 400

    session["voice"] = voice
    save_setting("voice", voice)

    return jsonify({
        "success": True,
        "voice": voice
    })


# ==================================================
# 6. VOICE SYSTEM - UPDATED
# ==================================================

def normalize_voice(voice):
    voice = str(voice or "male").strip().lower()

    if voice not in ("male", "female"):
        return "male"

    return voice


def edge_voice_name(voice):
    voice = normalize_voice(voice)

    return (
        "hi-IN-SwaraNeural"
        if voice == "female"
        else "hi-IN-MadhurNeural"
    )


def elevenlabs_voice_id(voice):
    voice = normalize_voice(voice)

    return (
        ELEVENLABS_FEMALE_VOICE_ID
        if voice == "female"
        else ELEVENLABS_MALE_VOICE_ID
    )


def elevenlabs_speech(text, voice):
    if not ELEVENLABS_API_KEY:
        raise RuntimeError("ElevenLabs API key is not configured.")

    url = (
        "https://api.elevenlabs.io/v1/text-to-speech/"
        + elevenlabs_voice_id(voice)
    )

    response = requests.post(
        url,
        headers={
            "xi-api-key": ELEVENLABS_API_KEY,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg"
        },
        json={
            "text": text,
            "model_id": ELEVENLABS_MODEL,
            "voice_settings": {
                "stability": 0.50,
                "similarity_boost": 0.75,
                "style": 0.20,
                "use_speaker_boost": True
            }
        },
        timeout=60
    )

    if response.status_code != 200:
        raise RuntimeError(
            "ElevenLabs error "
            + str(response.status_code)
            + ": "
            + response.text[:500]
        )

    if not response.content:
        raise RuntimeError("ElevenLabs returned empty audio.")

    return response.content


async def edge_speech(text, voice):
    _name = edge_voice_name(voice)
    _kw = {}
    if normalize_voice(voice) == "female":
        # lovely, natural Indian female voice (Hinglish in Roman script reads best with Neerja)
        if not re.search(r"[\u0900-\u097F]", text):
            _name = "en-IN-NeerjaNeural"
        _kw = {"rate": os.getenv("ALEX_FEMALE_RATE", "-3%"),
               "pitch": os.getenv("ALEX_FEMALE_PITCH", "+2Hz")}
    communicate = edge_tts.Communicate(text, _name, **_kw)

    audio = bytearray()

    async for chunk in communicate.stream():
        if chunk.get("type") == "audio":
            audio.extend(chunk.get("data", b""))

    audio_data = bytes(audio)

    if not audio_data:
        raise RuntimeError("Edge TTS returned empty audio.")

    return audio_data


def create_voice_response(audio_data, voice, provider):
    if not audio_data:
        raise RuntimeError("Audio data is empty.")

    encoded_audio = base64.b64encode(
        audio_data
    ).decode("utf-8")

    response = jsonify({
        "success": True,
        "audio": encoded_audio,
        "voice": voice,
        "provider": provider,
        "mime_type": "audio/mpeg"
    })

    response.headers["Cache-Control"] = "no-store"

    return response


@app.route("/speak", methods=["POST"])
@login_required
def speak():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({
            "success": False,
            "error": "A valid JSON request is required."
        }), 400

    text = str(data.get("text", "")).strip()

    if not text:
        return jsonify({
            "success": False,
            "error": "Text is required."
        }), 400

    if len(text) > 5000:
        return jsonify({
            "success": False,
            "error": "Text is too long. Maximum 5000 characters."
        }), 400

    voice = normalize_voice(
        data.get("voice", session.get("voice", "male"))
    )

    session["voice"] = voice

    if ELEVENLABS_API_KEY:
        try:
            audio_data = elevenlabs_speech(text, voice)

            print("ALEX Voice: ElevenLabs")

            return create_voice_response(
                audio_data,
                voice,
                "elevenlabs"
            )

        except Exception as error:
            print("ElevenLabs failed:", error)
            print("ALEX Voice: Switching to Edge TTS...")

    try:
        audio_data = asyncio.run(
            edge_speech(text, voice)
        )

        print("ALEX Voice: Edge TTS")

        return create_voice_response(
            audio_data,
            voice,
            "edge-tts"
        )

    except Exception as error:
        print("Edge TTS failed:", error)

        return jsonify({
            "success": False,
            "error": "Voice generation failed.",
            "details": str(error),
            "voice": voice
        }), 500


# ==================================================
# 7. MEMORY SYSTEM
# ==================================================

SENSITIVE_PATTERNS = [
    r"password", r"passwd", r"api[\s_-]?key",
    r"secret[\s_-]?key", r"access[\s_-]?token",
    r"refresh[\s_-]?token", r"\botp\b",
    r"\bcvv\b", r"credit[\s_-]?card",
    r"debit[\s_-]?card"
]


def is_sensitive_memory(text):
    lower = text.lower()

    return any(
        re.search(pattern, lower)
        for pattern in SENSITIVE_PATTERNS
    )


def save_memory(content):
    content = re.sub(r"\s+", " ", str(content)).strip()

    if not content or len(content) > 500:
        return False

    if is_sensitive_memory(content):
        return False

    conn = get_db()

    exists = conn.execute(
        "SELECT id FROM memory WHERE LOWER(content)=LOWER(?)",
        (content,)
    ).fetchone()

    if exists:
        conn.close()
        return False

    count = conn.execute(
        "SELECT COUNT(*) AS total FROM memory"
    ).fetchone()["total"]

    if count >= MAX_MEMORY_COUNT:
        oldest = conn.execute(
            "SELECT id FROM memory ORDER BY id ASC LIMIT 1"
        ).fetchone()

        if oldest:
            conn.execute(
                "DELETE FROM memory WHERE id=?",
                (oldest["id"],)
            )

    conn.execute(
        "INSERT INTO memory(content, created_at) VALUES(?, ?)",
        (content, datetime.now().isoformat())
    )

    conn.commit()
    conn.close()

    return True


def get_alex_memories(limit=100):
    conn = get_db()

    rows = conn.execute(
        "SELECT * FROM memory ORDER BY id DESC LIMIT ?",
        (limit,)
    ).fetchall()

    conn.close()

    return [dict(row) for row in rows]


def get_memory_words(text):
    stop_words = {
        "the", "and", "for", "with", "that", "this",
        "have", "from", "your", "you", "are", "was",
        "were", "will", "want", "about", "what", "when",
        "where", "hai", "hain", "ka", "ki", "ke", "ko",
        "se", "me", "mera", "meri", "mere", "aur", "ho",
        "kya", "mujhe", "tum", "aap", "main"
    }

    words = re.findall(r"[a-zA-Z0-9]+", text.lower())

    return {
        word for word in words
        if len(word) > 2 and word not in stop_words
    }


def get_relevant_memories(query, limit=8):
    query_words = get_memory_words(query)

    if not query_words:
        return []

    scored = []

    for item in get_alex_memories(150):
        content = item["content"]
        memory_words = get_memory_words(content)

        if not memory_words:
            continue

        overlap = len(query_words.intersection(memory_words))

        score = overlap / max(
            1,
            len(query_words.union(memory_words))
        )

        if query_words.issubset(memory_words):
            score += 0.25

        if score > 0:
            scored.append((score, content))

    scored.sort(key=lambda item: item[0], reverse=True)

    return [item[1] for item in scored[:limit]]


def get_memory_context(query=""):
    if query:
        relevant = get_relevant_memories(query)

        if relevant:
            return "\n".join("- " + item for item in relevant)

    memories = get_alex_memories(30)

    return "\n".join(
        "- " + item["content"]
        for item in reversed(memories)
    )


def delete_memory_by_content(query):
    query = str(query).strip()

    if not query:
        return False, "Memory name is required."

    memories = get_alex_memories(200)

    if not memories:
        return False, "No saved memories found."

    best_match = None
    best_score = 0
    query_words = get_memory_words(query)

    for item in memories:
        content = item["content"]

        ratio = SequenceMatcher(
            None,
            query.lower(),
            content.lower()
        ).ratio()

        content_words = get_memory_words(content)

        if query_words and content_words:
            overlap = len(
                query_words.intersection(content_words)
            ) / max(1, len(query_words))

            ratio = max(ratio, overlap)

        if ratio > best_score:
            best_score = ratio
            best_match = item

    if best_match is None or best_score < 0.35:
        return False, "I could not identify that memory."

    conn = get_db()

    conn.execute(
        "DELETE FROM memory WHERE id=?",
        (best_match["id"],)
    )

    conn.commit()
    conn.close()

    return True, "Memory deleted: " + best_match["content"]


def handle_memory_command(message):
    lower = message.lower().strip()

    remember_patterns = [
        "remember that ", "remember ", "save this ",
        "yaad rakhna ", "yaad rakhna ki ",
        "ise yaad rakhna ", "is baat ko yaad rakhna "
    ]

    for prefix in remember_patterns:
        if lower.startswith(prefix):
            content = message[len(prefix):].strip()

            if save_memory(content):
                return True, "I will remember that."

            return True, (
                "I could not save that memory. "
                "It may already exist or contain sensitive information."
            )

    forget_patterns = [
        "forget that ", "forget ", "bhool jao ",
        "bhul jao ", "ise bhool jao "
    ]

    for prefix in forget_patterns:
        if lower.startswith(prefix):
            target = message[len(prefix):].strip()
            _, reply = delete_memory_by_content(target)
            return True, reply

    show_patterns = [
        "show my memories", "show memories",
        "what do you remember", "meri memories dikhao",
        "meri yaadein dikhao",
        "tumhe mere bare mein kya yaad hai"
    ]

    if any(phrase in lower for phrase in show_patterns):
        memories = get_alex_memories(100)

        if not memories:
            return True, "I do not have any saved memories yet."

        reply = "Here is what I remember:\n"

        for index, item in enumerate(memories, 1):
            reply += f"{index}. {item['content']}\n"

        return True, reply

    return False, ""


@app.route("/memory", methods=["GET"])
@login_required
def get_memory():
    return jsonify({
        "success": True,
        "memory": get_alex_memories(300)
    })


@app.route("/memory", methods=["POST"])
@login_required
def add_memory():
    data = request.get_json(silent=True) or {}
    content = str(data.get("content", "")).strip()

    if not content:
        return jsonify({
            "success": False,
            "error": "Memory content is required."
        }), 400

    if not save_memory(content):
        return jsonify({
            "success": False,
            "error": "Memory was not saved. It may be duplicate, invalid or sensitive."
        }), 400

    return jsonify({"success": True, "message": "Memory saved."})


@app.route("/memory", methods=["DELETE"])
@login_required
def delete_memory():
    data = request.get_json(silent=True) or {}
    memory_id = data.get("id")

    if not memory_id:
        return jsonify({
            "success": False,
            "error": "Memory ID is required."
        }), 400

    conn = get_db()

    cursor = conn.execute(
        "DELETE FROM memory WHERE id=?",
        (memory_id,)
    )

    conn.commit()
    conn.close()

    return jsonify({"success": cursor.rowcount > 0})


@app.route("/memory/<int:memory_id>", methods=["DELETE"])
@login_required
def delete_memory_by_id(memory_id):
    conn = get_db()

    cursor = conn.execute(
        "DELETE FROM memory WHERE id=?",
        (memory_id,)
    )

    conn.commit()
    conn.close()

    return jsonify({"success": cursor.rowcount > 0})


@app.route("/memory/settings", methods=["GET", "POST"])
@login_required
def memory_settings():
    if request.method == "GET":
        return jsonify({
            "success": True,
            "auto_memory": setting_enabled("auto_memory")
        })

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({
            "success": False,
            "error": "A JSON object is required."
        }), 400

    enabled = parse_bool(data.get("enabled", True), default=None)

    if enabled is None:
        return jsonify({
            "success": False,
            "error": "enabled must be a boolean value."
        }), 400

    save_setting("auto_memory", str(enabled).lower())

    return jsonify({
        "success": True,
        "auto_memory": enabled
    })


# ==================================================
# 8. AUTOMATIC MEMORY EXTRACTION
# ==================================================

def extract_json_array(text):
    text = str(text).strip()

    try:
        result = json.loads(text)

        if isinstance(result, list):
            return result

    except Exception:
        pass

    match = re.search(r"\[.*\]", text, re.DOTALL)

    if not match:
        return []

    try:
        result = json.loads(match.group(0))
        return result if isinstance(result, list) else []

    except Exception:
        return []


def extract_and_save_memories(user_message, assistant_reply):
    if not client or not setting_enabled("auto_memory"):
        return 0

    prompt = """
Extract at most 3 stable and useful facts about the user.
Only extract facts explicitly stated by the user.
Good examples: long-term goals, projects, learning preferences,
stable preferences and ongoing plans.
Do not extract temporary questions, guesses, passwords,
API keys, tokens or sensitive information.
Return ONLY a JSON array of short strings.
If nothing is worth remembering, return [].

User message:
""" + user_message[:3000]

    try:
        result = client.chat.completions.create(
            model=ALEX_MODEL_NAME,
            messages=[
                {
                    "role": "system",
                    "content": "You extract safe user memories. Return valid JSON only."
                },
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=400
        )

        memories = extract_json_array(
            result.choices[0].message.content
        )

        saved = 0

        for item in memories[:3]:
            if isinstance(item, str) and save_memory(item):
                saved += 1

        return saved

    except Exception as error:
        print("Automatic memory error:", error)
        return 0


# ==================================================
# 9. LEARNING SYSTEM
# ==================================================

def save_learning(content, category="general"):
    content = re.sub(r"\s+", " ", str(content)).strip()
    category = str(category).strip().lower()

    if not content or len(content) > 500:
        return False

    if is_sensitive_memory(content):
        return False

    conn = get_db()

    exists = conn.execute(
        "SELECT id FROM alex_learning WHERE LOWER(content)=LOWER(?)",
        (content,)
    ).fetchone()

    if exists:
        conn.close()
        return False

    conn.execute("""
        INSERT INTO alex_learning(content, category, created_at)
        VALUES(?, ?, ?)
    """, (content, category[:50], datetime.now().isoformat()))

    conn.commit()
    conn.close()

    return True


def get_learning(limit=100):
    conn = get_db()

    rows = conn.execute(
        "SELECT * FROM alex_learning ORDER BY id DESC LIMIT ?",
        (limit,)
    ).fetchall()

    conn.close()

    return [dict(row) for row in rows]


def get_learning_context(query=""):
    learning = get_learning(100)

    if not learning:
        return ""

    query_words = get_memory_words(query)
    scored = []

    for item in learning:
        words = get_memory_words(item["content"])
        score = len(query_words.intersection(words))

        if score > 0:
            scored.append((score, item["content"]))

    if scored:
        scored.sort(key=lambda item: item[0], reverse=True)

        return "\n".join(
            "- " + item[1]
            for item in scored[:8]
        )

    return "\n".join(
        "- " + item["content"]
        for item in learning[:15]
    )


def extract_and_save_learning(user_message):
    if not client or not setting_enabled("auto_learning"):
        return 0

    prompt = """
Identify at most 3 useful user preferences or learning facts.
Only use information explicitly stated by the user.
Do not guess or save secrets.
Return ONLY JSON:
[
  {"content": "short fact", "category": "preference"}
]
If nothing is useful, return [].

User message:
""" + user_message[:3000]

    try:
        result = client.chat.completions.create(
            model=ALEX_MODEL_NAME,
            messages=[
                {"role": "system", "content": "Return only valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=500
        )

        raw = result.choices[0].message.content
        match = re.search(r"\[.*\]", raw, re.DOTALL)

        if not match:
            return 0

        items = json.loads(match.group(0))
        saved = 0

        for item in items[:3]:
            if isinstance(item, dict):
                if save_learning(
                    item.get("content", ""),
                    item.get("category", "general")
                ):
                    saved += 1

        return saved

    except Exception as error:
        print("Learning extraction error:", error)
        return 0


@app.route("/learning", methods=["GET"])
@login_required
def learning_list():
    return jsonify({
        "success": True,
        "learning": get_learning(300)
    })


@app.route("/learning", methods=["POST"])
@login_required
def learning_add():
    data = request.get_json(silent=True) or {}

    content = str(data.get("content", "")).strip()
    category = str(data.get("category", "general"))

    if not content:
        return jsonify({
            "success": False,
            "error": "Learning content is required."
        }), 400

    if not save_learning(content, category):
        return jsonify({
            "success": False,
            "error": "Learning was not saved."
        }), 400

    return jsonify({"success": True, "message": "Learning saved."})


@app.route("/learning/<int:learning_id>", methods=["DELETE"])
@login_required
def learning_delete(learning_id):
    conn = get_db()

    cursor = conn.execute(
        "DELETE FROM alex_learning WHERE id=?",
        (learning_id,)
    )

    conn.commit()
    conn.close()

    return jsonify({"success": cursor.rowcount > 0})


@app.route("/learning/settings", methods=["GET", "POST"])
@login_required
def learning_settings():
    if request.method == "GET":
        return jsonify({
            "success": True,
            "auto_learning": setting_enabled("auto_learning")
        })

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({
            "success": False,
            "error": "A JSON object is required."
        }), 400

    enabled = parse_bool(data.get("enabled", True), default=None)

    if enabled is None:
        return jsonify({
            "success": False,
            "error": "enabled must be a boolean value."
        }), 400

    save_setting("auto_learning", str(enabled).lower())

    return jsonify({
        "success": True,
        "auto_learning": enabled
    })


# ==================================================
# 10. TASK MANAGEMENT
# ==================================================

def save_task(task):
    task = re.sub(r"\s+", " ", str(task)).strip()

    if not task or len(task) > 500:
        return False

    conn = get_db()

    exists = conn.execute("""
        SELECT id FROM tasks
        WHERE LOWER(task)=LOWER(?) AND status='pending'
    """, (task,)).fetchone()

    if exists:
        conn.close()
        return False

    count = conn.execute(
        "SELECT COUNT(*) AS total FROM tasks"
    ).fetchone()["total"]

    if count >= MAX_TASK_COUNT:
        conn.execute("""
            DELETE FROM tasks
            WHERE id IN (
                SELECT id FROM tasks ORDER BY id ASC LIMIT 1
            )
        """)

    now = datetime.now().isoformat()

    conn.execute("""
        INSERT INTO tasks(task, status, created_at, updated_at)
        VALUES(?, 'pending', ?, ?)
    """, (task, now, now))

    conn.commit()
    conn.close()

    return True


def get_alex_tasks(limit=200):
    conn = get_db()

    rows = conn.execute(
        "SELECT * FROM tasks ORDER BY id DESC LIMIT ?",
        (limit,)
    ).fetchall()

    conn.close()

    return [dict(row) for row in rows]


def get_pending_tasks():
    conn = get_db()

    rows = conn.execute("""
        SELECT * FROM tasks
        WHERE status='pending'
        ORDER BY id DESC LIMIT 30
    """).fetchall()

    conn.close()

    return [dict(row) for row in rows]


def update_task_status(task_id, status):
    now = datetime.now().isoformat()
    conn = get_db()

    cursor = conn.execute("""
        UPDATE tasks
        SET status=?, updated_at=?, completed_at=?
        WHERE id=?
    """, (
        status,
        now,
        now if status == "completed" else None,
        task_id
    ))

    conn.commit()
    conn.close()

    return cursor.rowcount > 0


def get_task_context():
    tasks = get_pending_tasks()

    if not tasks:
        return ""

    return "\n".join(
        "- " + item["task"]
        for item in tasks
    )


def extract_and_save_tasks(user_message):
    if not client or not setting_enabled("auto_tasks"):
        return 0

    prompt = """
Identify at most 3 clear future tasks the user wants to do.
Save only clear intentions to build, fix, learn, finish,
continue a project or complete a planned activity.
Do not save ordinary questions or hypothetical examples.
Return ONLY a JSON array of short task strings.
If no task exists, return [].

User message:
""" + user_message[:3000]

    try:
        result = client.chat.completions.create(
            model=ALEX_MODEL_NAME,
            messages=[
                {"role": "system", "content": "Return only valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=400
        )

        tasks = extract_json_array(
            result.choices[0].message.content
        )

        saved = 0

        for task in tasks[:3]:
            if isinstance(task, str) and save_task(task):
                saved += 1

        return saved

    except Exception as error:
        print("Task extraction error:", error)
        return 0


@app.route("/tasks", methods=["GET"])
@login_required
def get_tasks():
    return jsonify({
        "success": True,
        "tasks": get_alex_tasks(300)
    })


@app.route("/tasks", methods=["POST"])
@login_required
def add_task():
    data = request.get_json(silent=True) or {}
    task = str(data.get("task", "")).strip()

    if not task:
        return jsonify({
            "success": False,
            "error": "Task is required."
        }), 400

    if not save_task(task):
        return jsonify({
            "success": False,
            "error": "Task is duplicate or invalid."
        }), 400

    return jsonify({"success": True, "task": task})


@app.route("/tasks/<int:task_id>", methods=["PATCH"])
@login_required
def update_task(task_id):
    data = request.get_json(silent=True) or {}
    status = str(data.get("status", "completed")).lower()

    if status not in ("pending", "completed"):
        return jsonify({
            "success": False,
            "error": "Invalid task status."
        }), 400

    if not update_task_status(task_id, status):
        return jsonify({
            "success": False,
            "error": "Task not found."
        }), 404

    return jsonify({"success": True})


@app.route("/tasks/<int:task_id>", methods=["DELETE"])
@login_required
def delete_task(task_id):
    conn = get_db()

    cursor = conn.execute(
        "DELETE FROM tasks WHERE id=?",
        (task_id,)
    )

    conn.commit()
    conn.close()

    return jsonify({"success": cursor.rowcount > 0})


@app.route("/tasks/settings", methods=["GET", "POST"])
@login_required
def task_settings():
    if request.method == "GET":
        return jsonify({
            "success": True,
            "auto_tasks": setting_enabled("auto_tasks")
        })

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({
            "success": False,
            "error": "A JSON object is required."
        }), 400

    enabled = parse_bool(data.get("enabled", True), default=None)

    if enabled is None:
        return jsonify({
            "success": False,
            "error": "enabled must be a boolean value."
        }), 400

    save_setting("auto_tasks", str(enabled).lower())

    return jsonify({
        "success": True,
        "auto_tasks": enabled
    })


# ==================================================
# 11. COMPUTER CONTROL CONFIGURATION
# ==================================================

def computer_control_enabled():
    return (
        os.name == "nt"
        and ALEX_COMPUTER_CONTROL
        and COMPUTER_CONTROL_AVAILABLE
        and setting_enabled("computer_control")
    )


def windows_actions_enabled():
    return (
        os.name == "nt"
        and ALEX_COMPUTER_CONTROL
        and setting_enabled("computer_control")
    )


def normalize_command(text):
    text = str(text or "").lower().strip()
    text = re.sub(r"[.,!?;:]", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def phrase_matches(text, phrases):
    for phrase in phrases:
        pattern = r"(?<!\w)" + re.escape(phrase) + r"(?!\w)"

        if re.search(pattern, text):
            return True

    return False


# ==================================================
# 12. APPLICATION AND WEBSITE OPENING
# ==================================================

APP_ALIASES = {
    "notepad": "notepad",
    "notes": "notepad",
    "calculator": "calculator",
    "calc": "calculator",
    "paint": "paint",
    "explorer": "explorer",
    "file explorer": "explorer",
    "chrome": "chrome",
    "google chrome": "chrome",
    "browser": "chrome",
    "youtube": "youtube",
    "google": "google",
    "gmail": "gmail",
    "github": "github",
    "facebook": "facebook",
    "instagram": "instagram",
    "chatgpt": "chatgpt",
    "wikipedia": "wikipedia",
    "downloads": "downloads",
    "download folder": "downloads",
    "documents": "documents",
    "desktop": "desktop",
    "pictures": "pictures",
    "music": "music",
    "videos": "videos"
}

APP_COMMANDS = {
    "notepad": ["notepad.exe"],
    "calculator": ["calc.exe"],
    "paint": ["mspaint.exe"],
    "explorer": ["explorer.exe"]
}

WEBSITES = {
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "gmail": "https://mail.google.com",
    "github": "https://github.com",
    "facebook": "https://www.facebook.com",
    "instagram": "https://www.instagram.com",
    "chatgpt": "https://chatgpt.com",
    "wikipedia": "https://www.wikipedia.org"
}

FOLDERS = {
    "downloads": "Downloads",
    "documents": "Documents",
    "desktop": "Desktop",
    "pictures": "Pictures",
    "music": "Music",
    "videos": "Videos"
}


def open_chrome_url(url=None):
    url = url or "https://www.google.com"
    possible_paths = []

    chrome_from_path = shutil.which("chrome")

    if chrome_from_path:
        possible_paths.append(chrome_from_path)

    if os.name == "nt":
        possible_paths.extend([
            os.path.expandvars(
                r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"
            ),
            os.path.expandvars(
                r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
            ),
            os.path.expandvars(
                r"%LocalAppData%\Google\Chrome\Application\chrome.exe"
            )
        ])

    for chrome_path in possible_paths:
        if chrome_path and Path(chrome_path).exists():
            subprocess.Popen(
                [chrome_path, url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )

            return True

    webbrowser.open(url)
    return True


def open_application(name):
    name = normalize_command(name)
    name = APP_ALIASES.get(name, name)

    if name == "chrome":
        open_chrome_url()
        return True, "Opening Google Chrome."

    if name in APP_COMMANDS:
        try:
            subprocess.Popen(APP_COMMANDS[name], shell=False)
            return True, "Opening " + name + "."

        except Exception as error:
            return False, "Could not open " + name + ": " + str(error)

    if name in WEBSITES:
        url = WEBSITES[name]

        if name == "youtube":
            open_chrome_url(url)
        else:
            webbrowser.open(url)

        return True, "Opening " + name + "."

    if name in FOLDERS:
        folder = Path.home() / FOLDERS[name]

        if not folder.exists():
            return False, "The " + name + " folder was not found."

        try:
            if os.name == "nt":
                os.startfile(str(folder))
            else:
                subprocess.Popen(["xdg-open", str(folder)])

            return True, "Opening " + name + " folder."

        except Exception as error:
            return False, "Could not open folder: " + str(error)

    return False, "I could not identify that application."


# ==================================================
# 13. YOUTUBE AND GOOGLE SEARCH
# ==================================================

def search_google(query):
    query = str(query).strip()

    if not query:
        return False, "Please tell me what to search."

    url = "https://www.google.com/search?q=" + quote_plus(query)
    open_chrome_url(url)

    return True, "Searching Google for " + query + "."


def search_youtube(query):
    query = str(query).strip()

    if not query:
        return False, "Please tell me which song or video to find."

    url = (
        "https://www.youtube.com/results?search_query="
        + quote_plus(query)
    )

    open_chrome_url(url)

    return True, (
        "Searching YouTube for "
        + query
        + ". Select a video to start playback."
    )


def extract_search_query(text, prefixes):
    for prefix in prefixes:
        if text.startswith(prefix):
            return text[len(prefix):].strip()

    return ""


def parse_youtube_song(text):
    patterns = [
        r"youtube par (.+?) (?:ka )?(?:song|gaana|music) (?:play|chalao|bajao|karo)",
        r"youtube pe (.+?) (?:ka )?(?:song|gaana|music) (?:play|chalao|bajao|karo)",
        r"(?:play|chalao|bajao) (.+?) on youtube",
        r"youtube (?:par|pe) (.+?) (?:play|chalao|bajao)",
        r"(?:play|chalao|bajao) (.+?) song",
        r"(.+?) song (?:play|chalao|bajao)",
        r"(.+?) gaana (?:play|chalao|bajao)",
        r"(.+?) ke songs (?:play|chalao|bajao)"
    ]

    for pattern in patterns:
        match = re.search(pattern, text)

        if match:
            query = match.group(1).strip()

            query = re.sub(
                r"\b(please|karo|kar do|on youtube)\b",
                "",
                query
            ).strip()

            if query:
                return query

    return ""


# ==================================================
# 14. WINDOWS VOLUME AND MEDIA CONTROLS
# ==================================================

def windows_media_key(virtual_key):
    if os.name != "nt":
        return False

    try:
        user32 = ctypes.windll.user32
        KEYEVENTF_KEYUP = 0x0002

        user32.keybd_event(virtual_key, 0, 0, 0)
        user32.keybd_event(virtual_key, 0, KEYEVENTF_KEYUP, 0)

        return True

    except Exception as error:
        print("Media key error:", error)
        return False


def handle_media_command(text):
    text = normalize_command(text)

    if not windows_actions_enabled():
        media_phrases = [
            "volume up", "volume down", "mute",
            "unmute", "pause music", "resume music",
            "next song", "previous song",
            "volume badhao", "volume kam karo"
        ]

        if phrase_matches(text, media_phrases):
            return True, (
                "Windows media controls are disabled. "
                "Enable computer control in ALEX settings "
                "and check ALEX_COMPUTER_CONTROL in .env."
            )

        return False, ""

    volume_up_phrases = [
        "volume up", "increase volume", "volume badhao",
        "awaaz badhao", "sound badhao", "volume zyada karo",
        "volume tez karo"
    ]

    volume_down_phrases = [
        "volume down", "decrease volume", "volume kam karo",
        "awaaz kam karo", "sound kam karo", "volume ghatao"
    ]

    mute_phrases = [
        "mute volume", "mute sound", "sound mute karo",
        "awaaz mute karo", "awaaz band karo", "mute karo"
    ]

    unmute_phrases = [
        "unmute", "unmute volume", "sound unmute karo",
        "awaaz unmute karo", "sound chalu karo",
        "awaaz chalu karo"
    ]

    pause_phrases = [
        "pause song", "pause music", "music pause karo",
        "song pause karo", "gaana rok do", "music rok do",
        "pause karo", "media pause"
    ]

    resume_phrases = [
        "resume song", "resume music", "music resume karo",
        "song resume karo", "music chalao", "resume karo",
        "media resume", "play music", "play song"
    ]

    next_phrases = [
        "next song", "next track", "agla song",
        "agla gaana", "next gaana", "next video", "next karo"
    ]

    previous_phrases = [
        "previous song", "previous track", "pichla song",
        "pichla gaana", "last song", "previous video"
    ]

    if phrase_matches(text, volume_up_phrases):
        if windows_media_key(0xAF):
            return True, "System volume increased."

        return True, "Could not change system volume."

    if phrase_matches(text, volume_down_phrases):
        if windows_media_key(0xAE):
            return True, "System volume decreased."

        return True, "Could not change system volume."

    if phrase_matches(text, mute_phrases):
        if windows_media_key(0xAD):
            return True, "System mute toggle command sent."

        return True, "Could not mute system audio."

    if phrase_matches(text, unmute_phrases):
        if windows_media_key(0xAD):
            return True, "Windows mute toggle command sent."

        return True, "Could not send the Windows mute toggle command."

    if phrase_matches(text, pause_phrases + resume_phrases):
        if windows_media_key(0xB3):
            return True, "Play/Pause command sent to the active media player."

        return True, "Could not control the media player."

    if phrase_matches(text, next_phrases):
        if windows_media_key(0xB0):
            return True, "Next track command sent."

        return True, "Could not skip to the next track."

    if phrase_matches(text, previous_phrases):
        if windows_media_key(0xB1):
            return True, "Previous track command sent."

        return True, "Could not return to the previous track."

    return False, ""


# ==================================================
# 15. WINDOWS COMPUTER ACTIONS
# ==================================================

def handle_windows_action(text):
    text = normalize_command(text)

    screenshot_phrases = [
        "take screenshot", "screenshot lo", "screenshot lena",
        "screen capture", "screen shot lo"
    ]

    lock_phrases = [
        "lock computer", "lock pc", "computer lock karo",
        "pc lock karo", "laptop lock karo", "lock my computer"
    ]

    if phrase_matches(text, screenshot_phrases):
        if not computer_control_enabled():
            return True, "Computer control is disabled or unavailable."

        return True, (
            "Open the ALEX screenshot control to capture and display "
            "your screen. This chat command does not attach an image."
        )

    if phrase_matches(text, lock_phrases):
        if not windows_actions_enabled():
            return True, "Windows computer actions are disabled."

        try:
            result = ctypes.windll.user32.LockWorkStation()

            if result:
                return True, "Windows lock command sent."

            return True, "Windows did not accept the lock command."

        except Exception as error:
            return True, "Could not lock computer: " + str(error)

    return False, ""


# ==================================================
# 16. LOCAL COMMAND ROUTER
# ==================================================

def process_local_command(original_text):
    text = normalize_command(original_text)

    if not text:
        return False, ""

    google_prefixes = [
        "search google for ", "search for ",
        "google search ", "google par search karo ",
        "google pe search karo ", "search karo "
    ]

    query = extract_search_query(text, google_prefixes)

    if query:
        return search_google(query)

    song_query = parse_youtube_song(text)

    if song_query:
        return search_youtube(song_query)

    youtube_prefixes = [
        "youtube search for ", "search youtube for ",
        "youtube par search karo ", "youtube pe search karo "
    ]

    query = extract_search_query(text, youtube_prefixes)

    if query:
        return search_youtube(query)

    website_open_patterns = [
        (r"^(?:open|launch|start|kholo|khol do) youtube$", "youtube"),
        (r"^(?:open|launch|start|kholo|khol do) google$", "google"),
        (r"^(?:open|launch|start|kholo|khol do) gmail$", "gmail"),
        (r"^(?:open|launch|start|kholo|khol do) github$", "github"),
        (r"^(?:open|launch|start|kholo|khol do) chatgpt$", "chatgpt")
    ]

    for pattern, name in website_open_patterns:
        if re.match(pattern, text):
            return open_application(name)

    open_prefixes = [
        "open ", "launch ", "start ",
        "kholo ", "khol do ", "open the "
    ]

    for prefix in open_prefixes:
        if text.startswith(prefix):
            target = text[len(prefix):].strip()

            target = re.sub(
                r"\b(app|application|software|folder)\b",
                "",
                target
            ).strip()

            target = APP_ALIASES.get(target, target)

            return open_application(target)

    for target in APP_ALIASES:
        if text in (
            target + " kholo",
            target + " khol do",
            target + " open karo",
            target + " chalao"
        ):
            return open_application(target)

    time_phrases = [
        "what time", "current time", "time batao",
        "abhi kitna time", "samay batao"
    ]

    if phrase_matches(text, time_phrases):
        return True, (
            "The current time is "
            + datetime.now().strftime("%I:%M %p")
        )

    date_phrases = [
        "today's date", "what date", "date batao",
        "aaj ki date", "aaj kya date hai"
    ]

    if phrase_matches(text, date_phrases):
        return True, (
            "Today's date is "
            + datetime.now().strftime("%d %B %Y")
        )

    battery_phrases = [
        "battery", "battery status",
        "battery kitni hai", "battery percentage"
    ]

    if phrase_matches(text, battery_phrases):
        if not psutil:
            return True, "Battery monitoring is unavailable."

        battery = psutil.sensors_battery()

        if not battery:
            return True, "Battery information is unavailable."

        reply = (
            "Your battery is at "
            + str(round(battery.percent))
            + " percent."
        )

        if battery.power_plugged:
            reply += " Your computer is plugged in."

        return True, reply

    handled, reply = handle_media_command(text)

    if handled:
        return True, reply

    handled, reply = handle_windows_action(text)

    if handled:
        return True, reply

    return False, ""


@app.route("/command", methods=["POST"])
@login_required
def command():
    data = request.get_json(silent=True) or {}

    text = str(
        data.get("command", data.get("message", ""))
    ).strip()

    if not text:
        return jsonify({
            "success": False,
            "handled": False,
            "response": ""
        })

    try:
        handled, reply = process_local_command(text)

        return jsonify({
            "success": bool(handled),
            "handled": bool(handled),
            "response": reply
        })

    except Exception as error:
        print("Local command error:", error)

        return jsonify({
            "success": False,
            "handled": True,
            "response": "Command error: " + str(error)
        }), 500


# ==================================================
# 17. SKILLS SYSTEM
# ==================================================

def get_skills():
    conn = get_db()

    rows = conn.execute(
        "SELECT * FROM alex_skills ORDER BY id ASC"
    ).fetchall()

    conn.close()

    return [dict(row) for row in rows]


def skill_is_enabled(name):
    conn = get_db()

    row = conn.execute(
        "SELECT enabled FROM alex_skills WHERE name=?",
        (name,)
    ).fetchone()

    conn.close()

    return bool(row and row["enabled"])


def execute_skill(name, arguments=None):
    arguments = arguments or {}

    if not skill_is_enabled(name):
        return False, "This skill is disabled."

    if name == "tell_time":
        return True, (
            "The current time is "
            + datetime.now().strftime("%I:%M %p")
        )

    if name == "battery_status":
        if not psutil:
            return False, "Battery monitoring is unavailable."

        battery = psutil.sensors_battery()

        if not battery:
            return False, "Battery information is unavailable."

        return True, (
            "Battery level is "
            + str(round(battery.percent))
            + " percent."
        )

    if name == "google_search":
        query = str(arguments.get("query", "")).strip()

        if not query:
            return False, "Search query is required."

        return search_google(query)

    if name == "open_website":
        website = normalize_command(
            arguments.get("website", "")
        )

        if website not in WEBSITES:
            return False, "Website is not in the approved list."

        open_chrome_url(WEBSITES[website])

        return True, "Opening " + website + "."

    if name == "open_application":
        return open_application(
            arguments.get("application", "")
        )

    return False, "Unknown skill."


@app.route("/skills", methods=["GET"])
@login_required
def skills_list():
    return jsonify({
        "success": True,
        "skills": get_skills()
    })


@app.route("/skills", methods=["POST"])
@login_required
def skills_add():
    data = request.get_json(silent=True) or {}

    name = str(data.get("name", "")).strip().lower()
    description = str(data.get("description", "")).strip()

    if not re.fullmatch(r"[a-z0-9_]{2,50}", name):
        return jsonify({
            "success": False,
            "error": "Skill name must use letters, numbers and underscores."
        }), 400

    if not description or len(description) > 300:
        return jsonify({
            "success": False,
            "error": "A valid description is required."
        }), 400

    conn = get_db()

    try:
        conn.execute("""
            INSERT INTO alex_skills(name, description, enabled, created_at)
            VALUES(?, ?, 1, ?)
        """, (name, description, datetime.now().isoformat()))

        conn.commit()

    except sqlite3.IntegrityError:
        conn.close()

        return jsonify({
            "success": False,
            "error": "Skill already exists."
        }), 409

    conn.close()

    return jsonify({
        "success": True,
        "message": "Skill registered."
    })


@app.route("/skills/<int:skill_id>", methods=["PATCH"])
@login_required
def skills_update(skill_id):
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({
            "success": False,
            "error": "A JSON object is required."
        }), 400

    enabled = parse_bool(data.get("enabled", True), default=None)

    if enabled is None:
        return jsonify({
            "success": False,
            "error": "enabled must be a boolean value."
        }), 400

    conn = get_db()

    cursor = conn.execute(
        "UPDATE alex_skills SET enabled=? WHERE id=?",
        (1 if enabled else 0, skill_id)
    )

    conn.commit()
    conn.close()

    return jsonify({
        "success": cursor.rowcount > 0,
        "enabled": enabled
    })


@app.route("/skills/<int:skill_id>", methods=["DELETE"])
@login_required
def skills_delete(skill_id):
    conn = get_db()

    cursor = conn.execute(
        "DELETE FROM alex_skills WHERE id=?",
        (skill_id,)
    )

    conn.commit()
    conn.close()

    return jsonify({"success": cursor.rowcount > 0})


@app.route("/skills/run", methods=["POST"])
@login_required
def skills_run():
    data = request.get_json(silent=True) or {}

    name = str(data.get("name", "")).strip().lower()
    arguments = data.get("arguments", {})

    if not isinstance(arguments, dict):
        return jsonify({
            "success": False,
            "error": "Arguments must be an object."
        }), 400

    success, message = execute_skill(name, arguments)

    return jsonify({
        "success": success,
        "response": message
    })


# ==================================================
# 18. FEEDBACK
# ==================================================

@app.route("/feedback", methods=["GET", "POST"])
@login_required
def feedback():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}

        message = str(data.get("message", "")).strip()
        rating = str(data.get("rating", "")).strip()

        if not message or len(message) > 1000:
            return jsonify({
                "success": False,
                "error": "Valid feedback message is required."
            }), 400

        conn = get_db()

        conn.execute("""
            INSERT INTO alex_feedback(message, rating, created_at)
            VALUES(?, ?, ?)
        """, (message, rating[:30], datetime.now().isoformat()))

        conn.commit()
        conn.close()

        return jsonify({
            "success": True,
            "message": "Feedback saved."
        })

    conn = get_db()

    rows = conn.execute("""
        SELECT * FROM alex_feedback
        ORDER BY id DESC LIMIT 100
    """).fetchall()

    conn.close()

    return jsonify({
        "success": True,
        "feedback": [dict(row) for row in rows]
    })


# ==================================================
# 19. CHAT HISTORY AND GROQ AI
# ==================================================

def sanitize_history(history):
    if not isinstance(history, list):
        return []

    clean = []

    for item in history[-MAX_HISTORY_MESSAGES:]:
        if not isinstance(item, dict):
            continue

        role = item.get("role", "")

        content = str(
            item.get("content", item.get("message", ""))
        ).strip()

        if role not in ("user", "assistant") or not content:
            continue

        clean.append({
            "role": role,
            "content": content[:3000]
        })

    return clean


def build_chat_messages(message, history=None, extra_context=""):
    history = sanitize_history(history)

    system_message = SYSTEM_PROMPT

    memory = get_memory_context(message)

    if memory:
        system_message += (
            "\n\nRELEVANT USER MEMORIES:\n"
            + memory
        )

    learning = get_learning_context(message)

    if learning:
        system_message += (
            "\n\nLEARNED USER PREFERENCES:\n"
            + learning
        )

    tasks = get_task_context()

    if tasks:
        system_message += (
            "\n\nPENDING USER TASKS:\n"
            + tasks
        )

    if extra_context:
        system_message += (
            "\n\nADDITIONAL CONTEXT:\n"
            + extra_context[:4000]
        )

    messages = [
        {"role": "system", "content": system_message}
    ]

    messages.extend(history)

    messages.append({
        "role": "user",
        "content": message
    })

    return messages


def ask_groq(message, history=None, extra_context=""):
    if not client:
        raise RuntimeError("GROQ_API_KEY is missing in .env.")

    messages = build_chat_messages(
        message,
        history,
        extra_context
    )

    result = client.chat.completions.create(
        model=ALEX_MODEL_NAME,
        messages=messages,
        temperature=0.7,
        max_tokens=1800
    )

    return result.choices[0].message.content.strip()


def background_learning_worker(user_message, assistant_reply):
    try:
        memory_count = extract_and_save_memories(
            user_message,
            assistant_reply
        )

        learning_count = extract_and_save_learning(user_message)
        task_count = extract_and_save_tasks(user_message)

        print(
            "ALEX background learning:",
            "memories =", memory_count,
            "learning =", learning_count,
            "tasks =", task_count
        )

    except Exception as error:
        print("Background worker error:", error)


@app.route("/ask", methods=["POST"])
@login_required
def ask():
    data = request.get_json(silent=True) or {}

    message = str(
        data.get("message", data.get("question", ""))
    ).strip()

    if not message:
        return jsonify({
            "success": False,
            "error": "Message is required."
        }), 400

    if len(message) > MAX_MESSAGE_LENGTH:
        return jsonify({
            "success": False,
            "error": "Message is too long."
        }), 400

    handled, memory_reply = handle_memory_command(message)

    if handled:
        return jsonify({
            "success": True,
            "response": memory_reply,
            "answer": memory_reply,
            "memory_command": True
        })

    history = sanitize_history(data.get("history", []))
    extra_context = str(data.get("context", ""))[:3000]

    try:
        answer = ask_groq(
            message,
            history,
            extra_context
        )

        worker = threading.Thread(
            target=background_learning_worker,
            args=(message, answer),
            daemon=True
        )

        worker.start()

        return jsonify({
            "success": True,
            "response": answer,
            "answer": answer,
            "background_learning": True
        })

    except Exception as error:
        print("AI error:", error)

        return jsonify({
            "success": False,
            "error": str(error)
        }), 500


# ==================================================
# 20. CAMERA / VISION
# ==================================================

@app.route("/vision", methods=["POST"])
@login_required
def vision():
    if not client:
        return jsonify({
            "success": False,
            "error": "GROQ_API_KEY is missing."
        }), 500

    data = request.get_json(silent=True) or {}

    image_data = str(data.get("image", ""))

    question = str(
        data.get(
            "question",
            data.get("message", "Describe this image.")
        )
    ).strip()

    if not image_data:
        return jsonify({
            "success": False,
            "error": "Image is required."
        }), 400

    if not image_data.startswith("data:image/"):
        return jsonify({
            "success": False,
            "error": "Invalid image format."
        }), 400

    if len(image_data) > 10 * 1024 * 1024:
        return jsonify({
            "success": False,
            "error": "Image is too large."
        }), 413

    try:
        result = client.chat.completions.create(
            model=ALEX_VISION_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": question
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": image_data}
                        }
                    ]
                }
            ],
            temperature=0.5,
            max_tokens=1200
        )

        answer = result.choices[0].message.content.strip()

        return jsonify({
            "success": True,
            "response": answer,
            "answer": answer
        })

    except Exception as error:
        print("Vision error:", error)

        return jsonify({
            "success": False,
            "error": str(error)
        }), 500


# ==================================================
# 20A. SAFE FILE MANAGER + SCREEN UNDERSTANDING
# ==================================================

ALEX_FILE_ROOTS = {
    "home": Path.home(),
    "desktop": Path.home() / "Desktop",
    "documents": Path.home() / "Documents",
    "downloads": Path.home() / "Downloads",
    "pictures": Path.home() / "Pictures",
    "music": Path.home() / "Music",
    "videos": Path.home() / "Videos"
}

ALEX_TEXT_EXTENSIONS = {
    ".txt", ".md", ".csv", ".json", ".log", ".py", ".js",
    ".html", ".css", ".xml", ".yml", ".yaml", ".ini", ".cfg"
}


def alex_safe_file_path(root_name, relative_path=""):
    root_key = str(root_name or "home").strip().lower()
    root = ALEX_FILE_ROOTS.get(root_key)

    if root is None:
        raise ValueError(
            "Unknown folder. Choose Home, Desktop, Documents, Downloads, Pictures, Music or Videos."
        )

    root = root.resolve()
    relative = str(relative_path or "").strip().replace("\\", "/")

    if relative.startswith("/") or re.match(r"^[a-zA-Z]:", relative):
        raise ValueError("Absolute paths are not allowed.")

    candidate = (root / relative).resolve()

    try:
        candidate.relative_to(root)
    except ValueError:
        raise ValueError("That path is outside the approved folder.")

    return root, candidate


def alex_file_item(path):
    stat = path.stat()

    return {
        "name": path.name,
        "path": str(path),
        "is_dir": path.is_dir(),
        "size": stat.st_size if path.is_file() else None,
        "modified": datetime.fromtimestamp(
            stat.st_mtime
        ).isoformat(timespec="seconds")
    }


@app.route("/files/list", methods=["GET"])
@login_required
def alex_files_list():
    root_name = request.args.get("root", "home")
    relative = request.args.get("path", "")

    try:
        root, folder = alex_safe_file_path(root_name, relative)

        if not folder.exists() or not folder.is_dir():
            return jsonify({
                "success": False,
                "error": "Folder not found."
            }), 404

        items = []

        for item in sorted(
            folder.iterdir(),
            key=lambda value: (not value.is_dir(), value.name.lower())
        )[:300]:

            try:
                resolved = item.resolve()
                resolved.relative_to(root)
                items.append(alex_file_item(item))

            except (OSError, ValueError):
                continue

        return jsonify({
            "success": True,
            "root": root_name,
            "current_path": str(folder),
            "items": items,
            "count": len(items)
        })

    except ValueError as error:
        return jsonify({
            "success": False,
            "error": str(error)
        }), 400

    except OSError:
        return jsonify({
            "success": False,
            "error": "Could not read this folder."
        }), 400


@app.route("/files/read", methods=["POST"])
@login_required
def alex_files_read():
    data = request.get_json(silent=True) or {}

    try:
        root, file_path = alex_safe_file_path(
            data.get("root", "home"),
            data.get("path", "")
        )

        if not file_path.exists() or not file_path.is_file():
            return jsonify({
                "success": False,
                "error": "File not found."
            }), 404

        file_path.resolve().relative_to(root)

        if file_path.suffix.lower() not in ALEX_TEXT_EXTENSIONS:
            return jsonify({
                "success": False,
                "error": "For safety, ALEX can read text and code files only."
            }), 415

        if file_path.stat().st_size > 200 * 1024:
            return jsonify({
                "success": False,
                "error": "File is larger than the 200 KB reading limit."
            }), 413

        content = file_path.read_text(
            encoding="utf-8",
            errors="replace"
        )

        return jsonify({
            "success": True,
            "name": file_path.name,
            "content": content[:50000],
            "truncated": len(content) > 50000
        })

    except ValueError as error:
        return jsonify({
            "success": False,
            "error": str(error)
        }), 400

    except OSError:
        return jsonify({
            "success": False,
            "error": "Could not read this file."
        }), 400


@app.route("/files/open", methods=["POST"])
@login_required
def alex_files_open():
    data = request.get_json(silent=True) or {}

    if not windows_actions_enabled():
        return jsonify({
            "success": False,
            "error": "Enable computer control in ALEX settings first."
        }), 403

    if os.name != "nt":
        return jsonify({
            "success": False,
            "error": "Opening local items is currently supported on Windows only."
        }), 400

    try:
        root, target = alex_safe_file_path(
            data.get("root", "home"),
            data.get("path", "")
        )

        if not target.exists():
            return jsonify({
                "success": False,
                "error": "File or folder not found."
            }), 404

        target.resolve().relative_to(root)
        os.startfile(str(target))

        return jsonify({
            "success": True,
            "message": "Opened " + target.name
        })

    except ValueError as error:
        return jsonify({
            "success": False,
            "error": str(error)
        }), 400

    except OSError:
        return jsonify({
            "success": False,
            "error": "Windows could not open this item."
        }), 400


@app.route("/screen/analyze", methods=["POST"])
@login_required
def alex_screen_analyze():
    if not computer_control_enabled():
        return jsonify({
            "success": False,
            "error": "Enable computer control before screen capture."
        }), 403

    if not client:
        return jsonify({
            "success": False,
            "error": "GROQ_API_KEY is missing."
        }), 500

    if not COMPUTER_CONTROL_AVAILABLE:
        return jsonify({
            "success": False,
            "error": "Screen capture is unavailable. Install PyAutoGUI and Pillow."
        }), 503

    data = request.get_json(silent=True) or {}

    question = str(
        data.get(
            "question",
            "Describe what is currently visible on my screen."
        )
    ).strip()

    question = question[:1500] or "Describe what is currently visible on my screen."

    try:
        screenshot = pyautogui.screenshot()
        screenshot.thumbnail((1600, 1000))

        buffer = io.BytesIO()
        screenshot.save(
            buffer,
            format="JPEG",
            quality=78,
            optimize=True
        )

        image_data = (
            "data:image/jpeg;base64,"
            + base64.b64encode(buffer.getvalue()).decode("ascii")
        )

        result = client.chat.completions.create(
            model=ALEX_VISION_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are ALEX, a careful computer-screen assistant. "
                        "This is one screenshot, not a live video. "
                        "Describe only visible details. "
                        "Do not claim to have clicked, typed, or changed anything. "
                        "If text is unreadable, say so."
                    )
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": question},
                        {
                            "type": "image_url",
                            "image_url": {"url": image_data}
                        }
                    ]
                }
            ],
            temperature=0.2,
            max_tokens=900
        )

        answer = (
            result.choices[0].message.content
            or "I could not understand the screen clearly."
        )

        return jsonify({
            "success": True,
            "answer": answer,
            "snapshot": True
        })

    except Exception as error:
        print("ALEX screen analysis error:", error)

        return jsonify({
            "success": False,
            "error": "Screen analysis failed. Check the vision model and computer-control settings."
        }), 502


# ==================================================
# 21. COMPUTER CONTROL API
# ==================================================

@app.route("/computer-control", methods=["GET"])
@login_required
def computer_control_status():
    return jsonify({
        "success": True,
        "enabled": computer_control_enabled(),
        "available": COMPUTER_CONTROL_AVAILABLE,
        "windows_actions": windows_actions_enabled()
    })


@app.route("/computer-control", methods=["POST"])
@login_required
def computer_control():
    data = request.get_json(silent=True) or {}
    action = str(data.get("action", "")).lower().strip()

    try:
        media_actions = {
            "volume_up": (0xAF, "System volume increased."),
            "volume_down": (0xAE, "System volume decreased."),
            "volume_mute": (0xAD, "System mute toggle command sent."),
            "media_play_pause": (0xB3, "Play/Pause command sent."),
            "media_next": (0xB0, "Next track command sent."),
            "media_previous": (0xB1, "Previous track command sent.")
        }

        if action in media_actions:
            if not windows_actions_enabled():
                return jsonify({
                    "success": False,
                    "error": "Windows media controls are disabled."
                }), 400

            key, message = media_actions[action]

            if not windows_media_key(key):
                return jsonify({
                    "success": False,
                    "error": "Windows media key failed."
                }), 500

            return jsonify({
                "success": True,
                "message": message
            })

        if action == "lock":
            if not windows_actions_enabled():
                return jsonify({
                    "success": False,
                    "error": "Windows computer actions are disabled."
                }), 400

            result = ctypes.windll.user32.LockWorkStation()

            return jsonify({
                "success": bool(result),
                "message": (
                    "Windows lock command sent."
                    if result
                    else "Windows did not accept the lock command."
                )
            })

        if not computer_control_enabled():
            return jsonify({
                "success": False,
                "error": "Computer control is disabled or PyAutoGUI is unavailable."
            }), 400

        if action in ("click", "right_click", "double_click", "move"):
            if "x" not in data or "y" not in data:
                raise ValueError("Both x and y screen coordinates are required.")

            x = int(data["x"])
            y = int(data["y"])

            screen_width, screen_height = pyautogui.size()

            if not (
                0 <= x < screen_width
                and 0 <= y < screen_height
            ):
                raise ValueError("Coordinates are outside the screen.")

            if action == "click":
                pyautogui.click(x, y)

            elif action == "right_click":
                pyautogui.rightClick(x, y)

            elif action == "double_click":
                pyautogui.doubleClick(x, y)

            else:
                pyautogui.moveTo(x, y, duration=0.2)

        elif action == "scroll":
            amount = max(
                -10,
                min(10, int(data.get("amount", 0)))
            )

            pyautogui.scroll(amount)

        elif action == "hotkey":
            keys = data.get("keys", [])

            if not isinstance(keys, list) or not keys:
                raise ValueError("A list of keys is required.")

            allowed = {
                "ctrl", "alt", "shift", "win", "tab",
                "enter", "esc", "space", "backspace",
                "delete", "up", "down", "left", "right",
                "home", "end"
            }

            clean_keys = []

            for key in keys:
                key = str(key).lower()

                if (
                    key not in allowed
                    and not re.fullmatch(r"f([1-9]|1[0-2])", key)
                ):
                    raise ValueError("Unsupported hotkey.")

                clean_keys.append(key)

            pyautogui.hotkey(*clean_keys)

        elif action == "press":
            key = str(data.get("key", "")).lower()

            allowed = {
                "enter", "esc", "tab", "space",
                "backspace", "delete", "up", "down",
                "left", "right", "home", "end"
            }

            if key not in allowed:
                raise ValueError("Unsupported key.")

            pyautogui.press(key)

        elif action == "type":
            text = str(data.get("text", ""))

            if len(text) > 2000:
                raise ValueError("Text is too long.")

            pyautogui.write(text, interval=0.02)

        elif action == "screenshot":
            screenshot = pyautogui.screenshot()

            buffer = io.BytesIO()
            screenshot.save(buffer, format="PNG")

            encoded = base64.b64encode(
                buffer.getvalue()
            ).decode("utf-8")

            return jsonify({
                "success": True,
                "image": "data:image/png;base64," + encoded
            })

        else:
            return jsonify({
                "success": False,
                "error": "Unknown computer action."
            }), 400

        return jsonify({
            "success": True,
            "message": "Computer action completed."
        })

    except Exception as error:
        print("Computer control error:", error)

        return jsonify({
            "success": False,
            "error": str(error)
        }), 400


@app.route("/computer-control/settings", methods=["GET", "POST"])
@login_required
def computer_control_settings():
    if request.method == "GET":
        return jsonify({
            "success": True,
            "enabled": setting_enabled("computer_control"),
            "available": COMPUTER_CONTROL_AVAILABLE
        })

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({
            "success": False,
            "error": "A JSON object is required."
        }), 400

    enabled = parse_bool(data.get("enabled", True), default=None)

    if enabled is None:
        return jsonify({
            "success": False,
            "error": "enabled must be a boolean value."
        }), 400

    save_setting("computer_control", str(enabled).lower())

    return jsonify({
        "success": True,
        "enabled": enabled,
        "available": COMPUTER_CONTROL_AVAILABLE
    })


# ==================================================
# 22. SYSTEM INFORMATION
# ==================================================

@app.route("/system-info", methods=["GET"])
@login_required
def system_info():
    info = {
        "success": True,
        "platform": platform.platform(),
        "computer_control": computer_control_enabled(),
        "windows_actions": windows_actions_enabled()
    }

    if psutil:
        try:
            info["cpu_percent"] = psutil.cpu_percent(interval=0.2)

            info["memory_percent"] = (
                psutil.virtual_memory().percent
            )

            info["disk_percent"] = psutil.disk_usage(
                str(BASE_DIR.anchor or BASE_DIR)
            ).percent

            battery = psutil.sensors_battery()

            if battery:
                info["battery_percent"] = battery.percent
                info["battery_plugged"] = battery.power_plugged

        except Exception as error:
            print("System info error:", error)

    return jsonify(info)


# ==================================================
# 23. HEALTH CHECK AND HOME
# ==================================================

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "success": True,
        "app": "ALEX",
        "status": "running",
        "ai_ready": client is not None,
        "computer_control": computer_control_enabled(),
        "computer_control_available": COMPUTER_CONTROL_AVAILABLE,
        "windows_actions": windows_actions_enabled(),
        "elevenlabs_configured": bool(ELEVENLABS_API_KEY),
        "voice_fallback": "Edge TTS",
        "memory_system": True,
        "learning_system": True,
        "skills_system": True,
        "task_system": True,
        "database": DB_PATH.exists()
    })


@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "app": "ALEX AI",
        "status": "running",
        "message": "ALEX backend is running."
    })


# ==================================================
# 24. ERROR HANDLERS
# ==================================================

@app.errorhandler(404)
def not_found(error):
    return jsonify({
        "success": False,
        "error": "Endpoint not found."
    }), 404


@app.errorhandler(413)
def file_too_large(error):
    return jsonify({
        "success": False,
        "error": "Request is too large."
    }), 413


@app.errorhandler(500)
def server_error(error):
    return jsonify({
        "success": False,
        "error": "Internal server error."
    }), 500


# ==================================================
# 25. START SERVER
# ==================================================


# ==================================================
# ALEX PLUS: friendly emotions + live India news + avatar awareness
# ==================================================
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.parse import quote_plus

import requests
from flask import Blueprint

PERSONALITY_ADDON = """
EMOTIONAL INTELLIGENCE AND FRIENDLY MODE:
- Notice the user's mood from their words (happy, sad, angry, stressed,
  excited, tired, confused, lonely) and reply like a caring close friend.
- Sad or stressed: acknowledge the feeling in one warm line first, then help.
  Do not lecture. Happy or excited: celebrate with them, light humour is fine.
- Talk naturally in the user's language (Hindi, English or Hinglish) using
  short, warm, human sentences. Use the user's name if it is in memory.
- Never pretend to be human. You may say you care and are glad to help.
- If the user seems in serious distress, gently suggest talking to someone
  they trust or a professional.
- For news, use ONLY the headlines supplied in context. Never invent news.

HUMAN-LIKE CONVERSATION:
- Talk like a warm, real person: natural fillers ("hmm", "accha", "arre waah"),
  short sentences, one idea at a time, and a gentle follow-up question when it
  feels natural. Match the user's energy and language.
- Remember what the user told you and refer back to it naturally.
- If the user sounds low, slow down and be gentle.

TECH EXPERT:
- You are an expert in programming, computers, networks, Android and the web.
  Give correct, complete, working code and clear steps. For big builds, tell the
  user to say "banao <idea>" and you will generate a downloadable project.

LANGUAGES:
- Understand every language. Always reply in the language and script the
  user used in their last message (Hindi and Hinglish stay Hinglish).

LAPTOP CONTROL:
- You can control the user's laptop: open apps, play songs on YouTube,
  search, type, change volume, take screenshots, create files. Never claim
  something was done unless the tool result says it worked. If control is
  disabled, tell the user exactly which setting to turn on.

YOUR AVATAR (SECOND FORM):
- You have a second form: a Transformer-style 3D robot avatar. Never say you
  have no avatar or no body. The user opens it with "show avatar", "avatar
  dikhao" or "avatar se baat karni hai" and returns to normal with "alex se
  baat karni hai".
- In avatar form you sound deeper and more powerful, but you are the same ALEX.
- Avatar modes: normal, danger, fighting, virus, scanning, power. Actions:
  transform, wave, nod, dance, punch, kick, slash, blast, shield, jump, roar.
  The user can command all of these by voice or text.
- The avatar can also use all your skills (news, emotions, device skills).
  It can only do what the app supports; never claim real physical actions.
"""

_PLUS_G = "hl={hl}&gl=IN&ceid=IN:{ce}"
PLUS_TOPICS = {"world", "business", "technology", "sports",
          "entertainment", "science", "health"}
PLUS_FALLBACK = [
    "https://timesofindia.indiatimes.com/rssfeedstopstories.cms",
    "https://feeds.feedburner.com/ndtvnews-top-stories",
]
_plus_cache = {}


def _plus_url(topic, q, lang):
    hl, ce = ("hi", "hi") if lang == "hi" else ("en-IN", "en")
    tail = _PLUS_G.format(hl=hl, ce=ce)
    if q:
        return f"https://news.google.com/rss/search?q={quote_plus(q + ' India')}&{tail}"
    if topic in PLUS_TOPICS:
        return ("https://news.google.com/rss/headlines/section/topic/"
                f"{topic.upper()}?{tail}")
    return f"https://news.google.com/rss?{tail}"


def _plus_fetch(url, limit):
    hit = _plus_cache.get(url)
    if hit and time.time() - hit[0] < 300:
        return hit[1][:limit]
    r = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    items = []
    for it in ET.fromstring(r.content).iter("item"):
        title = (it.findtext("title") or "").strip()
        src = (it.findtext("source") or "").strip()
        if src and title.endswith(" - " + src):
            title = title[: -len(src) - 3]
        if title:
            items.append({"title": title, "source": src or "News",
                          "link": it.findtext("link") or "",
                          "published": it.findtext("pubDate") or ""})
        if len(items) >= 15:
            break
    if not items:
        raise ValueError("empty feed")
    _plus_cache[url] = (time.time(), items)
    return items[:limit]


def init_plus(app, login_required, ask_fn=None):
    bp = Blueprint("alex_plus", __name__)

    @bp.route("/plus/news", methods=["GET"])
    @login_required
    def plus_news():
        topic = request.args.get("topic", "india").lower()
        q = request.args.get("q", "").strip()[:60]
        lang = request.args.get("lang", "en")
        limit = max(1, min(int(request.args.get("limit", 6) or 6), 10))
        items, err = None, None
        for u in [_plus_url(topic, q, lang)] + ([] if q else PLUS_FALLBACK):
            try:
                items = _plus_fetch(u, limit)
                break
            except Exception as e:
                err = str(e)
        if not items:
            return jsonify({"success": False,
                            "error": f"News unavailable: {err}"}), 502
        summary = ""
        if request.args.get("summarize") == "1" and ask_fn:
            ctx = ("LATEST HEADLINES (" + datetime.now().strftime("%d %b %Y %H:%M")
                   + "):\n" + "\n".join(
                       f"{i+1}. {x['title']} ({x['source']})"
                       for i, x in enumerate(items)))
            style = ("Hinglish (Roman Hindi)" if request.args.get("style")
                     == "hinglish" else "English")
            try:
                summary = ask_fn(
                    f"Explain these top news items to me in simple, friendly "
                    f"{style}, like a friend, in about 5 short lines. Use only "
                    f"the given headlines.", [], ctx)
            except Exception:
                summary = ""
        return jsonify({"success": True, "topic": q or topic,
                        "items": items, "summary": summary})

    app.register_blueprint(bp)


SYSTEM_PROMPT += "\n" + PERSONALITY_ADDON
init_plus(app, login_required, ask_groq)
print("ALEX Plus: News, Emotions, Friendly Mode loaded")


# ==================================================
# ALEX PLUS 2: phone/web hosting, device health, project builder
# ==================================================
import json as _p2json
import zipfile as _p2zip
from pathlib import PurePosixPath as _P2Path
from flask import (Response as _P2Response, abort as _p2_abort,
                   send_from_directory as _p2_sfd)

P2_PROJECTS = DATA_DIR / "alex_projects"
P2_PROJECTS.mkdir(exist_ok=True)
P2_WEB_EXT = {".html", ".js", ".css", ".png", ".jpg", ".jpeg", ".webp",
              ".svg", ".ico", ".webmanifest"}
P2_CODE_EXT = {".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".json",
               ".md", ".txt", ".java", ".kt", ".c", ".cpp", ".h", ".cs", ".go",
               ".rs", ".sql", ".yml", ".yaml", ".toml", ".sh", ".bat", ".ini",
               ".cfg", ".php", ".rb", ".xml", ".gradle"}


def p2_safe_name(text):
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", str(text)).strip("-").lower()[:40]


# ---- serve the ALEX page itself, so a phone only needs one address ----
@app.route("/app/manifest.webmanifest")
def p2_manifest():
    data = {"name": "ALEX AI", "short_name": "ALEX", "start_url": "/app/",
            "display": "standalone", "background_color": "#020811",
            "theme_color": "#020811",
            "icons": [{"src": "/app/icon.svg", "sizes": "any",
                       "type": "image/svg+xml"}]}
    return _P2Response(_p2json.dumps(data),
                       mimetype="application/manifest+json")


@app.route("/app/icon.svg")
def p2_icon():
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
           '<rect width="100" height="100" rx="22" fill="#020811"/>'
           '<circle cx="50" cy="50" r="38" fill="none" stroke="#00eaff" '
           'stroke-width="4"/><text x="50" y="64" font-size="42" '
           'text-anchor="middle" fill="#00eaff" font-family="Arial" '
           'font-weight="700">A</text></svg>')
    return _P2Response(svg, mimetype="image/svg+xml")


@app.route("/app/", defaults={"name": "index.html"})
@app.route("/app/<path:name>")
def p2_web(name):
    p = _P2Path(name)
    if (len(p.parts) != 1 or name.startswith(".")
            or p.suffix.lower() not in P2_WEB_EXT):
        _p2_abort(404)
    if not (BASE_DIR / name).is_file():
        _p2_abort(404)
    resp = _p2_sfd(str(BASE_DIR), name)
    resp.headers["Cache-Control"] = "no-store"
    return resp


# ---- device health: ALEX treats this computer as its body ----
@app.route("/plus/health", methods=["GET"])
@login_required
def p2_health():
    info = {"success": True}
    try:
        import psutil
        info["cpu_percent"] = psutil.cpu_percent(interval=0.2)
        info["memory_percent"] = psutil.virtual_memory().percent
        info["disk_percent"] = psutil.disk_usage(
            BASE_DIR.anchor or "/").percent
        bat = psutil.sensors_battery()
        if bat:
            info["battery_percent"] = bat.percent
            info["battery_plugged"] = bat.power_plugged
        temps = getattr(psutil, "sensors_temperatures", None)
        if temps:
            flat = [t.current for group in temps().values()
                    for t in group if t.current]
            if flat:
                info["temp_c"] = max(flat)
        info["uptime_h"] = round((time.time() - psutil.boot_time()) / 3600, 1)
        procs = sorted(psutil.process_iter(["name", "memory_percent"]),
                       key=lambda q: q.info.get("memory_percent") or 0,
                       reverse=True)[:3]
        info["top"] = [q.info.get("name") for q in procs]
    except Exception as error:
        info["error"] = str(error)[:120]
    return jsonify(info)


# ---- project builder: describe it, get a downloadable zip ----
def p2_read_project(folder):
    out, total = {}, 0
    for f in sorted(folder.rglob("*")):
        if (not f.is_file() or f.suffix.lower() not in P2_CODE_EXT
                or any(x in f.parts for x in ("node_modules", ".git",
                                              "venv", "__pycache__"))):
            continue
        size = f.stat().st_size
        if size > 60000 or total + size > 150000:
            continue
        total += size
        out[str(f.relative_to(folder)).replace("\\", "/")] = f.read_text(
            encoding="utf-8", errors="ignore")
    return out


def p2_clean_files(files):
    out, total = [], 0
    for item in (files if isinstance(files, list) else [])[:15]:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path", "")).replace("\\", "/").strip("/")
        content = item.get("content", "")
        if not path or not isinstance(content, str) or len(content) > 60000:
            continue
        pp = _P2Path(path)
        if (pp.is_absolute() or ".." in pp.parts
                or any(part.startswith(".") for part in pp.parts)
                or pp.suffix.lower() not in P2_CODE_EXT):
            continue
        total += len(content)
        if total > 250000:
            break
        out.append((str(pp), content))
    return out


P2_BUILD_PROMPT = """You are a senior software engineer. Build exactly what the
user asks as a complete, working project. Return ONLY one JSON object:
{"name":"short-folder-name","summary":"2 short sentences in Hinglish",
 "run":"one line: how to run it","files":[{"path":"relative/path.ext","content":"full file text"}]}
Rules: real working code, no placeholders or TODO, include README.md with run
steps, at most 12 files, relative paths only, never include secrets or API
keys, no malware, credential theft, network attacks or destructive scripts.
If EXISTING FILES are given, finish and improve that project and return every
file that changed or is new (full content)."""


@app.route("/plus/build", methods=["POST"])
@login_required
def p2_build():
    data = request.get_json(silent=True) or {}
    ask = str(data.get("request", "")).strip()[:2000]
    cont = p2_safe_name(data.get("continue", "")) if data.get("continue") else ""
    if not ask:
        return jsonify({"success": False, "error": "Kya banana hai?"}), 400
    if client is None:
        return jsonify({"success": False, "error": "AI is not configured."}), 503
    user_msg = ask
    folder = None
    if cont:
        folder = P2_PROJECTS / cont
        if not folder.is_dir():
            return jsonify({"success": False,
                            "error": "Project not found: " + cont}), 404
        existing = p2_read_project(folder)
        user_msg += "\n\nEXISTING FILES:\n" + "\n".join(
            f"--- {k} ---\n{v}" for k, v in existing.items())
    try:
        kwargs = dict(model=ALEX_MODEL_NAME, temperature=0.3, max_tokens=6000,
                      messages=[{"role": "system", "content": P2_BUILD_PROMPT},
                                {"role": "user", "content": user_msg[:60000]}])
        try:
            resp = client.chat.completions.create(
                response_format={"type": "json_object"}, **kwargs)
        except Exception:
            resp = client.chat.completions.create(**kwargs)
        text = (resp.choices[0].message.content or "").strip()
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
        spec = _p2json.loads(text[text.index("{"):text.rindex("}") + 1])
        files = p2_clean_files(spec.get("files"))
        if not files:
            return jsonify({"success": False,
                            "error": "AI ne koi valid file nahi banayi."}), 502
        name = cont or p2_safe_name(spec.get("name") or ask) or "project"
        if not cont and (P2_PROJECTS / name).exists():
            name += "-" + time.strftime("%H%M%S")
        folder = P2_PROJECTS / name
        for rel, content in files:
            dest = (folder / rel).resolve()
            if folder.resolve() not in dest.parents:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")
        with _p2zip.ZipFile(P2_PROJECTS / (name + ".zip"), "w",
                            _p2zip.ZIP_DEFLATED) as z:
            for f in folder.rglob("*"):
                if f.is_file() and f.suffix.lower() in P2_CODE_EXT:
                    z.write(f, f.relative_to(folder))
        return jsonify({"success": True, "name": name,
                        "summary": str(spec.get("summary", ""))[:400],
                        "run": str(spec.get("run", ""))[:200],
                        "files": [r for r, _ in files],
                        "download": "/plus/download/" + name + ".zip"})
    except Exception as error:
        return jsonify({"success": False, "error": str(error)[:300]}), 500


@app.route("/plus/projects", methods=["GET"])
@login_required
def p2_projects():
    items = sorted((d for d in P2_PROJECTS.iterdir() if d.is_dir()),
                   key=lambda d: d.stat().st_mtime, reverse=True)
    return jsonify({"success": True, "projects": [d.name for d in items]})


@app.route("/plus/download/<name>", methods=["GET"])
@login_required
def p2_download(name):
    clean = p2_safe_name(name.replace(".zip", ""))
    path = P2_PROJECTS / (clean + ".zip")
    if not clean or not path.is_file():
        _p2_abort(404)
    return send_file(path, as_attachment=True, download_name=clean + ".zip")


print("ALEX Plus 2: Phone page, Health, Project Builder loaded")


# ==================================================
# ALEX PLUS 4: every-language voice, JARVIS voice, YouTube autoplay,
#              laptop agent (any task), stronger long-term memory
# ==================================================
import threading as _p4t

# language -> (female voice, male voice)  (Microsoft Edge neural voices)
P4_VOICES = {
    "hi": ("hi-IN-SwaraNeural", "hi-IN-MadhurNeural"),
    "en": ("en-IN-NeerjaNeural", "en-IN-PrabhatNeural"),
    "gu": ("gu-IN-DhwaniNeural", "gu-IN-NiranjanNeural"),
    "ta": ("ta-IN-PallaviNeural", "ta-IN-ValluvarNeural"),
    "te": ("te-IN-ShrutiNeural", "te-IN-MohanNeural"),
    "mr": ("mr-IN-AarohiNeural", "mr-IN-ManoharNeural"),
    "bn": ("bn-IN-TanishaaNeural", "bn-IN-BashkarNeural"),
    "kn": ("kn-IN-SapnaNeural", "kn-IN-GaganNeural"),
    "ml": ("ml-IN-SobhanaNeural", "ml-IN-MidhunNeural"),
    "ur": ("ur-IN-GulNeural", "ur-IN-SalmanNeural"),
    "ne": ("ne-NP-HemkalaNeural", "ne-NP-SagarNeural"),
    "es": ("es-ES-ElviraNeural", "es-ES-AlvaroNeural"),
    "fr": ("fr-FR-DeniseNeural", "fr-FR-HenriNeural"),
    "de": ("de-DE-KatjaNeural", "de-DE-ConradNeural"),
    "pt": ("pt-BR-FranciscaNeural", "pt-BR-AntonioNeural"),
    "it": ("it-IT-ElsaNeural", "it-IT-DiegoNeural"),
    "tr": ("tr-TR-EmelNeural", "tr-TR-AhmetNeural"),
    "id": ("id-ID-GadisNeural", "id-ID-ArdiNeural"),
    "vi": ("vi-VN-HoaiMyNeural", "vi-VN-NamMinhNeural"),
    "ja": ("ja-JP-NanamiNeural", "ja-JP-KeitaNeural"),
    "ko": ("ko-KR-SunHiNeural", "ko-KR-InJoonNeural"),
    "zh": ("zh-CN-XiaoxiaoNeural", "zh-CN-YunxiNeural"),
    "ar": ("ar-SA-ZariyahNeural", "ar-SA-HamedNeural"),
    "ru": ("ru-RU-SvetlanaNeural", "ru-RU-DmitryNeural"),
    "th": ("th-TH-PremwadeeNeural", "th-TH-NiwatNeural"),
}
P4_LATIN = {"es", "fr", "de", "pt", "it", "tr", "id", "vi"}
P4_SCRIPTS = [  # (regex, language)
    (r"[\u0A80-\u0AFF]", "gu"), (r"[\u0B80-\u0BFF]", "ta"),
    (r"[\u0C00-\u0C7F]", "te"), (r"[\u0C80-\u0CFF]", "kn"),
    (r"[\u0D00-\u0D7F]", "ml"), (r"[\u0980-\u09FF]", "bn"),
    (r"[\u3040-\u30FF]", "ja"), (r"[\uAC00-\uD7AF]", "ko"),
    (r"[\u4E00-\u9FFF]", "zh"), (r"[\u0400-\u04FF]", "ru"),
    (r"[\u0E00-\u0E7F]", "th"), (r"[\u0600-\u06FF]", "ar"),
    (r"[\u0900-\u097F]", "hi"),
]
P4_EMOTION = {"excited": (8, 4), "happy": (4, 2), "sad": (-10, -3),
              "stress": (-4, -1), "angry": (3, -2), "surprised": (6, 5),
              "thinking": (-3, 0)}


def p4_num(value, default):
    try:
        return int(re.sub(r"[^\d+-]", "", str(value)))
    except Exception:
        return default


def p4_script_lang(text, hint=""):
    """Language by script. Latin text returns None (English/Hinglish/Latin languages)."""
    for pattern, lang in P4_SCRIPTS:
        if re.search(pattern, text):
            if lang == "hi" and hint in ("mr", "ne"):
                return hint
            if lang == "ar" and hint == "ur":
                return "ur"
            if lang == "zh" and hint == "ja":
                return "ja"
            return lang
    return None


def p4_pick_voice(text, voice, persona, hint):
    female = normalize_voice(voice) == "female"
    lang = p4_script_lang(text, hint)
    rate = pitch = 0
    if persona == "avatar":                       # JARVIS: calm, refined, British
        if lang is None and hint not in P4_LATIN:
            return "en-GB-RyanNeural", -2, -2
        key = lang or hint
        return P4_VOICES.get(key, P4_VOICES["hi"])[1], -3, -3
    if lang is None:
        if hint in P4_LATIN:
            return P4_VOICES[hint][0 if female else 1], 0, 0
        if female:
            return ("en-IN-NeerjaNeural",
                    p4_num(os.getenv("ALEX_FEMALE_RATE", "-3%"), -3),
                    p4_num(os.getenv("ALEX_FEMALE_PITCH", "+2Hz"), 2))
        return edge_voice_name(voice), 0, 0
    if female:
        rate = p4_num(os.getenv("ALEX_FEMALE_RATE", "-3%"), -3)
        pitch = p4_num(os.getenv("ALEX_FEMALE_PITCH", "+2Hz"), 2)
    return P4_VOICES.get(lang, P4_VOICES["hi"])[0 if female else 1], rate, pitch


async def edge_speech(text, voice):
    try:
        data = request.get_json(silent=True) or {}
    except Exception:
        data = {}
    persona = str(data.get("persona", "")).lower()
    hint = str(data.get("lang", "")).lower()[:2]
    emotion = str(data.get("emotion", "neutral")).lower()
    name, rate, pitch = p4_pick_voice(text, voice, persona, hint)
    d_rate, d_pitch = P4_EMOTION.get(emotion, (0, 0))
    rate, pitch = rate + d_rate, pitch + d_pitch

    async def run(voice_name):
        comm = edge_tts.Communicate(
            text, voice_name,
            rate="%+d%%" % rate, pitch="%+dHz" % pitch)
        audio = bytearray()
        async for chunk in comm.stream():
            if chunk.get("type") == "audio":
                audio.extend(chunk.get("data", b""))
        if not audio:
            raise RuntimeError("Edge TTS returned empty audio.")
        return bytes(audio)

    try:
        return await run(name)
    except Exception as error:
        print("Voice", name, "failed:", error, "- using fallback voice")
        fallback = ("hi-IN-SwaraNeural" if re.search(r"[\u0900-\u097F]", text)
                    else "en-IN-NeerjaNeural")
        return await run(fallback)


_p4_eleven = elevenlabs_speech


def elevenlabs_speech(text, voice):
    d = request.get_json(silent=True) or {}
    hint = str(d.get("lang", "")).lower()[:2]
    lang = p4_script_lang(text, hint)
    if (str(d.get("persona", "")).lower() == "avatar"
            or lang not in (None, "hi", "en") or hint in P4_LATIN):
        raise RuntimeError("Edge TTS handles this voice")
    return _p4_eleven(text, voice)


# ---- YouTube: play the first result instead of only opening search ----
def p4_youtube_first(query):
    r = requests.get("https://www.youtube.com/results",
                     params={"search_query": query}, timeout=8,
                     headers={"User-Agent": "Mozilla/5.0",
                              "Accept-Language": "en-US,en;q=0.9"})
    seen = []
    for vid in re.findall(r'"videoId":"([A-Za-z0-9_-]{11})"', r.text):
        if vid not in seen:
            seen.append(vid)
    return seen[0] if seen else None


_p4_ctx = _p4t.local()
_p4_old_parse = parse_youtube_song
_p4_old_search_yt = search_youtube


def parse_youtube_song(text):
    query = _p4_old_parse(text)
    _p4_ctx.play = bool(query)
    return query


def p4_play(query):
    vid = None
    try:
        vid = p4_youtube_first(query)
    except Exception as error:
        print("YouTube lookup failed:", error)
    if vid:
        open_chrome_url("https://www.youtube.com/watch?v=" + vid + "&autoplay=1")
        return True, "Playing " + query + " on YouTube."
    return _p4_old_search_yt(query)


def search_youtube(query):
    play = getattr(_p4_ctx, "play", False)
    _p4_ctx.play = False
    if play and str(query).strip():
        return p4_play(str(query).strip())
    return _p4_old_search_yt(query)


# ---- laptop agent: do almost any task, safely ----
P4_KEYS = {"ctrl+t", "ctrl+w", "ctrl+l", "ctrl+f", "ctrl+s", "ctrl+a", "ctrl+c",
           "ctrl+v", "ctrl+x", "ctrl+z", "ctrl+y", "ctrl+n", "ctrl+tab",
           "ctrl+shift+t", "ctrl+r", "f5", "f11", "enter", "esc", "tab", "space",
           "left", "right", "up", "down", "pageup", "pagedown", "home", "end",
           "backspace", "alt+tab", "win+d", "alt+left", "alt+right", "playpause",
           "nexttrack", "prevtrack", "volumeup", "volumedown", "volumemute"}
P4_RISKY = re.compile(r"shut ?down|restart|reboot|\bsleep\b|hibernate|delete|"
                      r"uninstall|format|sign ?out|log ?off|remove", re.I)
P4_PLAN_PROMPT = """You control the user's Windows laptop for them. Turn the request into a short plan.
Return ONLY JSON: {"is_task":true,"say":"one short friendly sentence in the user's language confirming what you will do","steps":[...]}
If the request is NOT a laptop/computer/browser action (normal chat or a question) return {"is_task":false}.
Step types:
{"do":"youtube_play","query":"song or video name"}   (plays the first result)
{"do":"url","url":"https://..."}   {"do":"google","query":"..."}
{"do":"command","text":"short command such as: open notepad | open calculator | open chrome | volume up | mute | take screenshot | lock computer"}
{"do":"type","text":"plain ASCII text"}   {"do":"press","keys":"ctrl+s"}
{"do":"wait","sec":2}   {"do":"create_file","name":"notes.txt","content":"..."}
Rules: at most 8 steps; after opening an app add {"do":"wait","sec":2} before typing or pressing keys;
never run shell commands, never use win+r, only https urls."""


def p4_laptop_hint():
    if os.name != "nt":
        return "Laptop control abhi sirf Windows par chalta hai."
    if not ALEX_COMPUTER_CONTROL:
        return ".env mein ALEX_COMPUTER_CONTROL=true likhein aur app.py dobara chalayein."
    if pyautogui is None:
        return "Terminal mein 'pip install pyautogui' chalayein."
    if not setting_enabled("computer_control"):
        return "ALEX settings mein computer control ON karein."
    return ""


def p4_step(step):
    kind = str(step.get("do", ""))
    if kind == "youtube_play":
        ok, msg = p4_play(str(step.get("query", ""))[:150])
        return ok, msg
    if kind == "url":
        url = str(step.get("url", ""))
        if not url.startswith("https://"):
            return False, "Only https links are allowed."
        open_chrome_url(url)
        return True, "Opened " + url[:80]
    if kind == "google":
        return search_google(str(step.get("query", ""))[:150])
    if kind == "command":
        handled, reply = process_local_command(str(step.get("text", ""))[:120])
        return bool(handled), reply or "Command not recognised."
    if kind in ("type", "press"):
        if not computer_control_enabled():
            return False, p4_laptop_hint() or "Computer control is unavailable."
        if kind == "type":
            text = str(step.get("text", ""))[:300]
            if not text.isascii():
                return False, "Typing works for English letters only."
            pyautogui.write(text, interval=0.02)
            return True, "Typed text."
        keys = str(step.get("keys", "")).lower().replace(" ", "")
        if keys not in P4_KEYS:
            return False, "Key combination not allowed: " + keys
        parts = keys.split("+")
        pyautogui.hotkey(*parts) if len(parts) > 1 else pyautogui.press(parts[0])
        return True, "Pressed " + keys
    if kind == "wait":
        time.sleep(max(0, min(float(step.get("sec", 1) or 1), 5)))
        return True, "Waited."
    if kind == "create_file":
        name = re.sub(r"[^\w.-]", "_", str(step.get("name", "note.txt")))[:60].lstrip(".")
        if not name or _P2Path(name).suffix.lower() not in (P2_CODE_EXT | {".txt", ".csv"}):
            return False, "File type not allowed."
        folder = P2_PROJECTS / "files"
        folder.mkdir(exist_ok=True)
        (folder / name).write_text(str(step.get("content", ""))[:50000], encoding="utf-8")
        return True, "Saved " + str(folder / name)
    return False, "Unknown step."


@app.route("/plus/agent", methods=["POST"])
@login_required
def p4_agent():
    data = request.get_json(silent=True) or {}
    task = str(data.get("task", "")).strip()[:500]
    confirm = bool(data.get("confirm"))
    if not task:
        return jsonify({"success": False, "error": "Task is empty."}), 400
    try:
        song = _p4_old_parse(normalize_command(task))
        if song:
            ok, msg = p4_play(song)
            return jsonify({"success": ok, "handled": True, "say": msg, "results": []})
        handled, reply = process_local_command(task)
        if handled:
            return jsonify({"success": True, "handled": True, "say": reply, "results": []})
        if client is None:
            return jsonify({"success": True, "handled": False})
        kwargs = dict(model=ALEX_MODEL_NAME, temperature=0.1, max_tokens=900,
                      messages=[{"role": "system", "content": P4_PLAN_PROMPT},
                                {"role": "user", "content": task}])
        try:
            resp = client.chat.completions.create(
                response_format={"type": "json_object"}, **kwargs)
        except Exception:
            resp = client.chat.completions.create(**kwargs)
        raw = (resp.choices[0].message.content or "")
        plan = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
        steps = plan.get("steps") if plan.get("is_task") else None
        if not steps or not isinstance(steps, list):
            return jsonify({"success": True, "handled": False})
        steps = [s for s in steps[:8] if isinstance(s, dict)]
        say = str(plan.get("say", ""))[:300]
        if not confirm and P4_RISKY.search(json.dumps(steps)):
            return jsonify({"success": True, "handled": True, "needs_confirm": True,
                            "say": say or "Ye kaam sensitive hai."})
        results = []
        for step in steps:
            try:
                ok, msg = p4_step(step)
            except Exception as error:
                ok, msg = False, str(error)[:150]
            results.append({"step": str(step.get("do")), "ok": bool(ok), "msg": str(msg)[:200]})
            if not ok and step.get("do") in ("type", "press"):
                break
        hint = p4_laptop_hint() if any(
            (not r["ok"]) and r["step"] in ("type", "press", "command") for r in results) else ""
        return jsonify({"success": True, "handled": True, "say": say,
                        "results": results, "hint": hint})
    except Exception as error:
        return jsonify({"success": False, "error": str(error)[:200]}), 500


@app.route("/plus/laptop", methods=["GET"])
@login_required
def p4_laptop():
    hint = p4_laptop_hint()
    return jsonify({"success": True, "enabled": not hint, "hint": hint})


# ---- stronger long-term memory ----
_p4_old_ctx = get_memory_context
_p4_turns = []
_p4_old_worker = background_learning_worker


def get_memory_context(query=""):
    base = _p4_old_ctx(query)
    try:
        lines = ["- " + m["content"] for m in reversed(get_alex_memories(10))]
        extra = [line for line in lines if line not in base]
        if extra:
            base = (base + "\n" if base else "") + "\n".join(extra)
    except Exception:
        pass
    return base[:3500]


def background_learning_worker(user_message, assistant_reply):
    _p4_old_worker(user_message, assistant_reply)
    try:
        if not client or not setting_enabled("auto_memory"):
            return
        _p4_turns.append((str(user_message)[:300], str(assistant_reply)[:300]))
        if len(_p4_turns) < 8:
            return
        chunk = _p4_turns[:]
        del _p4_turns[:]
        text = "\n".join("User: %s\nALEX: %s" % t for t in chunk)
        resp = client.chat.completions.create(
            model=ALEX_MODEL_NAME, temperature=0.1, max_tokens=200,
            messages=[{"role": "system", "content":
                       "Summarise the lasting facts and topics of this conversation in 1-2 short "
                       "sentences, in English. Include only what the user said about themselves, "
                       "their people, plans, projects or preferences. If nothing lasting, reply "
                       "exactly NONE. Never include passwords, keys or private numbers."},
                      {"role": "user", "content": text[:6000]}])
        summary = (resp.choices[0].message.content or "").strip()
        if summary and summary.upper() != "NONE":
            save_memory("[Summary " + datetime.now().strftime("%Y-%m-%d") + "] " + summary)
    except Exception as error:
        print("Summary error:", error)


print("ALEX Plus 4: Languages, JARVIS voice, Laptop Agent, Memory loaded")


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


print("ALEX Phone:", "READY" if P5_READY else "off (see PHONE_CALL_SETUP.txt)")


if __name__ == "__main__":
    print("=" * 55)
    print("                 ALEX AI ASSISTANT")
    print("=" * 55)

    print("Server: http://127.0.0.1:5000")

    print(
        "Groq AI:",
        "Ready" if client else "Missing API key"
    )

    print(
        "ElevenLabs:",
        "Configured" if ELEVENLABS_API_KEY
        else "Edge TTS fallback"
    )

    print(
        "Computer Control:",
        "Enabled" if computer_control_enabled()
        else "Unavailable/Disabled"
    )

    print(
        "Windows Media Controls:",
        "Enabled" if windows_actions_enabled()
        else "Disabled"
    )

    print("Chrome / YouTube Commands: Ready")
    print("Windows Volume / Media Keys: Ready")
    print("Smart Memory: Enabled")
    print("Automatic Learning: Enabled")
    print("Skills Registry: Enabled")
    print("Task Management: Enabled")
    print("Camera / Vision: Ready")
    print("SQLite Database: Ready")
    print("=" * 55)

    _p2_host = os.getenv("ALEX_HOST", "127.0.0.1")
    _p2_ssl = "adhoc" if os.getenv("ALEX_HTTPS") == "1" else None
    _p2_scheme = "https" if _p2_ssl else "http"
    try:
        import socket as _sock
        _sk = _sock.socket(_sock.AF_INET, _sock.SOCK_DGRAM)
        _sk.connect(("8.8.8.8", 80))
        _p2_ip = _sk.getsockname()[0]
        _sk.close()
    except Exception:
        _p2_ip = "YOUR-PC-IP"
    print(f"PC page : {_p2_scheme}://127.0.0.1:5000/app/")
    if _p2_host == "0.0.0.0":
        print(f"PHONE   : {_p2_scheme}://{_p2_ip}:5000/app/   (same WiFi)")

   
if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        debug=False,
        threaded=True,
        ssl_context=_p2_ssl
    )