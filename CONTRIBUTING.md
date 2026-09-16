# Contributing
## No-code contribution

Open the guided
[game report form](https://github.com/armada-os/armada-compat/issues/new?template=game-report.yml).
Exact device/runtime details and honest failure reports are more useful than a
large log dump. Do not include account details, tokens, or other secrets.

## Pull request contribution

With Python 3.11 or newer, create a new game or SoC profile:

```bash
python3 tools/new_game.py APPID "Game name" SOC --runtime proton
```

Valid runtimes are `proton`, `slr`, `native`, and `wine`. Proton scaffolds use
ARM64 Experimental by default; use `--proton-architecture x86_64` and
`--proton-version 9 --proton-variant ge` for GE-Proton 9. Edit the generated
profile using the comments in the file, then run:

```bash
python3 tools/compatdb.py validate
python3 -m unittest discover -s tests
```

A non-`untested` result needs a matching `[[reports]]` entry. Include only
settings you actually needed. Keep unrelated games and preset changes out of
the pull request.

The pull request template contains the full review checklist. Contributions
are licensed under GPL-2.0-or-later.
