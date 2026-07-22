import sys
import os
import json
import sqlite3
import datetime
import gc
import re

os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu --disable-software-rasterizer --disable-gpu-compositing"

from PyQt5.QtCore import QObject, pyqtSlot, QUrl, Qt
from PyQt5.QtWidgets import QApplication, QMainWindow, QFileDialog, QMessageBox
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEnginePage
from PyQt5.QtWebChannel import QWebChannel

import species_gen
from core import logger, ppuipkg_manager, fdb_cloner, expeditions


class SpeciesGenBackend(QObject):
    """Exposed to JS as 'backend' via QWebChannel"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.window = parent

    @pyqtSlot(str, str, str)
    def log_activity(self, level, category, message):
        logger.write_activity_log(level, category, message)

    @pyqtSlot(result=str)
    def list_log_sessions(self):
        return logger.list_log_sessions()

    @pyqtSlot(str, int, str, result=str)
    def get_recent_activity_logs(self, filter_level="", limit=100, session_file=""):
        return logger.get_recent_activity_logs(filter_level, limit, session_file)

    @pyqtSlot(str, result=str)
    def clear_activity_logs(self, session_file=""):
        return logger.clear_activity_logs(session_file)

    @pyqtSlot(result=str)
    def get_log_file_path(self):
        return logger.get_current_log_file()

    @pyqtSlot(result=str)
    def get_species_list(self):
        fdb = species_gen.DEFAULT_SOURCE_FDB
        if not os.path.isfile(fdb):
            return json.dumps({"error": "FDB not found at " + fdb})
        
        con = sqlite3.connect(f"file:{fdb}?mode=ro", uri=True)
        try:
            all_species = []
            for row in con.execute("SELECT Name, SpeciesID, GeneticSpeciesID FROM Species ORDER BY Name"):
                all_species.append({"Name": row[0], "SpeciesID": row[1], "GeneticSpeciesID": row[2]})
            return json.dumps({"species": all_species})
        except Exception as e:
            return json.dumps({"error": str(e)})
        finally:
            con.close()

    @pyqtSlot(str, result=str)
    def scan_donor(self, name):
        try:
            res = species_gen.scan_donor(species_gen.DEFAULT_SOURCE_FDB, name)
            return json.dumps({"success": True, "data": res})
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})

    @pyqtSlot(result=str)
    def get_prefab_index(self):
        index_path = os.path.join(os.path.dirname(__file__), "prefab_index.json")
        try:
            if not os.path.isfile(index_path):
                index_path = species_gen.PREFAB_INDEX
            with open(index_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            return json.dumps({"error": str(e)})

    @pyqtSlot(result=str)
    def browse_and_rebuild_prefab_index(self):
        try:
            file_path, _ = QFileDialog.getOpenFileName(None, "Select JWE3 Prefab Dump Lua File", "", "Lua Files (*.lua);;All Files (*)")
            if not file_path:
                return json.dumps({"success": False, "cancelled": True})
            return self.rebuild_prefab_index_from_file(file_path)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})

    @pyqtSlot(str, result=str)
    def rebuild_prefab_index_from_file(self, lua_path):
        try:
            if not os.path.isfile(lua_path):
                return json.dumps({"success": False, "error": f"Lua dump file not found at '{lua_path}'"})
            import prefab_index
            data = prefab_index.build(lua_path)
            out_path = os.path.join(os.path.dirname(__file__), "prefab_index.json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

            logger.write_activity_log("INFO", "PREFAB_INDEX", f"Rebuilt index from {lua_path}: {len(data.get('entries', {}))} top-level entries.")
            return json.dumps({
                "success": True,
                "count": len(data.get("entries", {})),
                "referenced_only_count": len(data.get("referenced_only", [])),
                "lua_file": lua_path,
                "json_file": out_path
            })
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})


    @pyqtSlot(str, result=str)
    def generate(self, payload_json_str):
        try:
            payload = json.loads(payload_json_str)
            mod_name = payload.get("mod_name")
            species_configs = payload.get("species", [])
            
            if not mod_name or not species_configs:
                return json.dumps({"success": False, "error": "mod_name and at least one species are required"})

            plans = []
            combined_report = {"warnings": [], "tables": {}, "exp_tables": {}}
            
            root_ap = payload.get("asset_packages") or {}
            for config in species_configs:
                if root_ap:
                    if not config.get("asset_packages"): config["asset_packages"] = {}
                    config["asset_packages"].update(root_ap)
                plan, report = species_gen.plan_species(config)
                plans.append({"config": config, **plan})

                if config.get("scaling"):
                    payload.setdefault("scaling", {}).update(config["scaling"])

                if config.get("asset_packages"):
                    payload.setdefault("asset_packages", {}).update(config["asset_packages"])
                if config.get("asset_category") and not payload.get("asset_category"):
                    payload["asset_category"] = config["asset_category"]

                if report.get("warnings"):
                    combined_report["warnings"].extend(report["warnings"])
                
            paths = species_gen.generate_species(mod_name, plans, combined_report, payload)
            
            proj_path = os.path.join(species_gen.BASE, "Generated", mod_name, "mod_project.json")
            os.makedirs(os.path.dirname(proj_path), exist_ok=True)
            with open(proj_path, "w", encoding="utf-8") as f:
                f.write(json.dumps(payload, indent=2))
            paths["project_file"] = proj_path

            gc.collect()

            log_path = os.path.join(species_gen.BASE, "Generated", "species_gen_log.txt")
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            with open(log_path, "w", encoding="utf-8") as f:
                f.write("=== SUCCESS ===\n")
                f.write(json.dumps(combined_report, indent=2))

            return json.dumps({"success": True, "paths": paths, "report": combined_report})
        except Exception as e:
            import traceback
            traceback.print_exc()
            
            log_path = os.path.join(species_gen.BASE, "Generated", "species_gen_log.txt")
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            with open(log_path, "w", encoding="utf-8") as f:
                f.write("=== ERROR ===\n")
                f.write(str(e) + "\n\n")
                f.write(traceback.format_exc())
                f.write("\n\n=== PAYLOAD ===\n")
                f.write(json.dumps(payload, indent=2) if payload else "None")
                
            return json.dumps({"success": False, "error": str(e)})

    # ---------------- post-build editing ----------------

    @pyqtSlot(result=str)
    def list_built_mods(self):
        try:
            return json.dumps({"success": True, "data": species_gen.list_generated_mods()})
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})

    @pyqtSlot(str, str, result=str)
    def load_mod_table(self, fdb_path, table):
        try:
            if table in species_gen.COSMETIC_TABLES:
                species_gen.ensure_table(fdb_path, table)
            data = species_gen.read_table(fdb_path, table)
            if data is None:
                return json.dumps({"success": False, "error": f"{table} not present in this mod"})
            return json.dumps({"success": True, "data": data})
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})

    @pyqtSlot(str, str, str, result=str)
    def save_mod_table(self, fdb_path, table, payload_json):
        try:
            payload = json.loads(payload_json)
            report = {}
            n = species_gen.write_table_rows(fdb_path, table, payload["columns"], payload["rows"], report)
            problems = []
            if table in species_gen.COSMETIC_TABLES:
                problems = species_gen.validate_cosmetics(fdb_path)
            return json.dumps({"success": True, "written": n, "problems": problems})
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})

    @pyqtSlot(str, result=str)
    def validate_mod_cosmetics(self, fdb_path):
        try:
            return json.dumps({"success": True, "problems": species_gen.validate_cosmetics(fdb_path)})
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})

    @pyqtSlot(str, str, result=str)
    def add_digsite(self, exp_fdb, payload_json):
        return expeditions.add_digsite_to_fdb(exp_fdb, payload_json, species_gen)

    @pyqtSlot(str, result=str)
    def load_mod_ppuipkg(self, mod_name):
        return ppuipkg_manager.scan_mod_ppuipkg(mod_name)

    @pyqtSlot(str, result=str)
    def scan_mod_ppuipkg(self, mod_name):
        return ppuipkg_manager.scan_mod_ppuipkg(mod_name)

    @pyqtSlot(str, str, result=str)
    def save_mod_ppuipkg(self, mod_name, icons_json):
        return ppuipkg_manager.save_mod_ppuipkg(mod_name, icons_json)

    @pyqtSlot(str, str, result=str)
    def verify_asset_paths(self, mod_name, packages_json_str):
        return fdb_cloner.verify_asset_paths(mod_name, packages_json_str)

    @pyqtSlot(str, str, result=str)
    def verify_ppuipkg_paths(self, mod_name, icons_json_str):
        return ppuipkg_manager.verify_ppuipkg_paths(mod_name, icons_json_str)

    @pyqtSlot(str, result=str)
    def load_generated_mod_prefabs(self, mod_name):
        return fdb_cloner.load_generated_mod_prefabs(mod_name)

    @pyqtSlot(str, result=str)
    def scan_mod_assetpkgs(self, mod_name):
        return fdb_cloner.scan_mod_assetpkgs(mod_name)

    @pyqtSlot(str, result=str)
    def load_digsites(self, exp_fdb):
        return expeditions.load_digsites(exp_fdb)

    @pyqtSlot(str, result=str)
    def save_project(self, config_json_str):
        path, _ = QFileDialog.getSaveFileName(self.window, "Save Project", "", "JSON Files (*.json)")
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(config_json_str)
                return json.dumps({"success": True, "path": path})
            except Exception as e:
                return json.dumps({"success": False, "error": str(e)})
        return json.dumps({"success": False, "cancelled": True})

    @pyqtSlot(result=str)
    def load_project(self):
        path, _ = QFileDialog.getOpenFileName(self.window, "Load Project", "", "JSON Files (*.json)")
        if path:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = f.read()
                return json.dumps({"success": True, "data": data, "path": path})
            except Exception as e:
                return json.dumps({"success": False, "error": str(e)})
        return json.dumps({"success": False, "cancelled": True})

    @pyqtSlot(str)
    def show_error(self, message):
        QMessageBox.critical(self.window, "Error", message)

    @pyqtSlot(str)
    def show_info(self, message):
        QMessageBox.information(self.window, "Info", message)


class ConsoleWebEnginePage(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        log_str = f"JS Console ({sourceID}:{lineNumber}): {message}"
        print(log_str)
        logger.write_activity_log("JS", "CONSOLE", log_str)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("JWE3 Species Generator")
        self.resize(1200, 800)

        self.browser = QWebEngineView(self)
        self.browser.setPage(ConsoleWebEnginePage(self.browser))
        self.setCentralWidget(self.browser)

        self.browser.settings().setAttribute(self.browser.settings().WebAttribute.LocalContentCanAccessRemoteUrls, True)
        self.browser.settings().setAttribute(self.browser.settings().WebAttribute.LocalContentCanAccessFileUrls, True)

        self.channel = QWebChannel(self.browser.page())
        self.backend = SpeciesGenBackend(self)
        self.channel.registerObject("backend", self.backend)
        self.browser.page().setWebChannel(self.channel)

        ui_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "species_gen_ui", "index.html"))
        self.browser.load(QUrl.fromLocalFile(ui_path))


def main():
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
