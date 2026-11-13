# Changelog

All notable changes to this project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - not yet released

First public version.

### Added
- Passive tree and skill gems of a Path of Building build on one screen, with the ascendancy and bloodline below the tree.
- Automatic tree / skill set switching on level-up, read from `Client.txt` (English and Japanese game clients).
- Set names with level ranges such as `1-11`, `Level 12-31`, `12 to 33`, `Lvl 90` and `68+`.
- Diff against the previous set (added / removed nodes and gems).
- Gems obtainable in the current act (quest rewards / vendors) for the in-game character's class.
- Leveling timer with per-act splits; manual start by default, optional automatic start; time while the game is closed is excluded.
- Automatic reload when a build is saved in PoB; PoB export codes can be pasted.
- Desktop app (`PoBLevelingCompanion.exe`) with an "always on top" option.
- Japanese / English UI.
- Automatic detection of `Client.txt` (Steam, standalone and Epic installs).
