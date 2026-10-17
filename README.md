# zellij fork tooling

This is a fork of [zellij-org/zellij](https://github.com/zellij-org/zellij).
This branch, `fork-tooling`, is the repository's default branch and holds only
the fork's own tooling. It shares no history with zellij, and none of zellij's
source lives here.

| File | What it does |
|---|---|
| `.github/workflows/sync-upstream.yml` | Fast-forwards `main` to upstream's `main`, weekly and on demand |
| `.github/workflows/release-local.yml` | Tests, builds and publishes fork releases |
| `cliff-fork.toml` | `git-cliff` config for release notes |
| `LOCAL-RELEASES.md` | How the branches and releases fit together |

It is the default branch because GitHub runs scheduled workflows, and offers
the "Run workflow" button, only from the default branch's workflow files.
Keeping them here means they live in one place instead of being merged into
every branch that gets built.

## Branches

- **`main`** mirrors upstream's `main` exactly, so a pull request cut from it
  shows only its own change. Nothing else is ever committed to it.
- **`main-local`** is `main` plus the fork's work, and is what `fork-v*` tags
  are cut from. It is being replaced by a build system driven by a config file
  on this branch, and will be retired once that produces releases.
- **`archive/*`** branches are finished work kept for reference. A ruleset
  stops them being changed or deleted. `archive/fork-tooling` holds this
  branch's history from before it was split off from zellij's.

## Status

`LOCAL-RELEASES.md` still describes the `main-local` model, from before this
branch held only tooling. The `main-window` branch and its `window-v*` releases
it mentions have been retired, since upstream merged the window work into
`main`.
