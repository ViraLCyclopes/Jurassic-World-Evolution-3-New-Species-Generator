import os
import json
import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(BASE_DIR, "Generated", "Logs")
CURRENT_SESSION_ID = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def get_current_log_file(session_file=None):
    if session_file and os.path.isfile(os.path.join(LOG_DIR, session_file)):
        return os.path.join(LOG_DIR, session_file)
    return os.path.join(LOG_DIR, f"session_{CURRENT_SESSION_ID}.log")


def clean_old_logs(max_files=15):
    try:
        if not os.path.exists(LOG_DIR):
            return
        files = []
        for f in os.listdir(LOG_DIR):
            if (f.startswith("session_") or f.startswith("activity_")) and f.endswith(".log"):
                fp = os.path.join(LOG_DIR, f)
                files.append((fp, os.path.getmtime(fp)))
        files.sort(key=lambda x: x[1], reverse=True)
        for fp, _ in files[max_files:]:
            try:
                os.remove(fp)
            except Exception:
                pass
    except Exception:
        pass


def write_activity_log(level, category, message):
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        clean_old_logs()
        log_file = get_current_log_file()

        if os.path.isfile(log_file) and os.path.getsize(log_file) > 100 * 1024:
            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            with open(log_file, "w", encoding="utf-8") as f:
                f.writelines(lines[-150:])

        t_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = f"[{t_str}] [{level.upper():5s}] [{category}] {message}\n"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(entry)
    except Exception as e:
        print("Log write error:", e)


def list_log_sessions():
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        sessions = []
        for f in os.listdir(LOG_DIR):
            if (f.startswith("session_") or f.startswith("activity_")) and f.endswith(".log"):
                fp = os.path.join(LOG_DIR, f)
                is_current = (f == f"session_{CURRENT_SESSION_ID}.log")
                mtime = os.path.getmtime(fp)
                mtime_str = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
                label = f"{f} (Current Session)" if is_current else f"{f} ({mtime_str})"
                sessions.append({"filename": f, "label": label, "mtime": mtime, "is_current": is_current})
        sessions.sort(key=lambda x: x["mtime"], reverse=True)
        return json.dumps({"success": True, "sessions": sessions, "current_session": f"session_{CURRENT_SESSION_ID}.log"})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


def get_recent_activity_logs(filter_level="", limit=100, session_file=""):
    try:
        log_file = get_current_log_file(session_file)
        if not os.path.isfile(log_file):
            return json.dumps({"success": True, "logs": "No activity logs recorded for this session.", "path": log_file, "count": 0})

        with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        if filter_level:
            fl = filter_level.upper()
            lines = [l for l in lines if f"[{fl}" in l or f"[{fl}]" in l]

        if not limit or limit <= 0:
            limit = 100

        recent_lines = lines[-limit:]
        recent_str = "".join(recent_lines) if recent_lines else "No matching log entries found."

        return json.dumps({
            "success": True,
            "logs": recent_str,
            "path": log_file,
            "total_entries": len(lines),
            "displayed_entries": len(recent_lines)
        })
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


def clear_activity_logs(session_file=""):
    try:
        log_file = get_current_log_file(session_file)
        if os.path.isfile(log_file):
            with open(log_file, "w", encoding="utf-8") as f:
                f.write(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [INFO ] [SYSTEM] Log session cleared by user.\n")
        return json.dumps({"success": True})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})
