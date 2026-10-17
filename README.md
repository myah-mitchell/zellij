# zellij fork tooling

This is a fork of [zellij-org/zellij](https://github.com/zellij-org/zellij).
This branch, `fork-tooling`, is the repository's default branch and holds only
the fork's own tooling. It shares no history with zellij, and none of zellij's
source lives here.

| File | What it does |
|---|---|
| `builds.toml` | Says what to build and release. Editing it cuts releases. |
| `tooling/builds.py` | Assembles a build from its config, and records conflict resolutions |
| `rerere/` | Recorded conflict resolutions, replayed when a stack is assembled |
| `.github/workflows/builds.yml` | Assembles, tests, compiles and publishes what `builds.toml` describes |
| `.github/workflows/sync-upstream.yml` | Fast-forwards `main` to upstream's `main`, weekly and before every build |
| `cliff-fork.toml` | `git-cliff` config for release notes |

It is the default branch because GitHub runs scheduled workflows, and offers
the "Run workflow" button, only from the default branch's workflow files.
Keeping them here means they live in one place instead of being merged into
every branch that gets built.

## Branches

- **`main`** mirrors upstream's `main` exactly, so a pull request cut from it
  shows only its own change. Nothing else is ever committed to it.
- **`build/<name>`** is what the build of that name was last assembled into.
  The workflow rewrites it on every build, so check it out to run or inspect
  a build, never to commit to.
- **Work branches** (`feat/*`, `fix/*`) are cut from `main` and named in a
  build's `stack` to be included in it.
- **`archive/*`** branches are finished work kept for reference. A ruleset
  stops them being changed or deleted. `archive/fork-tooling` holds this
  branch's history from before it was split off from zellij's.
- **`main-local`** is `main` plus the fork's work, merged by hand, from before
  `builds.toml` existed. It is frozen, and will be archived once the new system
  has published a release.

## Builds

Each `[build.<name>]` table in `builds.toml` is one series of releases: a base,
a stack of branches merged onto it in order, and a tag pattern. The comments at
the top of the file list every key.

```toml
[build.fork]
tag = "fork-v{version}"
version = "0.46.3"
base = "upstream:main"
stack = ["feat/my-change", "upstream:pull/5714"]
```

A ref is `upstream:<branch>`, `upstream:pull/<number>` for an upstream pull
request as its author last pushed it, or a branch of this fork.

### Cutting a release

Edit `builds.toml` and push it to `fork-tooling`. The push builds every table
that changed and publishes each one whose tests and builds all pass. To release
a new version of `fork`, bump its `version`; to try an upstream pull request,
add it to a stack, or add a new table for it.

A table whose tag already exists is skipped rather than rebuilt, so a release
is never overwritten. Bump `version` to release again. A tag with `{date}` in
it gets `.2`, `.3` and so on for a second build the same day.

### Trying a build without releasing it

Actions, Builds, Run workflow. Name the builds (or leave `all`) and leave
"Publish releases" off. The run assembles, tests and compiles, pushes the
result to `build/<name>`, and keeps the archives on the run's page, under
Artifacts, for 90 days. Nothing is tagged, so a table builds even when its version is already
released, which lets you try a stack change before bumping it.

GitHub wraps each archive in a zip of its own. To fetch them from a terminal
instead, unwrapped:

```sh
gh run download <run id> -R myah-mitchell/zellij -p 'fork--*'
```

To assemble one on your own machine, from a checkout of this branch:

```sh
python3 tooling/builds.py assemble fork --repo /path/to/your/zellij/clone
```

It fetches the refs into `refs/fork-builds/` of that clone, merges in a new
worktree, and prints where. Nothing is pushed.

### When a stack conflicts

The build fails, and the run's log names the files. To resolve it once and
have every later build reuse the resolution:

```sh
python3 tooling/builds.py assemble <name> --repo /path/to/your/zellij/clone
# resolve the files in the worktree it names, as for any merge
python3 tooling/builds.py record --worktree <that worktree>
git add rerere && git commit -m "Record resolution for <name>" && git push
```

`record` saves git's own rerere records under `rerere/`, and `assemble` hands
them back to git before merging. A resolution keeps working as long as the
conflict looks the same, so it outlives small changes elsewhere in the files.
If both sides change the conflicting lines, it stops matching, the build fails
again, and you record a new one.

A branch that upstream has since merged is reported in the run's summary as
already in the base. Drop it from the stack when convenient.

## What a release contains

| Archive | For |
|---|---|
| `zellij-x86_64-unknown-linux-musl.tar.gz` | Any Linux. Static, so it cannot open `zellij window`. |
| `zellij-x86_64-unknown-linux-gnu.tar.gz` | Linux with glibc 2.39 or newer (Ubuntu 24.04, Debian 13). Use this one for `zellij window`, including under WSLg. |
| `zellij-x86_64-pc-windows-msvc.zip` | Windows. `zellij.exe`, and `zellij-window.exe` when the build has it. |

A build makes all three unless its `targets` in `builds.toml` names fewer;
`nightly` makes only the musl one. Each comes with a `.sha256sum`. The release notes list the base and every
stacked ref with the commit each was at, then the conventional commits since
the previous release with the same tag prefix. A series' first release covers
everything since the upstream release its base descends from.

A build is only published when all of its archives exist, and each archive only
exists if its platform's tests passed. Linux runs the whole `cargo xtask test`;
Windows runs the library tests of `zellij-utils`, `zellij-server` and
`zellij-client`, which is what upstream keeps passing there. Upstream's own
`rust.yml` and `e2e.yml` run on `main` only, so they never see a build.

## Tag prefixes

Every tag starts with a fixed prefix (`fork-v`, `nightly-v`), and that prefix
names the series. Upstream's `release.yml`, which every build carries, triggers
on `v*.*.*`; a prefixed tag never matches it, so a fork release cannot start a
competing upstream release. Upstream's own tags are not stored in this fork for
the same reason. The publish job fetches them into the runner when it needs one
for release notes.

Do not run upstream's `release.yml` from the Actions tab here. It builds a
draft release named `Release main`, by upstream's process rather than this one.

## Syncing from upstream

`sync-upstream.yml` fast-forwards `main` to upstream every Monday, and
`builds.yml` runs it first, so `main` is current whenever something is built.
It only ever fast-forwards, and fails loudly if `main` has something upstream
does not.

The built-in workflow token may not push commits that change anything under
`.github/workflows/`, and upstream edits its workflows every few weeks. So both
workflows push with a token minted from a GitHub App installed on this fork,
with **Contents: write** and **Workflows: write**. Its client ID (from the
app's settings page, not the numeric app ID) and private key are the
repository secrets `AUTOMATION_APP_CLIENT_ID` and `AUTOMATION_APP_PRIVATE_KEY`.
The token lasts an hour and is revoked when the job ends.

A push made with an app token starts workflows, so each sync that moves `main`
also runs upstream's `rust.yml` on it. That duplicates upstream's own run and
can be turned off by disabling those workflows here.

To sync by hand:

```sh
git remote add upstream https://github.com/zellij-org/zellij.git   # once
git fetch upstream
git switch main && git merge --ff-only upstream/main && git push origin main
```
