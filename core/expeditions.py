import os
import json
import sqlite3

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_digsites(exp_fdb):
    try:
        if not os.path.isfile(exp_fdb):
            return json.dumps({"success": False, "error": f"FDB file not found at {exp_fdb}"})
        con = sqlite3.connect(f"file:{exp_fdb}?mode=ro", uri=True)
        try:
            cur = con.cursor()
            cur.execute('SELECT * FROM "DigSites"')
            cols = [desc[0] for desc in cur.description]
            rows = cur.fetchall()
            return json.dumps({"success": True, "data": {"columns": cols, "rows": rows}})
        finally:
            con.close()
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


def add_digsite_to_fdb(exp_fdb, payload_json, species_gen_module):
    try:
        payload = json.loads(payload_json) if isinstance(payload_json, str) else payload_json
        report = {}
        written = species_gen_module.add_digsite(
            exp_fdb,
            payload.get("site", {}),
            payload.get("fossils", []),
            mirror=payload.get("mirror", True),
            report=report
        )
        return json.dumps({"success": True, "tables": written})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})
