import datetime as dt
import importlib.util
import json
import tempfile
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("compatdb", ROOT / "tools" / "compatdb.py")
compatdb = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(compatdb)
NEW_GAME_SPEC = importlib.util.spec_from_file_location("new_game", ROOT / "tools" / "new_game.py")
new_game = importlib.util.module_from_spec(NEW_GAME_SPEC)
assert NEW_GAME_SPEC.loader is not None
NEW_GAME_SPEC.loader.exec_module(new_game)


class CompatDatabaseTests(unittest.TestCase):
    def test_new_game_scaffold_is_valid_toml_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            preset = root / "presets" / "core-pinning" / "sm8550.toml"
            preset.parent.mkdir(parents=True)
            preset.touch()
            created = new_game.create_profile(root, 1245620, "ELDEN RING", "SM8550", "proton")
            self.assertEqual(len(created), 2)
            with (root / "compat" / "1245620" / "game.toml").open("rb") as source:
                self.assertEqual(tomllib.load(source)["game"]["name"], "ELDEN RING")
            with (root / "compat" / "1245620" / "sm8550.toml").open("rb") as source:
                target = tomllib.load(source)
            self.assertEqual(target["compatibility"][0]["runtime"], "proton")
            self.assertEqual(target["compatibility"][0]["proton-architecture"], "arm64")
            self.assertEqual(target["compatibility"][0]["proton-version"], "experimental")
            self.assertEqual(target["compatibility"][0]["proton-variant"], "steam")
            with self.assertRaisesRegex(compatdb.ValidationError, "replace generated TODO"):
                compatdb.reject_placeholders(created[-1], target)
            with self.assertRaises(FileExistsError):
                new_game.create_profile(root, 1245620, "ELDEN RING", "sm8550", "proton")

    def test_new_game_rejects_unknown_soc_and_metadata_mismatch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            preset = root / "presets" / "core-pinning" / "sm8550.toml"
            preset.parent.mkdir(parents=True)
            preset.touch()
            with self.assertRaisesRegex(ValueError, "unsupported SoC"):
                new_game.create_profile(root, 730, "Counter-Strike 2", "sm9999", "proton")
            new_game.create_profile(root, 730, "Counter-Strike 2", "sm8550", "proton")
            (root / "compat" / "730" / "sm8550.toml").unlink()
            with self.assertRaisesRegex(ValueError, "exact SteamDB name"):
                new_game.create_profile(root, 730, "Wrong name", "sm8550", "proton")

    def test_repository_validates(self):
        database = compatdb.load_database(ROOT)
        self.assertEqual(database["api_version"], 1)
        self.assertEqual(set(database["core_presets"]), {"sm8250", "sm8550", "sm8650", "sm8750"})
        self.assertEqual(set(database["fex_presets"]), {"standard", "fast", "compat"})

    def test_example_merges_general_and_soc_settings(self):
        database = compatdb.load_database(ROOT, ROOT / "examples" / "database" / "compat")
        target = database["games"]["123456"]["targets"]["sm8550"]
        self.assertEqual(target["settings"]["launch"]["arguments"], ["-vulkan", "-novid"])
        self.assertEqual(
            target["settings"]["launch"]["exe-append"],
            {
                "proton": "/../ExampleGame.exe",
                "slr": "/../example-game",
            },
        )
        self.assertEqual(target["settings"]["fex"]["preset"], "standard")
        self.assertEqual(target["settings"]["fex"]["overrides"]["Multiblock"], "0")
        self.assertEqual(target["settings"]["cpu"]["preset"], "big")

    def test_example_covers_alternative_setting_shapes(self):
        database = compatdb.load_database(ROOT, ROOT / "examples" / "database" / "compat")
        game = database["games"]["123456"]
        sm8550 = game["targets"]["sm8550"]
        sm8650 = game["targets"]["sm8650"]

        self.assertEqual(game["game"]["slug"], "example-game")
        self.assertEqual(sm8550["target"]["devices"], ["example-handheld", "example-handheld-pro"])
        self.assertEqual(
            {result["runtime"] for result in sm8550["compatibility"]},
            {"proton", "slr", "native", "wine"},
        )
        proton = [result for result in sm8550["compatibility"] if result["runtime"] == "proton"]
        self.assertEqual(
            {result["proton-architecture"] for result in proton},
            {"arm64", "x86_64"},
        )
        self.assertEqual(
            {
                (
                    result["proton-architecture"],
                    result["proton-version"],
                    result["proton-variant"],
                )
                for result in proton
            },
            {("arm64", "experimental", "steam"), ("x86_64", "9", "ge")},
        )
        self.assertEqual(
            [result["proton-architecture"] for result in proton if result.get("default")],
            ["arm64"],
        )
        self.assertFalse(sm8550["settings"]["fex"]["thunks"]["EGL"])
        self.assertFalse(sm8550["settings"]["environment"]["DISABLE_EXAMPLE_OVERLAY"])
        self.assertEqual(sm8650["settings"]["launch"]["exe-append"], "/../ExampleGame.exe")
        self.assertEqual(sm8650["settings"]["cpu"]["cores"], [7, 2, 3, 4, 5, 6])
        self.assertEqual(sm8650["settings"]["fex"]["preset"], "fast")
        self.assertEqual(
            {result["proton-version"] for result in sm8650["compatibility"]},
            {"9", "11"},
        )
        self.assertEqual(
            {
                (result["proton-version"], result["proton-variant"], result["status"])
                for result in sm8650["compatibility"]
            },
            {("9", "ge", "playable"), ("9", "steam", "playable"),
             ("11", "steam", "boots")},
        )

    def test_compiler_preserves_core_order_and_dates(self):
        database = compatdb.load_database(ROOT, ROOT / "examples" / "database" / "compat")
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "dist"
            compatdb.compile_database(database, output)
            game = json.loads((output / "db" / "v1" / "steam" / "123456.json").read_text())
            preset = json.loads((output / "db" / "v1" / "presets" / "core-pinning" / "sm8550.json").read_text())
            index = json.loads((output / "db" / "v1" / "index.json").read_text())
            self.assertEqual(game["targets"]["sm8550"]["reports"][0]["tested_at"], "2026-09-16")
            self.assertEqual(preset["presets"]["big"]["cores"], [3, 4, 5, 6, 7])
            runtime = index["games"][0]["targets"][0]["runtimes"][0]
            self.assertEqual(runtime["runtime"], "proton")
            self.assertEqual(runtime["last_tested"], "2026-09-16")
            x86_proton = next(
                result for result in index["games"][0]["targets"][0]["runtimes"]
                if result.get("proton-architecture") == "x86_64"
                and result.get("proton-version") == "9"
                and result.get("proton-variant") == "ge"
            )
            self.assertEqual(x86_proton["last_tested"], "2026-09-15")

    def test_named_preset_must_exist_for_soc(self):
        database = compatdb.load_database(ROOT, ROOT / "examples" / "database" / "compat")
        settings = {"cpu": {"preset": "does-not-exist"}}
        with self.assertRaisesRegex(compatdb.ValidationError, "unknown core preset"):
            compatdb.validate_settings(
                Path("test.toml"), settings, "sm8550",
                {soc: document["presets"] for soc, document in database["core_presets"].items()},
                set(database["fex_presets"]),
            )

    def test_explicit_cores_and_preset_are_mutually_exclusive(self):
        database = compatdb.load_database(ROOT)
        settings = {"cpu": {"preset": "big", "cores": [7, 3, 4, 5, 6]}}
        with self.assertRaisesRegex(compatdb.ValidationError, "mutually exclusive"):
            compatdb.validate_settings(
                Path("test.toml"), settings, "sm8550",
                {soc: document["presets"] for soc, document in database["core_presets"].items()},
                set(database["fex_presets"]),
            )

    def test_explicit_core_order_is_not_sorted(self):
        database = compatdb.load_database(ROOT)
        settings = {"cpu": {"cores": [7, 3, 4, 5, 6]}}
        result = compatdb.validate_settings(
            Path("test.toml"), settings, "sm8550",
            {soc: document["presets"] for soc, document in database["core_presets"].items()},
            set(database["fex_presets"]),
        )
        self.assertEqual(result["cpu"]["cores"], [7, 3, 4, 5, 6])

    def test_launch_data_is_not_a_shell_string(self):
        database = compatdb.load_database(ROOT)
        presets = {soc: document["presets"] for soc, document in database["core_presets"].items()}
        with self.assertRaisesRegex(compatdb.ValidationError, "array"):
            compatdb.validate_settings(
                Path("test.toml"), {"launch": {"arguments": "-vulkan -novid"}},
                "sm8550", presets, set(database["fex_presets"]),
            )

    def test_removed_settings_namespaces_are_rejected(self):
        database = compatdb.load_database(ROOT)
        presets = {soc: document["presets"] for soc, document in database["core_presets"].items()}
        for namespace in ("gamescope", "wine"):
            with self.subTest(namespace=namespace):
                with self.assertRaisesRegex(compatdb.ValidationError, "unknown settings table"):
                    compatdb.validate_settings(
                        Path("test.toml"), {namespace: {}}, "sm8550", presets,
                        set(database["fex_presets"]),
                    )
        with self.assertRaisesRegex(compatdb.ValidationError, "unknown exe-append route"):
            compatdb.validate_settings(
                Path("test.toml"), {"launch": {"exe-append": {
                    "unknown": "/../game.exe"}}},
                "sm8550", presets, set(database["fex_presets"]),
            )

    def test_scalar_exe_append_is_preserved(self):
        database = compatdb.load_database(ROOT)
        settings = {"launch": {"exe-append": "/../game.exe"}}
        result = compatdb.validate_settings(
            Path("test.toml"), settings, "sm8550",
            {soc: document["presets"] for soc, document in database["core_presets"].items()},
            set(database["fex_presets"]),
        )
        self.assertEqual(result["launch"]["exe-append"], "/../game.exe")

    def test_slr_proton_exe_append_requires_both_routes(self):
        database = compatdb.load_database(ROOT)
        presets = {soc: document["presets"] for soc, document in database["core_presets"].items()}
        value = {"launch": {"exe-append": {
            "proton": "/../game.exe", "slr": "/../game-linux"}}}
        self.assertEqual(
            compatdb.validate_settings(
                Path("test.toml"), value, "sm8550", presets,
                set(database["fex_presets"])),
            value,
        )
        with self.assertRaisesRegex(compatdb.ValidationError, "requires proton and slr"):
            compatdb.validate_settings(
                Path("test.toml"),
                {"launch": {"exe-append": {"proton": "/../game.exe"}}},
                "sm8550", presets, set(database["fex_presets"]),
            )

    def test_compatibility_is_runtime_specific(self):
        value = [
            {
                "runtime": "proton",
                "proton-architecture": "arm64",
                "proton-version": "experimental",
                "proton-variant": "steam",
                "default": True,
                "status": "playable",
                "confidence": "community",
            },
            {
                "runtime": "proton",
                "proton-architecture": "x86_64",
                "proton-version": "9",
                "proton-variant": "steam",
                "status": "boots",
                "confidence": "experimental",
            },
            {"runtime": "slr", "status": "broken", "confidence": "experimental"},
        ]
        self.assertEqual(compatdb.validate_compatibility(Path("test.toml"), value), value)
        with self.assertRaisesRegex(compatdb.ValidationError, "duplicate compatibility result"):
            compatdb.validate_compatibility(Path("test.toml"), [value[0], value[0]])

    def test_proton_architecture_and_default_are_validated(self):
        base = {"runtime": "proton", "status": "playable", "confidence": "community"}
        with self.assertRaisesRegex(compatdb.ValidationError, "proton-architecture"):
            compatdb.validate_compatibility(Path("test.toml"), [base])
        with self.assertRaisesRegex(compatdb.ValidationError, "proton-version"):
            compatdb.validate_compatibility(
                Path("test.toml"), [{**base, "proton-architecture": "arm64"}]
            )
        with self.assertRaisesRegex(compatdb.ValidationError, "proton-variant"):
            compatdb.validate_compatibility(Path("test.toml"), [{
                **base,
                "proton-architecture": "arm64",
                "proton-version": "experimental",
            }])
        with self.assertRaisesRegex(compatdb.ValidationError, "only one Proton"):
            compatdb.validate_compatibility(Path("test.toml"), [
                {
                    **base,
                    "proton-architecture": "arm64",
                    "proton-version": "experimental",
                    "proton-variant": "steam",
                    "default": True,
                },
                {
                    **base,
                    "proton-architecture": "x86_64",
                    "proton-version": "9",
                    "proton-variant": "ge",
                    "default": True,
                },
            ])
        with self.assertRaisesRegex(compatdb.ValidationError, "requires playable or verified"):
            compatdb.validate_compatibility(Path("test.toml"), [{
                **base,
                "proton-architecture": "arm64",
                "proton-version": "experimental",
                "proton-variant": "steam",
                "status": "boots",
                "default": True,
            }])

    def test_proton_release_tracks_allow_version_specific_results(self):
        base = {
            "runtime": "proton",
            "proton-architecture": "x86_64",
            "proton-variant": "steam",
            "status": "playable",
            "confidence": "community",
        }
        results = [
            {**base, "proton-version": "9", "default": True},
            {**base, "proton-version": "11", "status": "boots"},
            {**base, "proton-version": "9", "proton-variant": "ge"},
            {**base, "proton-version": "9", "proton-variant": "cachyos"},
        ]
        self.assertEqual(compatdb.validate_compatibility(Path("test.toml"), results), results)
        with self.assertRaisesRegex(compatdb.ValidationError, "major release"):
            compatdb.validate_compatibility(
                Path("test.toml"), [{**base, "proton-version": "9.0-4"}]
            )
        with self.assertRaisesRegex(compatdb.ValidationError, "lowercase identifier"):
            compatdb.validate_compatibility(Path("test.toml"), [{
                **base,
                "proton-version": "9",
                "proton-variant": "GE",
            }])

    def test_proton_reports_identify_the_tool_architecture(self):
        report = {
            "runtime": "proton",
            "tested_at": dt.date.today(),
            "distro": "Example Linux",
            "device": "Example Device",
            "notes": "Example report.",
        }
        with self.assertRaisesRegex(compatdb.ValidationError, "proton-architecture"):
            compatdb.validate_reports(Path("test.toml"), [report])
        report["proton-architecture"] = "x86_64"
        with self.assertRaisesRegex(compatdb.ValidationError, "proton-version"):
            compatdb.validate_reports(Path("test.toml"), [report])
        report["proton-version"] = "9"
        with self.assertRaisesRegex(compatdb.ValidationError, "proton-variant"):
            compatdb.validate_reports(Path("test.toml"), [report])
        report["proton-variant"] = "ge"
        self.assertEqual(compatdb.validate_reports(Path("test.toml"), [report]), [report])


if __name__ == "__main__":
    unittest.main()
