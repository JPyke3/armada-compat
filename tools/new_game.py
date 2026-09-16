#!/usr/bin/env python3
"""Create a minimal game/SoC profile without overwriting existing data."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import tomllib
from pathlib import Path


SOC_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
RUNTIMES = ("proton", "slr", "native", "wine")
PROTON_ARCHITECTURES = ("arm64", "x86_64")
PROTON_VERSION = re.compile(r"^(?:[1-9][0-9]*|experimental|hotfix)$")
PROTON_VARIANT = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def toml_string(value: str) -> str:
    # JSON strings are valid TOML basic strings for the characters accepted here.
    return json.dumps(value, ensure_ascii=False)


def create_profile(
    root: Path,
    appid: int,
    name: str,
    soc: str,
    runtime: str,
    proton_architecture: str = "arm64",
    proton_version: str = "experimental",
    proton_variant: str = "steam",
) -> list[Path]:
    if appid <= 0:
        raise ValueError("Steam app ID must be a positive integer")
    if not name.strip():
        raise ValueError("game name cannot be empty")
    soc = soc.lower()
    if not SOC_NAME.fullmatch(soc):
        raise ValueError("SoC must be an identifier such as sm8550")
    if runtime not in RUNTIMES:
        raise ValueError(f"runtime must be one of: {', '.join(RUNTIMES)}")
    if proton_architecture not in PROTON_ARCHITECTURES:
        raise ValueError(
            f"Proton architecture must be one of: {', '.join(PROTON_ARCHITECTURES)}"
        )
    if not PROTON_VERSION.fullmatch(proton_version):
        raise ValueError(
            "Proton version must be a major release such as '9', or 'experimental'/'hotfix'"
        )
    if not PROTON_VARIANT.fullmatch(proton_variant):
        raise ValueError("Proton variant must be a lowercase identifier such as steam or ge")
    preset_file = root / "presets" / "core-pinning" / f"{soc}.toml"
    if not preset_file.is_file():
        supported = sorted(path.stem for path in preset_file.parent.glob("*.toml"))
        suffix = f"; available: {', '.join(supported)}" if supported else ""
        raise ValueError(f"unsupported SoC {soc!r}{suffix}")

    game_dir = root / "compat" / str(appid)
    game_file = game_dir / "game.toml"
    target_file = game_dir / f"{soc}.toml"
    if target_file.exists():
        raise FileExistsError(f"refusing to overwrite {target_file}")

    game_dir.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    if game_file.exists():
        try:
            with game_file.open("rb") as source:
                existing = tomllib.load(source).get("game", {})
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ValueError(f"cannot read existing {game_file}: {exc}") from exc
        if existing.get("id") != appid or existing.get("name") != name.strip():
            raise ValueError(
                f"existing metadata is {existing.get('name')!r} ({existing.get('id')}); "
                "use its exact SteamDB name and App ID"
            )
    else:
        game_file.write_text(
            "schema_version = 1\n\n"
            "[game]\n"
            f"id = {appid}\n"
            f"name = {toml_string(name.strip())}\n"
            'store = "steam"\n',
            encoding="utf-8",
        )
        created.append(game_file)

    proton_compatibility = (
        f'proton-architecture = {toml_string(proton_architecture)}\n'
        f'proton-version = {toml_string(proton_version)}\n'
        f'proton-variant = {toml_string(proton_variant)}\n'
        '# default = true # Only after a playable/verified test; never overrides user choice.\n'
        if runtime == "proton" else ""
    )
    proton_report = (
        f'# proton-architecture = {toml_string(proton_architecture)}\n'
        f'# proton-version = {toml_string(proton_version)}\n'
        f'# proton-variant = {toml_string(proton_variant)}\n'
        if runtime == "proton" else ""
    )
    target_file.write_text(
        "schema_version = 1\n\n"
        "[target]\n"
        f"soc = {toml_string(soc)}\n\n"
        "[[compatibility]]\n"
        f"runtime = {toml_string(runtime)}\n"
        f"{proton_compatibility}"
        'status = "untested" # TODO: broken, boots, playable, or verified\n'
        'confidence = "experimental"\n'
        'notes = "TODO: describe the result"\n\n'
        "# For a tested result, change the status and add evidence:\n"
        "# [[reports]]\n"
        f"# runtime = {toml_string(runtime)}\n"
        f"{proton_report}"
        f"# tested_at = {dt.date.today().isoformat()}\n"
        '# distro = "TODO"\n'
        '# device = "TODO"\n'
        '# notes = "TODO: what was tested"\n\n'
        "# Add only settings the game needs. See examples/database/compat/123456/.\n"
        "# [settings.cpu]\n"
        '# preset = "big"\n'
        "#\n"
        "# [settings.fex]\n"
        '# preset = "fast"\n',
        encoding="utf-8",
    )
    created.append(target_file)
    return created


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("appid", type=int, help="decimal Steam app ID")
    parser.add_argument("name", help="game name")
    parser.add_argument("soc", help="SoC identifier, for example sm8550")
    parser.add_argument("--runtime", choices=RUNTIMES, default="proton")
    parser.add_argument(
        "--proton-architecture",
        choices=PROTON_ARCHITECTURES,
        default="arm64",
        help="Proton tool build architecture; ignored for non-Proton runtimes",
    )
    parser.add_argument(
        "--proton-version",
        default="experimental",
        help="Proton major release or track, for example 9 or experimental",
    )
    parser.add_argument(
        "--proton-variant",
        default="steam",
        help="Proton distribution identifier, for example steam, ge, or cachyos",
    )
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        root = args.root.resolve()
        created = create_profile(
            root,
            args.appid,
            args.name,
            args.soc,
            args.runtime,
            args.proton_architecture,
            args.proton_version,
            args.proton_variant,
        )
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    for path in created:
        print(f"created {path.relative_to(root)}")
    print("next: edit the SoC file, remove TODOs, then run python3 tools/compatdb.py validate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
