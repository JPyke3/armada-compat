<p align="center">
  <a href="https://armadaos.dev/">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset=".github/assets/armada-mark-white.svg">
      <img src=".github/assets/armada-mark-black.svg" alt="Armada" width="112">
    </picture>
  </a>
</p>

<h1 align="center">Armada Compatibility Database</h1>

<p align="center"><strong>Community-tested game profiles for ARM Linux handhelds</strong></p>

<p align="center">
  Find working settings for your games or share what worked on your device.
  The data is open, distro-neutral, and designed for both people and tools.
</p>

<p align="center">
  <a href="https://github.com/armada-os/armada-compat/actions/workflows/compat-database.yml"><img alt="Validation status" src="https://github.com/armada-os/armada-compat/actions/workflows/compat-database.yml/badge.svg?branch=main"></a>
  <a href="https://armadaos.dev/"><img alt="Armada documentation" src="https://img.shields.io/badge/docs-armadaos.dev-18181a?style=flat"></a>
  <a href="LICENSE.md"><img alt="GPL-2.0-or-later license" src="https://img.shields.io/badge/license-GPL--2.0--or--later-18181a?style=flat"></a>
  <a href="https://discord.gg/HdmdSxTD5S"><img alt="Discord community" src="https://img.shields.io/badge/chat-Discord-5865F2?style=flat&amp;logo=discord&amp;logoColor=white"></a>
</p>

<p align="center">
  <a href="https://github.com/armada-os/armada-compat/issues/new?template=game-report.yml"><strong>Report a game</strong></a>
  ·
  <a href="CONTRIBUTING.md">Contribute a profile</a>
  ·
  <a href="docs/schema.md">Profile reference</a>
  ·
  <a href="https://armadaos.dev/">Armada</a>
</p>

## About

The Armada Compatibility Database collects settings that make PC games work
well on ARM Linux handhelds. Profiles are grouped by Steam App ID and SoC so
results can be reviewed, updated, and shared across distros without waiting for
an operating-system release.

Profiles never overwrite an explicit Steam compatibility-tool choice. They can
recommend a Proton architecture, release track, and variant—such as ARM64 Steam
Experimental or x86_64 GE-Proton 9—as a safe default when Steam has no user
choice. Alternate tested results give clients graceful fallbacks when that
variant is unavailable. Exact tool IDs remain evidence rather than permanent
pins. Steam Linux Runtime, native Linux, and Wine results are independent.

## Get a game supported

You do not need to write TOML or code. Open a
[game compatibility report](https://github.com/armada-os/armada-compat/issues/new?template=game-report.yml),
fill in what you tested, and a maintainer can turn it into a profile.

Please include:

- the game name and App ID shown on [SteamDB](https://steamdb.info/);
- your device and SoC;
- whether Steam used ARM64 Proton, x86_64 Proton, or the Steam Linux Runtime;
- the Proton variant, major version/track, and exact tool version, when applicable;
- what worked, what did not, and any required settings; and
- the distro, runtime version, and date tested.

## Contribute a profile

With Python 3.11 or newer, create the required files with one command:

```console
$ python3 tools/new_game.py 1245620 "ELDEN RING" sm8550 --runtime proton
```

Edit the generated SoC file, remove its `TODO` values, and validate it:

```console
$ python3 tools/compatdb.py validate
```

For an existing game, the same command adds a new SoC without touching other
profiles. It refuses to overwrite files. The
[exhaustive fictional example](examples/database/compat/123456) covers every
field and both mutually exclusive forms such as named/manual cores,
route-mapped/scalar executables, and ARM64/x86_64 Proton. For individual field
rules, read the [profile reference](docs/schema.md).

## Repository layout

```text
compat/<steam-app-id>/
  game.toml        # game name and Steam ID
  general.toml     # optional settings shared by all SoCs
  <soc>.toml       # result, settings, and test evidence

presets/core-pinning/<soc>.toml
presets/fex/{standard,fast,compat}.json
```

## Development

The validator has no third-party dependencies and GitHub Actions checks every
pull request:

```console
$ python3 tools/compatdb.py validate
$ python3 -m unittest discover -s tests
$ python3 tools/compatdb.py build --output dist
```

The build produces a versioned JSON API for websites and distro clients:

```text
/db/v1/index.json
/db/v1/steam/<app-id>.json
/db/v1/presets/...
```

TOML remains the contributor-facing source; generated files are never
committed.

## Community

Issues and pull requests are welcome. Use the
[guided game report](https://github.com/armada-os/armada-compat/issues/new?template=game-report.yml)
for compatibility results or ask for help in the
[Armada Discord community](https://discord.gg/HdmdSxTD5S).

## Credits

Compatibility data is contributed by the ARM Linux gaming community. The
Armada logo was created by [Rax](https://github.com/Raxcoms).

## License

Source data and repository tooling are licensed under
**GPL-2.0-or-later**. See [LICENSE.md](LICENSE.md).
