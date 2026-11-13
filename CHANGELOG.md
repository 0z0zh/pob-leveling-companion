# Changelog / 更新履歴

All notable changes to this project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

このプロジェクトの主な変更点を記録しています。
書式は [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) に、バージョン番号は [セマンティック バージョニング](https://semver.org/lang/ja/) に準拠しています。

## [Unreleased]

## [0.1.1] - 2026-11-13

### 日本語
#### 追加
- GitHub Actions による exe の自動ビルド。タグを push するとリリースに exe と SHA-256 チェックサムを添付
- exe に製品名とバージョン情報を埋め込み (`VERSION` ファイルから生成)
- README にコード署名ポリシーを追加 (SignPath Foundation への申請準備)

#### 変更
- ビルドに使うライブラリのバージョンを `requirements-build.txt` で固定

### English
#### Added
- Automatic exe builds with GitHub Actions; pushing a tag attaches the exe and its SHA-256 checksum to the release.
- Product name and version metadata embedded in the exe (generated from the `VERSION` file).
- Code signing policy in the README (in preparation for applying to the SignPath Foundation).

#### Changed
- Build dependency versions pinned in `requirements-build.txt`.

## [0.1.0] - 2026-11-13

### 日本語

最初の公開版です。

#### 追加
- Path of Building のビルドのパッシブツリーとスキルジェムを1画面で表示 (アセンダンシー / ブラッドラインはツリーの下に表示)
- `Client.txt` を読み取り、レベルアップに合わせて Tree / Skill のセットを自動で切り替え (英語版・日本語版のゲームクライアントに対応)
- `1-11`、`Level 12-31`、`12 to 33`、`Lvl 90`、`68+` などのレベル範囲を含むセット名に対応
- 前のセットとの差分表示 (追加・削除されたノードとジェム)
- 現在の Act で入手できるジェム (クエスト報酬 / 購入) を、ゲーム内キャラクターのクラスに合わせて表示
- Act ごとのタイムを計るレベリングタイマー (既定は手動スタート、自動スタートも可能。ゲームを閉じていた時間は除外)
- PoB でビルドを保存すると自動で反映、PoB エクスポートコードの貼り付けにも対応
- デスクトップアプリ (`PoBLevelingCompanion.exe`) と「最前面」表示
- 日本語 / English の表示切替
- `Client.txt` の自動検出 (Steam / スタンドアロン / Epic)

### English

First public version.

#### Added
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

[Unreleased]: https://github.com/0z0zh/pob-leveling-companion/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/0z0zh/pob-leveling-companion/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/0z0zh/pob-leveling-companion/releases/tag/v0.1.0
