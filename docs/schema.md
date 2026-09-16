# Source schema v1

All source files use UTF-8. Dates use TOML local dates (`2026-09-16`), not
quoted locale-specific strings. Unknown top-level tables are rejected so that a
typo cannot silently become a recommendation.

## `game.toml`

```toml
schema_version = 1

[game]
id = 123456
name = "Example Game"
store = "steam"
```

`game.id` must match its decimal directory name. Schema v1 supports Steam IDs;
`store` is explicit so another identity namespace can be added without
reinterpreting existing IDs. Optional fields are `slug`, `homepage`, and
`aliases` (an array of strings).

## `general.toml`

This file is optional. It contains settings that are reasonable on every SoC
entry for the game. SoC files override it table-by-table and key-by-key.

```toml
schema_version = 1

[settings.environment]
SOME_GAME_OPTION = "1"
```

It deliberately contains no compatibility status. A working result is always
specific to a target and evidence.

## `<soc>.toml`

```toml
schema_version = 1

[target]
soc = "sm8550"

[[compatibility]]
runtime = "proton"
proton-architecture = "arm64"
proton-version = "experimental"
proton-variant = "steam"
default = true
status = "playable"
confidence = "community"
notes = "Short, actionable caveat."

[settings.cpu]
preset = "big"
wine_topology = true
nice = 0

[settings.fex]
preset = "standard"

[[reports]]
runtime = "proton"
proton-architecture = "arm64"
proton-version = "experimental"
proton-variant = "steam"
tested_at = 2026-09-16
distro = "Example Linux"
distro_version = "1.0"
device = "Example Handheld"
tester = "github-handle"
notes = "What was actually tested."
```

`target.soc` must match the filename. Optional `target.devices` restricts a
result to device IDs; omit it for an SoC-wide result.

Each `[[compatibility]]` result names the active launch route: `proton`, `slr`,
`native`, or `wine`. A target may contain multiple results when its outcome
differs between Proton and the Steam Linux Runtime.

A Proton result requires `proton-architecture`, `proton-version`, and
`proton-variant`. Architecture is `"arm64"` or `"x86_64"` and describes the
Proton tool build, not the Windows game's architecture:

- `arm64` is an ARM64/ARM64EC Proton build, identified on current builds by a
  `files/bin-arm64` directory; and
- `x86_64` is a conventional Proton build whose host components also require
  translation on an ARM64 system.

`proton-version` is a release track: a major version such as `"9"` or `"11"`,
or the moving `"experimental"`/`"hotfix"` tracks. It deliberately excludes
minor and package versions. For example:

```toml
[[compatibility]]
runtime = "proton"
proton-architecture = "x86_64"
proton-version = "9"
proton-variant = "steam"
default = true
status = "playable"
confidence = "community"

[[compatibility]]
runtime = "proton"
proton-architecture = "x86_64"
proton-version = "11"
proton-variant = "steam"
status = "boots"
confidence = "experimental"
```

`proton-variant` identifies the build family. Reuse the portable identifiers
`steam`, `ge`, and `cachyos`; future variants use a stable lowercase identifier
rather than a package name or tool ID. Exact names such as `GE-Proton9-27`
belong in report evidence.

The same target may therefore record separate results for architectures,
release tracks, and variants. One playable or verified result may set
`default = true`. Consumers first look for that exact combination. When it is
not installed, they can prefer another explicitly tested playable or verified
result—for example a `steam` result with the same architecture and release—or
ask the user before trying an untested substitution. Explicit user choices are
never overwritten. A distro or tool manager owns installed-tool discovery and
mapping; the database does not encode package names or installation methods.

Compatibility statuses are:

- `untested`: a target placeholder, not a compatibility claim;
- `broken`: does not reach usable gameplay;
- `boots`: starts, but has significant blockers;
- `playable`: usable with documented caveats; and
- `verified`: works well and has repeatable evidence.

Confidence is `experimental`, `community`, or `maintainer`. Every status except
`untested` requires at least one report. A report records evidence, not
telemetry; avoid personal data beyond an optional public handle.

Reports require the same `runtime` field as their result. Proton reports also
require the matching `proton-architecture`, `proton-version`, and
`proton-variant`. Optional `runtime_name` and `runtime_version` fields record
the concrete Proton/SLR/Wine implementation and exact tested version as
evidence. Other optional report fields are `distro_version`, `tester`, and
`kernel`.

## Settings namespaces

Every settings table is optional. A consumer applies only keys it understands.

### `settings.launch`

- `exe-append`: either a string, meaning a Proton-only executable suffix, or a
  table containing both `proton` and `slr` suffixes;
  and
- `arguments`: an array of arguments appended to the launched game.

Arguments are an array rather than a shell string: `arguments = ["-vulkan",
"-novid"]`. A conditional replacement looks like this:

```toml
[settings.launch]
exe-append = "/../eldenring.exe" # shorthand for Proton/Windows
```

Or, when the game actually has distinct Windows and Linux/SLR launches:

```toml
[settings.launch]
exe-append = { proton = "/../eldenring.exe", slr = "/../native-game" }
```

Consumers pass each argument verbatim and must not evaluate it as shell text.
The scalar/table distinction is preserved in the generated API. An executable
suffix is data, not a command. Consumers ask Steam for the active compatibility
type. A scalar applies only to Proton; a table selects its `proton` or `slr`
member. The consumer normalizes the resulting path and must reject a result
that escapes the game install root. An unknown route leaves the selected
executable unchanged.

### `settings.cpu`

- `preset`: a name in `presets/core-pinning/<soc>.toml`; or
- `cores`: an explicitly ordered array of zero-based logical CPU IDs.

`preset` and `cores` are mutually exclusive. Optional fields are
`wine_topology` (boolean), `nice` (-20 through 19), and `scheduler` (portable
name such as `eevdf`, `lavd`, or `cosmos`). Ordering is significant because
Wine/FEX topology can expose CPUs in that order.

### `settings.fex`

- `preset`: basename of `presets/fex/<name>.json` (without `.json`);
- `overrides`: string-to-string FEX Config values; and
- `thunks`: table of thunk module names to booleans.

`overrides` is applied after the preset. The checked-in JSON files are kept in
FEX's native shape (`{"Config": {...}}`) to avoid a lossy translation.

### `settings.environment`

Keys are environment-variable names. Values are strings or `false`; `false`
means remove an inherited variable. Consumers should present this table before
applying it and must not treat values as shell source.

## Core-pinning presets

```toml
schema_version = 1

[soc]
id = "sm8550"
logical_cpus = 8

[presets.big]
description = "Performance and prime cores"
cores = [3, 4, 5, 6, 7]
```

Core IDs must be unique and within `logical_cpus`. Array order is preserved.
Preset names are API identifiers and should not be renamed casually.
