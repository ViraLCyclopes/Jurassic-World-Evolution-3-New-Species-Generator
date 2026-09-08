import os
import json
import sqlite3
import tempfile
import unittest
from unittest import mock

from core import database, generator


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DINO = os.path.join(ROOT, "extracted_fdbs", "c0dinosaurs.fdb")
EXP = os.path.join(ROOT, "extracted_fdbs", "c0expeditions.fdb")


class CloneRegressionTests(unittest.TestCase):
    def test_two_species_accumulate_in_both_databases(self):
        with tempfile.TemporaryDirectory() as tmp:
            dino_out = os.path.join(tmp, "dinosaurs.fdb")
            exp_out = os.path.join(tmp, "expeditions.fdb")
            report = {}
            first = database.clone_fdb(
                DINO, dino_out, "Dimetrodon", "TestAlpha",
                80000000, 80000000, report=report)
            database.clone_expeditions_fdb(
                EXP, exp_out, "Dimetrodon", "TestAlpha",
                80000000, 80000000, report=report,
                resolved_members=first["_resolved_members"])
            second = database.clone_fdb(
                DINO, dino_out, "IndominusRex", "TestBeta",
                80000010, 80000010, report=report)
            database.clone_expeditions_fdb(
                EXP, exp_out, "IndominusRex", "TestBeta",
                80000010, 80000010, report=report,
                resolved_members=second["_resolved_members"])
            third = database.clone_fdb(
                DINO, dino_out, "Dimetrodon", "TestGamma",
                80000020, 80000020, report=report)
            database.clone_expeditions_fdb(
                EXP, exp_out, "Dimetrodon", "TestGamma",
                80000020, 80000020, report=report,
                resolved_members=third["_resolved_members"])

            con = sqlite3.connect(dino_out)
            try:
                rows = con.execute(
                    "SELECT SpeciesID, Name FROM Species ORDER BY SpeciesID").fetchall()
                expected = [(m["target_sid"], m["target_name"])
                            for m in (first["_resolved_members"] +
                                      second["_resolved_members"] +
                                      third["_resolved_members"])]
                self.assertEqual(sorted(expected), rows)
                self.assertEqual(("ok",), con.execute("PRAGMA integrity_check").fetchone())
            finally:
                con.close()
            con = sqlite3.connect(exp_out)
            try:
                self.assertEqual(("ok",), con.execute("PRAGMA integrity_check").fetchone())
                self.assertGreater(con.execute(
                    "SELECT COUNT(*) FROM Genomes WHERE GenomeID LIKE 'Test%'").fetchone()[0], 0)
            finally:
                con.close()
            self.assertIn("TestAlpha", report["species_results"])
            self.assertIn("TestBeta", report["species_results"])
            self.assertIn("TestGamma", report["species_results"])
            self.assertEqual(
                report["tables"]["Species"],
                len(first["_resolved_members"]) + len(second["_resolved_members"]) +
                len(third["_resolved_members"]))

    def test_incompatible_existing_schema_is_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "bad.fdb")
            con = sqlite3.connect(target)
            con.execute("CREATE TABLE Species (WrongColumn INTEGER)")
            con.commit()
            con.close()
            with self.assertRaisesRegex(RuntimeError, "schema conflict.*Species"):
                database.clone_fdb(
                    DINO, target, "Dimetrodon", "TestBad",
                    81000000, 81000000)

    def test_identical_shared_row_deduplicates_but_conflict_fails(self):
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE Shared (ID INTEGER PRIMARY KEY, Value TEXT NOT NULL)")
        self.assertEqual(1, database.insert_rows_strict(
            con, "Shared", ["ID", "Value"], [[1, "same"]], "One"))
        self.assertEqual(0, database.insert_rows_strict(
            con, "Shared", ["ID", "Value"], [[1, "same"]], "Two"))
        with self.assertRaisesRegex(RuntimeError, "Two.*Shared.*ID"):
            database.insert_rows_strict(
                con, "Shared", ["ID", "Value"], [[1, "different"]], "Two")
        con.close()


class AllocationRegressionTests(unittest.TestCase):
    def test_complete_family_overlap_and_integer_validation(self):
        configs = [
            {"source": "Dimetrodon", "name": "One", "species_id": 82000000,
             "genetic_id": 82000000},
            {"source": "Dimetrodon", "name": "Two", "species_id": 82000001,
             "genetic_id": 82000001},
        ]
        with self.assertRaisesRegex(ValueError, "conflicts"):
            database.allocate_species_ids(configs, DINO)
        with self.assertRaisesRegex(ValueError, "GeneticSpeciesID.*already in use"):
            database.allocate_species_ids([
                {"source": "Dimetrodon", "name": "GeneOne",
                 "species_id": 82100000, "genetic_id": 82100000},
                {"source": "Dimetrodon", "name": "GeneTwo",
                 "species_id": 82100010, "genetic_id": 82100000},
            ], DINO)
        with self.assertRaisesRegex(ValueError, "whole integer"):
            database.allocate_species_ids([
                {"source": "Dimetrodon", "name": "Floaty", "species_id": 4.5}
            ], DINO)

    def test_maximum_increased_by_two_nines(self):
        config = [{
            "source": "Dimetrodon", "name": "MaxFamily",
            "species_id": 99999997, "genetic_id": 99999999,
        }]
        database.allocate_species_ids(config, DINO)
        self.assertEqual(99999997, config[0]["species_id"])
        bad = [{
            "source": "Dimetrodon", "name": "TooHigh",
            "species_id": 99999998, "genetic_id": 90000000,
        }]
        with self.assertRaisesRegex(ValueError, "invalid"):
            database.allocate_species_ids(bad, DINO)

    def test_automatic_ranges_do_not_overlap(self):
        configs = [
            {"source": "Dimetrodon", "name": "AutoOne"},
            {"source": "Dimetrodon", "name": "AutoTwo"},
        ]
        database.allocate_species_ids(configs, DINO, floor=83000000)
        self.assertEqual(83000000, configs[0]["species_id"])
        self.assertEqual(83000003, configs[1]["species_id"])
        self.assertNotEqual(configs[0]["genetic_id"], configs[1]["genetic_id"])

    def test_configured_source_ids_participate_in_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "custom.fdb")
            con = sqlite3.connect(source)
            con.execute(
                "CREATE TABLE Species (SpeciesID INTEGER PRIMARY KEY, "
                "GeneticSpeciesID INTEGER, Name TEXT UNIQUE, Prefab TEXT)")
            con.executemany("INSERT INTO Species VALUES (?, ?, ?, ?)", [
                (1, 1, "Donor", "Donor"),
                (90000000, 90000000, "CustomOccupied", "CustomOccupied"),
            ])
            con.commit()
            con.close()
            with self.assertRaisesRegex(ValueError, "conflicts"):
                database.allocate_species_ids([{
                    "source": "Donor", "name": "Clone",
                    "species_id": 90000000, "genetic_id": 90000001,
                }], source)

    def test_disabled_reordered_members_use_clone_offsets(self):
        config = {
            "source": "Dimetrodon", "name": "Reordered",
            "species_id": 91000000, "genetic_id": 91000000,
            "family_members": [
                {"Name": "Dimetrodon_Juvenile", "Prefab": "Dimetrodon_Juvenile"},
                {"Name": "Dimetrodon_Male", "enabled": False},
                {"Name": "Dimetrodon", "Prefab": "Dimetrodon_Female"},
            ],
        }
        database.allocate_species_ids([config], DINO)
        with tempfile.TemporaryDirectory() as tmp:
            result = database.clone_fdb(
                DINO, os.path.join(tmp, "out.fdb"), "Dimetrodon", "Reordered",
                config["species_id"], config["genetic_id"],
                fdb_overrides={"family_members": config["family_members"]})
        self.assertEqual(
            [(91000000, "Reordered_Juvenile"), (91000001, "Reordered")],
            [(m["target_sid"], m["target_name"])
             for m in result["_resolved_members"]])


class PublicationRegressionTests(unittest.TestCase):
    def _payload(self, root):
        return {
            "mod_name": "RecoveryTest",
            "_output_root": root,
            "source_dinosaurs_fdb": DINO,
            "source_expeditions_fdb": EXP,
            "species": [{
                "source": "IndominusRex", "name": "RecoverySpecies",
                "species_id": 84000000, "genetic_id": 84000000,
            }],
        }

    def test_asset_package_filename_case_migration(self):
        with tempfile.TemporaryDirectory() as root:
            old_path = os.path.join(root, "dynamoterror_female.assetpkg")
            with open(old_path, "w", encoding="utf-8") as stream:
                stream.write("preserved")
            exact_path = generator._exact_case_output_path(
                root, "Dynamoterror_Female.assetpkg")
            self.assertEqual(
                os.path.join(root, "Dynamoterror_Female.assetpkg"), exact_path)
            self.assertEqual(["Dynamoterror_Female.assetpkg"], os.listdir(root))
            with open(exact_path, "r", encoding="utf-8") as stream:
                self.assertEqual("preserved", stream.read())

    def test_failed_clone_preserves_existing_project(self):
        with tempfile.TemporaryDirectory() as root:
            out = os.path.join(root, "RecoveryTest")
            os.makedirs(os.path.join(out, "Main"))
            sentinel = os.path.join(out, "Main", "sentinel.bin")
            project = os.path.join(out, "mod_project.json")
            with open(sentinel, "wb") as stream:
                stream.write(b"known-good-fdb")
            with open(project, "w", encoding="utf-8") as stream:
                stream.write(b'{"known":"good"}'.decode())
            with open(sentinel, "rb") as stream:
                before_sentinel = stream.read()
            with open(project, "rb") as stream:
                before_project = stream.read()
            payload = self._payload(root)
            plan, _ = generator.plan_species(payload["species"][0])
            plans = [{"config": payload["species"][0], **plan}]
            with mock.patch("core.generator.clone_fdb", side_effect=RuntimeError("injected")):
                with self.assertRaisesRegex(RuntimeError, "injected"):
                    generator.generate_species("RecoveryTest", plans, {}, payload)
            with open(sentinel, "rb") as stream:
                self.assertEqual(before_sentinel, stream.read())
            with open(project, "rb") as stream:
                self.assertEqual(before_project, stream.read())

    def test_name_validation_precedes_output_mutation(self):
        with tempfile.TemporaryDirectory() as root:
            payload = self._payload(root)
            payload["mod_name"] = "..\\Escape"
            with self.assertRaisesRegex(ValueError, "path"):
                generator.generate_species("..\\Escape", [], {}, payload)
            self.assertEqual([], os.listdir(root))

    def test_complete_build_is_stable_and_preserves_custom_file(self):
        with tempfile.TemporaryDirectory() as root:
            payload = self._payload(root)
            payload["species"][0].pop("species_id")
            payload["species"][0].pop("genetic_id")
            plan, _ = generator.plan_species(payload["species"][0])
            plans = [{"config": payload["species"][0], **plan}]
            first = generator.generate_species("RecoveryTest", plans, {}, payload)
            assigned = (payload["species"][0]["species_id"],
                        payload["species"][0]["genetic_id"], payload["uuid"])
            custom = os.path.join(first["output_dir"], "Main", "custom.author.lua")
            with open(custom, "w", encoding="utf-8") as stream:
                stream.write("-- user file\n")

            plan, _ = generator.plan_species(payload["species"][0])
            plans = [{"config": payload["species"][0], **plan}]
            second = generator.generate_species("RecoveryTest", plans, {}, payload)
            self.assertEqual(
                assigned,
                (payload["species"][0]["species_id"],
                 payload["species"][0]["genetic_id"], payload["uuid"]))
            self.assertTrue(os.path.isfile(custom))
            with open(second["project_file"], "r", encoding="utf-8") as stream:
                saved = __import__("json").load(stream)
            self.assertEqual(payload["uuid"], saved["uuid"])

    def test_publish_failure_after_old_move_restores_original(self):
        with tempfile.TemporaryDirectory() as root:
            out = os.path.join(root, "RecoveryTest")
            os.makedirs(out)
            sentinel = os.path.join(out, "sentinel.txt")
            with open(sentinel, "w", encoding="utf-8") as stream:
                stream.write("original")
            payload = self._payload(root)
            plan, _ = generator.plan_species(payload["species"][0])
            plans = [{"config": payload["species"][0], **plan}]
            real_replace = os.replace
            calls = {"count": 0}

            def fail_second_replace(source, target):
                calls["count"] += 1
                if calls["count"] == 2:
                    raise PermissionError("simulated lock")
                return real_replace(source, target)

            with mock.patch("core.generator.os.replace", side_effect=fail_second_replace):
                with self.assertRaisesRegex(RuntimeError, "original was restored"):
                    generator.generate_species("RecoveryTest", plans, {}, payload)
            with open(sentinel, "r", encoding="utf-8") as stream:
                self.assertEqual("original", stream.read())

    def test_locked_original_is_untouched(self):
        with tempfile.TemporaryDirectory() as root:
            out = os.path.join(root, "RecoveryTest")
            os.makedirs(out)
            sentinel = os.path.join(out, "sentinel.txt")
            with open(sentinel, "w", encoding="utf-8") as stream:
                stream.write("original")
            payload = self._payload(root)
            plan, _ = generator.plan_species(payload["species"][0])
            plans = [{"config": payload["species"][0], **plan}]
            with mock.patch("core.generator.os.replace", side_effect=PermissionError("locked")):
                with self.assertRaisesRegex(RuntimeError, "original is untouched"):
                    generator.generate_species("RecoveryTest", plans, {}, payload)
            with open(sentinel, "r", encoding="utf-8") as stream:
                self.assertEqual("original", stream.read())

    def test_all_prepublication_fault_checkpoints_preserve_original(self):
        for stage in ("dinosaur_clone", "expedition_clone", "scaffolding",
                      "validation", "before_publish"):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as root:
                out = os.path.join(root, "RecoveryTest")
                os.makedirs(out)
                sentinel = os.path.join(out, "sentinel.txt")
                with open(sentinel, "w", encoding="utf-8") as stream:
                    stream.write(stage)
                payload = self._payload(root)

                def inject(current, wanted=stage):
                    if current == wanted:
                        raise RuntimeError(f"injected {wanted}")

                payload["_fault_injector"] = inject
                plan, _ = generator.plan_species(payload["species"][0])
                plans = [{"config": payload["species"][0], **plan}]
                with self.assertRaisesRegex(RuntimeError, f"injected {stage}"):
                    generator.generate_species("RecoveryTest", plans, {}, payload)
                with open(sentinel, "r", encoding="utf-8") as stream:
                    self.assertEqual(stage, stream.read())

    def test_owned_cleanup_preserves_unknown_and_modified_files(self):
        with tempfile.TemporaryDirectory() as root:
            payload = self._payload(root)
            plan, _ = generator.plan_species(payload["species"][0])
            plans = [{"config": payload["species"][0], **plan}]
            result = generator.generate_species("RecoveryTest", plans, {}, payload)
            old_generated = os.path.join(result["output_dir"], "Main", "recoveryspecies.lua")
            custom_lua = os.path.join(result["output_dir"], "Main", "custom.author.lua")
            custom_pkg = os.path.join(result["output_dir"], "Init", "custom.author.assetpkg")
            with open(old_generated, "a", encoding="utf-8") as stream:
                stream.write("\n-- hand edit\n")
            with open(custom_lua, "w", encoding="utf-8") as stream:
                stream.write("-- custom\n")
            with open(custom_pkg, "w", encoding="utf-8") as stream:
                stream.write("<custom/>\n")

            payload["species"][0]["name"] = "ReplacementSpecies"
            plan, _ = generator.plan_species(payload["species"][0])
            plans = [{"config": payload["species"][0], **plan}]
            report = {}
            generator.generate_species("RecoveryTest", plans, report, payload)
            self.assertTrue(os.path.isfile(old_generated))
            self.assertTrue(os.path.isfile(custom_lua))
            self.assertTrue(os.path.isfile(custom_pkg))
            self.assertIn("recoveryspecies.lua", " ".join(
                report.get("preserved_generated_file_conflicts", [])))

    def test_complete_backend_build_with_two_species(self):
        with tempfile.TemporaryDirectory() as root:
            payload = self._payload(root)
            payload["mod_name"] = "TwoSpeciesBuild"
            payload["species"].append({
                "source": "Dimetrodon", "name": "SecondSpecies",
                "species_id": 85000000, "genetic_id": 85000000,
            })
            plans = []
            for config in payload["species"]:
                plan, _ = generator.plan_species(config)
                plans.append({"config": config, **plan})
            result = generator.generate_species("TwoSpeciesBuild", plans, {}, payload)
            con = sqlite3.connect(result["dinosaurs_fdb"])
            try:
                names = {r[0] for r in con.execute("SELECT Name FROM Species")}
                self.assertIn("RecoverySpecies", names)
                self.assertIn("SecondSpecies", names)
                self.assertEqual(("ok",), con.execute("PRAGMA integrity_check").fetchone())
            finally:
                con.close()
            from lupa import LuaRuntime
            compile_lua = LuaRuntime().eval("function(source) return load(source) end")
            main_dir = os.path.dirname(result["dinosaurs_fdb"])
            for filename in os.listdir(main_dir):
                if not filename.lower().endswith(".lua"):
                    continue
                with open(os.path.join(main_dir, filename), "r", encoding="utf-8") as stream:
                    compiled = compile_lua(stream.read())
                self.assertFalse(isinstance(compiled, tuple) and compiled[0] is None,
                                 f"Lua syntax failed for {filename}: {compiled}")

    def test_gui_backend_returns_normalized_project(self):
        from species_gen_ui import SpeciesGenBackend
        with tempfile.TemporaryDirectory() as root:
            payload = self._payload(root)
            payload["species"][0].pop("species_id")
            payload["species"][0].pop("genetic_id")
            payload["asset_packages"] = {
                "StaleTopLevel": r"ovldata\RecoveryTest\StaleTopLevel"
            }
            payload["species"][0]["asset_packages"] = {
                "StaleSpecies": r"ovldata\RecoveryTest\StaleSpecies"
            }
            payload["config"] = {"asset_packages": {
                "Dynamoterror_Female": (
                    r"ovldata\RecoveryTest\Dinosaurs\Land\Dynamoterror\Female\ExactFolder"
                )
            }}
            response = json.loads(SpeciesGenBackend()._generate_sync(json.dumps(payload)))
            self.assertTrue(response["success"], response.get("error"))
            normalized = response["project"]
            self.assertIsInstance(normalized["species"][0]["species_id"], int)
            self.assertIsInstance(normalized["species"][0]["genetic_id"], int)
            self.assertRegex(normalized["uuid"], r"^[0-9a-f-]{36}$")
            output_dir = response["paths"]["output_dir"]
            package_file = os.path.join(
                output_dir, "Init", "Dynamoterror_Female.assetpkg")
            self.assertTrue(os.path.isfile(package_file))
            self.assertFalse(os.path.exists(os.path.join(
                output_dir, "Init", "StaleTopLevel.assetpkg")))
            self.assertFalse(os.path.exists(os.path.join(
                output_dir, "Init", "StaleSpecies.assetpkg")))
            with open(package_file, "r", encoding="utf-8") as stream:
                self.assertIn(
                    r"ovldata\RecoveryTest\Dinosaurs\Land\Dynamoterror\Female\ExactFolder",
                    stream.read())
            self.assertTrue(os.path.isdir(os.path.join(
                output_dir, "Dinosaurs", "Land", "Dynamoterror", "Female", "ExactFolder")))

    def test_gui_worker_rejects_duplicate_request_and_emits_result(self):
        from PyQt5.QtCore import QCoreApplication, QEventLoop, QTimer
        from species_gen_ui import SpeciesGenBackend
        app = QCoreApplication.instance() or QCoreApplication([])
        backend = SpeciesGenBackend()
        backend._generate_sync = lambda payload: json.dumps({"success": True})
        loop = QEventLoop()
        received = []
        backend.generationFinished.connect(lambda value: (received.append(json.loads(value)), loop.quit()))
        first = json.loads(backend.start_generate("{}", "update"))
        second = json.loads(backend.start_generate("{}", "generate"))
        self.assertTrue(first["accepted"])
        self.assertFalse(second["accepted"])
        QTimer.singleShot(5000, loop.quit)
        loop.exec_()
        app.processEvents()
        self.assertEqual("update", received[0]["request_type"])


if __name__ == "__main__":
    unittest.main()
