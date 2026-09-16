#!/usr/bin/env python3
"""Validate TOML compatibility data and compile the public JSON API."""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import re
import shutil
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
STATUSES = {"untested", "broken", "boots", "playable", "verified"}
CONFIDENCE = {"experimental", "community", "maintainer"}
ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SOC_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
SETTING_TABLES = {"launch", "cpu", "fex", "environment"}
RUNTIME_ROUTES = {"native", "slr", "proton", "wine"}
PROTON_ARCHITECTURES = {"arm64", "x86_64"}
PROTON_VERSION = re.compile(r"^(?:[1-9][0-9]*|experimental|hotfix)$")
PROTON_VARIANT = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class ValidationError(Exception):
    pass


def fail(path: Path, message: str) -> None:
    raise ValidationError(f"{path}: {message}")


def load_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as source:
            value = tomllib.load(source)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        fail(path, str(exc))
    if not isinstance(value, dict):
        fail(path, "document must be a table")
    return value


def expect_keys(path: Path, value: dict[str, Any], allowed: set[str], where: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        fail(path, f"unknown {where} key(s): {', '.join(unknown)}")


def expect_table(path: Path, value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail(path, f"{where} must be a table")
    return value


def expect_string(path: Path, value: Any, where: str, *, optional: bool = False) -> None:
    if optional and value is None:
        return
    if not isinstance(value, str) or not value.strip():
        fail(path, f"{where} must be a non-empty string")


def validate_version(path: Path, data: dict[str, Any]) -> None:
    if data.get("schema_version") != SCHEMA_VERSION:
        fail(path, f"schema_version must be {SCHEMA_VERSION}")


def reject_placeholders(path: Path, value: Any) -> None:
    if isinstance(value, dict):
        for child in value.values():
            reject_placeholders(path, child)
    elif isinstance(value, list):
        for child in value:
            reject_placeholders(path, child)
    elif isinstance(value, str) and "TODO" in value.upper():
        fail(path, "replace generated TODO values before submitting")


def validate_string_list(path: Path, value: Any, where: str) -> None:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        fail(path, f"{where} must be an array of non-empty strings")


def validate_cores(path: Path, value: Any, where: str, limit: int | None = None) -> None:
    if not isinstance(value, list) or not value:
        fail(path, f"{where} must be a non-empty integer array")
    if any(type(cpu) is not int or cpu < 0 for cpu in value):
        fail(path, f"{where} contains an invalid CPU ID")
    if len(value) != len(set(value)):
        fail(path, f"{where} contains duplicate CPU IDs")
    if limit is not None and any(cpu >= limit for cpu in value):
        fail(path, f"{where} contains a CPU outside logical_cpus={limit}")


def validate_game(path: Path, expected_id: int) -> dict[str, Any]:
    data = load_toml(path)
    reject_placeholders(path, data)
    validate_version(path, data)
    expect_keys(path, data, {"schema_version", "game"}, "top-level")
    game = expect_table(path, data.get("game"), "game")
    expect_keys(path, game, {"id", "name", "store", "slug", "homepage", "aliases"}, "game")
    if type(game.get("id")) is not int or game["id"] != expected_id:
        fail(path, f"game.id must match directory name {expected_id}")
    expect_string(path, game.get("name"), "game.name")
    if game.get("store") != "steam":
        fail(path, "game.store must be 'steam' in schema v1")
    for key in ("slug", "homepage"):
        if key in game:
            expect_string(path, game[key], f"game.{key}")
    if "aliases" in game:
        validate_string_list(path, game["aliases"], "game.aliases")
    return game


def validate_settings(
    path: Path,
    settings: Any,
    soc: str | None,
    core_presets: dict[str, dict[str, Any]],
    fex_presets: set[str],
) -> dict[str, Any]:
    settings = expect_table(path, settings, "settings")
    expect_keys(path, settings, SETTING_TABLES, "settings table")

    launch = settings.get("launch")
    if launch is not None:
        launch = expect_table(path, launch, "settings.launch")
        expect_keys(path, launch, {"exe-append", "arguments"}, "launch")
        if "exe-append" in launch:
            executable = launch["exe-append"]
            if isinstance(executable, str):
                expect_string(path, executable, "settings.launch.exe-append")
                if "\0" in executable:
                    fail(path, "settings.launch.exe-append cannot contain NUL")
            else:
                executable = expect_table(path, executable, "settings.launch.exe-append")
                expect_keys(path, executable, {"proton", "slr"}, "exe-append route")
                if set(executable) != {"proton", "slr"}:
                    fail(path, "settings.launch.exe-append map requires proton and slr")
                for route, suffix in executable.items():
                    expect_string(path, suffix, f"settings.launch.exe-append.{route}")
                    if "\0" in suffix:
                        fail(path, f"settings.launch.exe-append.{route} cannot contain NUL")
        if "arguments" in launch:
            validate_string_list(path, launch["arguments"], "settings.launch.arguments")
            if any("\0" in argument for argument in launch["arguments"]):
                fail(path, "settings.launch.arguments cannot contain NUL")

    cpu = settings.get("cpu")
    if cpu is not None:
        cpu = expect_table(path, cpu, "settings.cpu")
        expect_keys(path, cpu, {"preset", "cores", "wine_topology", "nice", "scheduler"}, "cpu")
        if "preset" in cpu and "cores" in cpu:
            fail(path, "settings.cpu.preset and cores are mutually exclusive")
        if "preset" in cpu:
            expect_string(path, cpu["preset"], "settings.cpu.preset")
            if soc is not None and cpu["preset"] not in core_presets.get(soc, {}):
                fail(path, f"unknown core preset {cpu['preset']!r} for {soc}")
        if "cores" in cpu:
            validate_cores(path, cpu["cores"], "settings.cpu.cores")
        if "wine_topology" in cpu and not isinstance(cpu["wine_topology"], bool):
            fail(path, "settings.cpu.wine_topology must be a boolean")
        if "nice" in cpu and (type(cpu["nice"]) is not int or not -20 <= cpu["nice"] <= 19):
            fail(path, "settings.cpu.nice must be an integer from -20 through 19")
        if "scheduler" in cpu:
            expect_string(path, cpu["scheduler"], "settings.cpu.scheduler")

    fex = settings.get("fex")
    if fex is not None:
        fex = expect_table(path, fex, "settings.fex")
        expect_keys(path, fex, {"preset", "overrides", "thunks"}, "fex")
        if "preset" in fex:
            expect_string(path, fex["preset"], "settings.fex.preset")
            if fex["preset"] not in fex_presets:
                fail(path, f"unknown FEX preset {fex['preset']!r}")
        for table_name in ("overrides", "thunks"):
            if table_name not in fex:
                continue
            table = expect_table(path, fex[table_name], f"settings.fex.{table_name}")
            for key, value in table.items():
                expect_string(path, key, f"settings.fex.{table_name} key")
                expected = str if table_name == "overrides" else bool
                if not isinstance(value, expected):
                    fail(path, f"settings.fex.{table_name}.{key} has the wrong type")

    environment = settings.get("environment")
    if environment is not None:
        environment = expect_table(path, environment, "settings.environment")
        for key, value in environment.items():
            if not ENV_NAME.fullmatch(key):
                fail(path, f"invalid environment variable name {key!r}")
            if not isinstance(value, (str, bool)) or value is True:
                fail(path, f"settings.environment.{key} must be a string or false")
    return settings


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def load_core_presets(root: Path) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    directory = root / "presets" / "core-pinning"
    resolved: dict[str, dict[str, Any]] = {}
    documents: dict[str, Any] = {}
    for path in sorted(directory.glob("*.toml")):
        data = load_toml(path)
        validate_version(path, data)
        expect_keys(path, data, {"schema_version", "soc", "presets"}, "top-level")
        soc = expect_table(path, data.get("soc"), "soc")
        expect_keys(path, soc, {"id", "logical_cpus"}, "soc")
        soc_id = soc.get("id")
        if soc_id != path.stem or not isinstance(soc_id, str) or not SOC_NAME.fullmatch(soc_id):
            fail(path, "soc.id must be a lowercase identifier matching the filename")
        logical = soc.get("logical_cpus")
        if type(logical) is not int or logical < 1:
            fail(path, "soc.logical_cpus must be a positive integer")
        presets = expect_table(path, data.get("presets"), "presets")
        if not presets:
            fail(path, "at least one core preset is required")
        for name, preset_value in presets.items():
            if not SOC_NAME.fullmatch(name):
                fail(path, f"invalid preset name {name!r}")
            preset = expect_table(path, preset_value, f"presets.{name}")
            expect_keys(path, preset, {"description", "cores"}, f"preset {name}")
            expect_string(path, preset.get("description"), f"presets.{name}.description")
            validate_cores(path, preset.get("cores"), f"presets.{name}.cores", logical)
        resolved[soc_id] = presets
        documents[soc_id] = data
    return resolved, documents


def load_fex_presets(root: Path) -> tuple[set[str], dict[str, Any]]:
    directory = root / "presets" / "fex"
    names: set[str] = set()
    documents: dict[str, Any] = {}
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            fail(path, str(exc))
        if not isinstance(data, dict) or set(data) != {"Config"} or not isinstance(data["Config"], dict):
            fail(path, "must contain exactly one Config object")
        if not data["Config"] or any(not isinstance(k, str) or not isinstance(v, str) for k, v in data["Config"].items()):
            fail(path, "Config must be a non-empty string-to-string object")
        names.add(path.stem)
        documents[path.stem] = data
    return names, documents


def validate_compatibility(path: Path, value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value or any(not isinstance(item, dict) for item in value):
        fail(path, "compatibility must be a non-empty array of tables")
    seen: set[tuple[str, str | None, str | None, str | None]] = set()
    default_proton = 0
    for index, item in enumerate(value):
        expect_keys(
            path,
            item,
            {
                "runtime", "proton-architecture", "proton-version", "proton-variant",
                "default", "status", "confidence", "notes",
            },
            f"compatibility[{index}]",
        )
        runtime = item.get("runtime")
        if runtime not in RUNTIME_ROUTES:
            fail(path, f"compatibility[{index}].runtime must be one of {', '.join(sorted(RUNTIME_ROUTES))}")
        proton_architecture = item.get("proton-architecture")
        proton_version = item.get("proton-version")
        proton_variant = item.get("proton-variant")
        if runtime == "proton":
            if proton_architecture not in PROTON_ARCHITECTURES:
                fail(
                    path,
                    f"compatibility[{index}].proton-architecture must be one of "
                    f"{', '.join(sorted(PROTON_ARCHITECTURES))}",
                )
            if not isinstance(proton_version, str) or not PROTON_VERSION.fullmatch(proton_version):
                fail(
                    path,
                    f"compatibility[{index}].proton-version must be a major release "
                    "such as '9', or 'experimental'/'hotfix'",
                )
            if not isinstance(proton_variant, str) or not PROTON_VARIANT.fullmatch(proton_variant):
                fail(
                    path,
                    f"compatibility[{index}].proton-variant must be a lowercase identifier",
                )
        elif proton_architecture is not None:
            fail(path, f"compatibility[{index}].proton-architecture is only valid for Proton")
        elif proton_version is not None:
            fail(path, f"compatibility[{index}].proton-version is only valid for Proton")
        elif proton_variant is not None:
            fail(path, f"compatibility[{index}].proton-variant is only valid for Proton")
        identity = (runtime, proton_architecture, proton_version, proton_variant)
        if identity in seen:
            label = runtime_label(identity)
            fail(path, f"duplicate compatibility result {label!r}")
        seen.add(identity)
        if item.get("status") not in STATUSES:
            fail(path, f"compatibility[{index}].status must be one of {', '.join(sorted(STATUSES))}")
        if item.get("confidence") not in CONFIDENCE:
            fail(path, f"compatibility[{index}].confidence must be one of {', '.join(sorted(CONFIDENCE))}")
        if "default" in item:
            if item["default"] is not True:
                fail(path, f"compatibility[{index}].default must be true or omitted")
            if runtime != "proton":
                fail(path, f"compatibility[{index}].default is only valid for Proton")
            if item["status"] not in {"playable", "verified"}:
                fail(path, f"compatibility[{index}].default requires playable or verified status")
            default_proton += 1
        if "notes" in item:
            expect_string(path, item["notes"], f"compatibility[{index}].notes")
    if default_proton > 1:
        fail(path, "only one Proton compatibility result may be the default")
    return value


def validate_reports(path: Path, reports: Any) -> list[dict[str, Any]]:
    if reports is None:
        reports = []
    if not isinstance(reports, list) or any(not isinstance(report, dict) for report in reports):
        fail(path, "reports must be an array of tables")
    allowed = {
        "runtime", "proton-architecture", "proton-version", "proton-variant",
        "tested_at", "distro", "distro_version", "device", "tester", "notes",
        "kernel", "runtime_name", "runtime_version",
    }
    for index, report in enumerate(reports):
        expect_keys(path, report, allowed, f"reports[{index}]")
        runtime = report.get("runtime")
        if runtime not in RUNTIME_ROUTES:
            fail(path, f"reports[{index}].runtime must be one of {', '.join(sorted(RUNTIME_ROUTES))}")
        proton_architecture = report.get("proton-architecture")
        proton_version = report.get("proton-version")
        proton_variant = report.get("proton-variant")
        if runtime == "proton":
            if proton_architecture not in PROTON_ARCHITECTURES:
                fail(
                    path,
                    f"reports[{index}].proton-architecture must be one of "
                    f"{', '.join(sorted(PROTON_ARCHITECTURES))}",
                )
            if not isinstance(proton_version, str) or not PROTON_VERSION.fullmatch(proton_version):
                fail(
                    path,
                    f"reports[{index}].proton-version must be a major release such as "
                    "'9', or 'experimental'/'hotfix'",
                )
            if not isinstance(proton_variant, str) or not PROTON_VARIANT.fullmatch(proton_variant):
                fail(path, f"reports[{index}].proton-variant must be a lowercase identifier")
        elif proton_architecture is not None:
            fail(path, f"reports[{index}].proton-architecture is only valid for Proton")
        elif proton_version is not None:
            fail(path, f"reports[{index}].proton-version is only valid for Proton")
        elif proton_variant is not None:
            fail(path, f"reports[{index}].proton-variant is only valid for Proton")
        if not isinstance(report.get("tested_at"), dt.date) or isinstance(report.get("tested_at"), dt.datetime):
            fail(path, f"reports[{index}].tested_at must be a TOML local date")
        if report["tested_at"] > dt.date.today():
            fail(path, f"reports[{index}].tested_at cannot be in the future")
        for required in ("distro", "device", "notes"):
            expect_string(path, report.get(required), f"reports[{index}].{required}")
        for optional in allowed - {"runtime", "tested_at", "distro", "device", "notes"}:
            if optional in report:
                expect_string(path, report[optional], f"reports[{index}].{optional}")
    return reports


def runtime_identity(
    value: dict[str, Any],
) -> tuple[str, str | None, str | None, str | None]:
    runtime = value["runtime"]
    if runtime == "proton":
        return (
            runtime,
            value.get("proton-architecture"),
            value.get("proton-version"),
            value.get("proton-variant"),
        )
    return runtime, None, None, None


def runtime_label(identity: tuple[str, str | None, str | None, str | None]) -> str:
    runtime, architecture, version, variant = identity
    if runtime == "proton":
        return f"{runtime}/{architecture}/{version}/{variant}"
    return runtime


def load_database(root: Path, compat_dir: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    compat_dir = (compat_dir or root / "compat").resolve()
    core_presets, core_documents = load_core_presets(root)
    fex_presets, fex_documents = load_fex_presets(root)
    games: dict[str, Any] = {}

    if not compat_dir.is_dir():
        fail(compat_dir, "compat directory does not exist")
    for game_dir in sorted((entry for entry in compat_dir.iterdir() if entry.is_dir()), key=lambda p: p.name):
        if not game_dir.name.isdigit() or int(game_dir.name) <= 0:
            fail(game_dir, "game directory must be a positive decimal Steam app ID")
        game_file = game_dir / "game.toml"
        if not game_file.is_file():
            fail(game_file, "missing game metadata")
        game = validate_game(game_file, int(game_dir.name))
        general: dict[str, Any] = {}
        general_file = game_dir / "general.toml"
        if general_file.exists():
            data = load_toml(general_file)
            reject_placeholders(general_file, data)
            validate_version(general_file, data)
            expect_keys(general_file, data, {"schema_version", "settings"}, "top-level")
            general = validate_settings(general_file, data.get("settings"), None, core_presets, fex_presets)

        targets: dict[str, Any] = {}
        for path in sorted(game_dir.glob("*.toml")):
            if path.name in {"game.toml", "general.toml"}:
                continue
            if not SOC_NAME.fullmatch(path.stem):
                fail(path, "target filename must be a lowercase SoC identifier")
            data = load_toml(path)
            reject_placeholders(path, data)
            validate_version(path, data)
            expect_keys(path, data, {"schema_version", "target", "compatibility", "settings", "reports"}, "top-level")
            target = expect_table(path, data.get("target"), "target")
            expect_keys(path, target, {"soc", "devices"}, "target")
            if target.get("soc") != path.stem:
                fail(path, "target.soc must match the filename")
            if path.stem not in core_presets:
                fail(path, f"no core-pinning preset file exists for {path.stem}")
            if "devices" in target:
                validate_string_list(path, target["devices"], "target.devices")

            compatibility = validate_compatibility(path, data.get("compatibility"))
            settings = validate_settings(path, data.get("settings", {}), path.stem, core_presets, fex_presets)
            if all(item["status"] == "untested" for item in compatibility) and settings:
                fail(path, "untested targets cannot contain SoC-specific recommended settings")
            reports = validate_reports(path, data.get("reports"))
            compatibility_routes = {runtime_identity(item) for item in compatibility}
            report_routes = {runtime_identity(report) for report in reports}
            unknown_report_routes = sorted(report_routes - compatibility_routes)
            if unknown_report_routes:
                labels = [runtime_label(identity) for identity in unknown_report_routes]
                fail(path, "report runtime has no compatibility result: " + ", ".join(labels))
            for item in compatibility:
                if item["status"] != "untested" and runtime_identity(item) not in report_routes:
                    label = runtime_label(runtime_identity(item))
                    fail(path, f"{label} {item['status']} result requires a matching report")
            merged_settings = deep_merge(general, settings)
            # General named presets still have to exist for every SoC target.
            validate_settings(path, merged_settings, path.stem, core_presets, fex_presets)
            logical_cpus = core_documents[path.stem]["soc"]["logical_cpus"]
            explicit = merged_settings.get("cpu", {}).get("cores")
            if explicit is not None:
                validate_cores(path, explicit, "settings.cpu.cores", logical_cpus)
            targets[path.stem] = {
                "target": target,
                "compatibility": compatibility,
                "settings": merged_settings,
                "reports": reports,
                "source": path.relative_to(root).as_posix(),
            }
        if not targets:
            fail(game_dir, "at least one SoC target TOML file is required")
        games[game_dir.name] = {
            "game": game,
            "source": game_file.relative_to(root).as_posix(),
            "targets": targets,
        }

    return {
        "api_version": SCHEMA_VERSION,
        "games": games,
        "core_presets": core_documents,
        "fex_presets": fex_documents,
    }


def json_default(value: Any) -> Any:
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    raise TypeError(f"cannot encode {type(value).__name__}")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, default=json_default) + "\n",
        encoding="utf-8",
    )


def compile_database(database: dict[str, Any], output: Path) -> None:
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    try:
        api = temporary / "db" / f"v{SCHEMA_VERSION}"
        summaries = []
        for appid, document in sorted(database["games"].items(), key=lambda item: int(item[0])):
            write_json(api / "steam" / f"{appid}.json", {
                "api_version": SCHEMA_VERSION,
                **document,
            })
            summaries.append({
                **document["game"],
                "targets": [
                    {
                        "soc": soc,
                        "runtimes": [
                            {
                                **result,
                                "last_tested": max(
                                    (report["tested_at"] for report in target["reports"]
                                    if runtime_identity(report) == runtime_identity(result)),
                                    default=None,
                                ),
                            }
                            for result in target["compatibility"]
                        ],
                    }
                    for soc, target in sorted(document["targets"].items())
                ],
            })
        index = {
            "api_version": SCHEMA_VERSION,
            "games": summaries,
            "presets": {
                "core_pinning": sorted(database["core_presets"]),
                "fex": sorted(database["fex_presets"]),
            },
        }
        write_json(api / "index.json", index)
        write_json(temporary / "db" / "index.json", index)
        for soc, value in database["core_presets"].items():
            write_json(api / "presets" / "core-pinning" / f"{soc}.json", value)
        for name, value in database["fex_presets"].items():
            write_json(api / "presets" / "fex" / f"{name}.json", value)
        (temporary / "index.html").write_text(
            "<!doctype html><meta charset=utf-8><title>Compatibility database</title>"
            "<h1>Compatibility database</h1><p>Generated API version "
            f"{SCHEMA_VERSION}; {len(summaries)} game(s).</p><p><a href=\"db/v{SCHEMA_VERSION}/index.json\">"
            f"Open v{SCHEMA_VERSION} database index</a></p>",
            encoding="utf-8",
        )
        if output.exists():
            shutil.rmtree(output)
        temporary.replace(output)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "build"))
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--compat-dir", type=Path, help="alternate compat directory (useful for examples/tests)")
    parser.add_argument("--output", type=Path, default=Path("dist"))
    args = parser.parse_args(argv)
    root = args.root.resolve()
    compat_dir = args.compat_dir
    if compat_dir is not None and not compat_dir.is_absolute():
        compat_dir = root / compat_dir
    try:
        database = load_database(root, compat_dir)
        if args.command == "build":
            output = args.output if args.output.is_absolute() else root / args.output
            protected = {root, (root / "compat").resolve(), (root / "presets").resolve()}
            if output.resolve() in protected:
                raise ValidationError(f"refusing to replace protected path: {output}")
            compile_database(database, output)
            print(f"built {len(database['games'])} game(s) in {output}")
        else:
            print(f"valid: {len(database['games'])} game(s), "
                  f"{len(database['core_presets'])} SoC preset(s), "
                  f"{len(database['fex_presets'])} FEX preset(s)")
    except ValidationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
