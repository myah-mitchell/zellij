# Fork branches and local releases

This is a fork of [zellij-org/zellij](https://github.com/zellij-org/zellij). It
exists both to contribute changes back upstream and to run builds that upstream
has not shipped. Those two purposes pull in opposite directions: contributions
need a history identical to upstream's, while running your own build needs
commits upstream does not have. The branch layout below keeps them apart.

## The branches

**`main`** is a mirror of `upstream/main` and nothing else. No fork-only commit
ever lands here. Keeping it byte-identical to upstream is what makes a pull
request from this fork show only the change it proposes.

**`fork-tooling`** holds the fork's own files and nothing else: this document,
the release and sync workflows, and `cliff-fork.toml`. It is branched from
`main` and never proposed upstream. A change to the fork's tooling is made here,
then merged into `main-local` like any other branch.

**Work branches** are branched from `main`, one per change you intend to
propose. Because they start from an exact copy of upstream, the pull request
they open contains only their own commits.

**`main-local`** is the integration branch, and holds no commits of its own. It
is `main` with a merge of `fork-tooling` and a merge of each work branch you
want to run before upstream accepts it. It is merged *into*, never branched
*from*. Everything on it is a merge, so it can be thrown away and rebuilt from
its parts at any time (see [Rebuilding main-local](#rebuilding-main-local)).

```
upstream/main ──▶ main ──┬──▶ work branch ──▶ PR to zellij-org/zellij
                         │         │
                         ├──▶ fork-tooling
                         │         │
                         │         ▼
                         └──▶ main-local ──▶ fork-v* tag ──▶ fork release
                          (main + a merge of fork-tooling
                           and of each work branch to run)
```

**`main-window`** is a second integration branch, built the same way as
`main-local` but on upstream's `zellij-window` branch
([zellij-org/zellij#5652](https://github.com/zellij-org/zellij/pull/5652), the
native window frontend) instead of on `main`. It exists to run that branch
before upstream merges it, together with this fork's work. It is
`upstream/zellij-window` with a merge of `fork-tooling` and a merge of each
work branch to run, and it is released from `window-v*` tags.

```
upstream/zellij-window ──▶ main-window ──▶ window-v* tag ──▶ window release
                    (+ a merge of fork-tooling
                     and of each work branch to run)
```

Work branches are still branched from `main`, so merging one into
`main-window` also brings in whatever `main` has that `zellij-window` does not
yet. That is where conflicts come from, and they are resolved in the merge
commit as with `main-local`. Once upstream merges `zellij-window`, its window
work arrives in `main` and `main-local`, and `main-window` can be retired.

## Syncing from upstream

`.github/workflows/sync-upstream.yml` runs daily at 06:00 UTC, and on demand
from the Actions tab. It fast-forwards `main` to `upstream/main` and does
nothing else. It never forces, so it fails rather than rewriting anything.
A failed run means one of two things, and the run's summary and error say which:

- **The fast-forward was refused.** Something has been committed to `main` that
  upstream does not have. Move it to `fork-tooling` or a work branch, then
  reset `main` to `upstream/main`.
- **The push was refused for want of the workflow scope.** See below.

### Letting upstream's workflow changes through

The token GitHub gives a workflow run may not push a commit that adds or changes
anything under `.github/workflows/`, and no entry in a `permissions:` block can
grant that. Zellij edits its own workflow files every few weeks, so those syncs
fail while every other sync succeeds.

A GitHub App installed on this fork can push them. It needs two repository
permissions: **Contents: write** to move `main` at all, and **Workflows: write**
for the commits that touch those files. Workflows is a separate permission and
is off by default, so an app that already syncs fine on ordinary days can still
fail on these.

Give the workflow the app by setting two repository secrets under Settings,
Secrets and variables, Actions:

- `SYNC_APP_ID`, the app's ID
- `SYNC_APP_PRIVATE_KEY`, the app's private key

With them unset the workflow falls back to the built-in token.

The token minted from the app lasts an hour and is revoked when the job ends,
which is why an app is preferable to a personal access token here. A fine
grained personal access token with the same two permissions works if you would
rather not install an app, but it is tied to a person's account and lives until
it expires.

Without either, the sync still works most days. It just stops on the days
upstream touches a workflow, and `main` has to be fast-forwarded by hand that
once, with the commands under "To sync by hand" below.

Using an app has one visible side effect. GitHub starts no workflow run for a
push made with the built-in token, but it does for one made with an app token,
so from then on each sync that moves `main` also starts a run of the inherited
`rust.yml` against upstream's commits. That is a duplicate of what upstream
already ran, and it can be turned off by disabling those workflows on this fork
under Actions.

`main-local` and `main-window` are deliberately left alone by that job. Merging `main` into it is
the one step that can conflict, exactly when upstream lands a change the fork
already carries, and that is a decision to make rather than something to
discover from a failed overnight run. Each run's summary says whether
`main-local` has fallen behind `main`, and whether `main-window` has fallen
behind upstream's `zellij-window`. For `main-local` the merge is a two-line job:

```sh
git switch main-local && git fetch origin
git merge origin/main
```

The scheduled trigger is also why `main-local` is this fork's default branch:
GitHub only runs `schedule` workflows from the default branch, and the sync
workflow is a fork-only file that must never land on `main`. Setting it is a
one-time change under Settings, Branches, Default branch on the fork. Until it
is set, the sync runs only when started by hand.

To sync by hand, upstream is a second remote, added once per clone:

```sh
git remote add upstream https://github.com/zellij-org/zellij.git
git fetch upstream
git switch main && git merge --ff-only upstream/main
```

### Where upstream's tags come from

This fork keeps none of upstream's tags. Its tag list holds fork releases alone,
which is what makes the release page readable, and it means no `v*.*.*` tag ever
exists here for the inherited `release.yml` to fire on.

They are still needed when a release's notes are written, since the tag before a
build is what says which commits are new, and for a first fork release that tag
is an upstream one. The release workflow fetches them from upstream when it
builds:

```sh
git fetch --no-tags https://github.com/zellij-org/zellij.git "+refs/tags/*:refs/tags/*"
```

They live in that runner for the length of the job and are pushed nowhere.
zellij-org/zellij is public, so this needs no token and nothing has to be set up
before the first release. The same command is how you get them into a local
clone if you want to read the history against them.

Copying them into the fork under a second name was tried first and does not
work. A push is refused for want of the workflow permission whenever the commits
it carries contain anything under `.github/workflows/`, whichever ref namespace
it targets, and upstream has had workflow files since `v0.5.1`, so 74 of its 78
tags were rejected. Fetching at build time avoids the problem rather than
demanding a permission for it.

### When upstream lands something the fork already has

Once a work branch's pull request is accepted, upstream's copy of that change
arrives through the sync above, while `main-local` still carries the copy merged
in earlier. Git compares content, not pull request numbers, so what happens next
depends only on whether the two copies produced the same text:

- Identical content merges silently. Nothing to do.
- Content that drifted apart, because the change was squashed, reformatted or
  revised during review, raises a conflict on the affected lines. Resolve it in
  favour of upstream's version. Staying aligned with upstream is the point of
  the sync, and the fork's copy has served its purpose.

When the conflicts are large, which is likely when review reshaped the change,
skip the merge and rebuild `main-local` without that work branch instead.

For `main-window` it is the same with upstream's branch:

```sh
git switch main-window && git fetch upstream
git merge upstream/zellij-window
```

### Rebuilding main-local

Because `main-local` is only merges, it can be rebuilt from scratch whenever
merging `main` into it gets awkward: after a work branch lands upstream in a
different shape, or when a branch is dropped. Start from `main` and merge back
in only what should still be there:

```sh
git fetch origin
git switch -C main-local origin/main
git merge --no-ff origin/fork-tooling
git merge --no-ff origin/feat/some-work-branch   # one per branch still unmerged upstream
```

A work branch that was written against an older `main` can conflict here, or
compile cleanly and still be wrong where upstream reshaped the code around it.
Resolve that in the merge commit and run `cargo xtask test` before pushing. The
same resolution is what the branch's pull request will need when it is rebased,
so it is worth noting there.

Pushing the result replaces the branch's history, so it needs
`git push --force-with-lease origin main-local`. Earlier fork releases keep
their own history reachable through their tags.

`main-window` is rebuilt the same way from upstream's branch:

```sh
git fetch origin && git fetch upstream
git switch -C main-window upstream/zellij-window
git merge --no-ff origin/fork-tooling
git merge --no-ff origin/feat/some-work-branch
git push --force-with-lease origin main-window
```

## Cutting a local release

Releases are built by `.github/workflows/release-local.yml`, which runs on
pushed tags matching `fork-v*` or `window-v*`. The prefix picks the branch the
tag must be on:

| Tag | Branch | Built from |
|---|---|---|
| `fork-v*` | `main-local` | upstream `main` plus fork work |
| `window-v*` | `main-window` | upstream `zellij-window` plus fork work |

```sh
git switch main-local
git push origin main-local          # push the branch before the tag
git tag -a fork-v0.1.0 -m "fork-v0.1.0"
git push origin fork-v0.1.0
```

A `main-window` build is the same with `main-window` and a `window-v` tag.
Both lines publish the same artifact names, so the tag on the release page is
what tells them apart.

The workflow checks the tag, runs the tests on Linux and on Windows, and only if
both pass builds two binaries:

| Target | Built with | Published as |
|---|---|---|
| `x86_64-unknown-linux-musl` | `cargo xtask ci cross` on Linux | `zellij-x86_64-unknown-linux-musl.tar.gz` |
| `x86_64-pc-windows-msvc` | `cargo xtask ci build-release` on Windows | `zellij-x86_64-pc-windows-msvc.zip` |

Each comes with a matching `.sha256sum`. These are the same commands and
targets upstream uses for its own artifacts. Windows cannot be cross-compiled
from Linux the way musl is, so it is built natively, with the C runtime linked
statically (`+crt-static`) so that `zellij.exe` runs without the Visual C++
redistributable. Only once both builds succeed does the publish job create the
release on this fork, with notes generated by `git-cliff`, so a release never
goes out with one platform missing.

The artifacts carry upstream's own naming, so they drop into anything that
already unpacks a zellij release. The notes are what say this is a fork build
and name the exact commit it came from, since the release page is all the
context a reader gets.

Each checksum covers the archive under its bare name, so verifying a download is
`sha256sum -c zellij-x86_64-unknown-linux-musl.sha256sum` in the directory both
files landed in. On Windows without a `sha256sum`, compare the hash in the file
with `Get-FileHash zellij-x86_64-pc-windows-msvc.zip`. Upstream's own releases hash the unpacked binary at its build
path instead, so the two files are not interchangeable.

The notes cover the commits since the previous release with the same prefix,
so a `window-v` build is compared with the last `window-v` build and never with
a `fork-v` one. When there is none, they cover the commits since the newest
upstream release the build descends from. That range is worked out by walking
the history rather than by asking `git-cliff` for the latest tag: the fork's
tags and upstream's sit on branches that diverged, so ordering them by date
interleaves them, and a release would re-list everything the one before it
already shipped.

Only those two targets are built. Upstream's release covers six targets in both
web and no-web variants plus a Windows MSI installer, which is a long and
expensive run for builds you install on a couple of machines. The MSI is left
out on purpose: it uses upstream's product codes, so installing it would replace
an upstream install rather than sit beside it. Adding a target means adding an
entry to the build job's matrix and its files to the publish step.

### Trying a build without releasing it

The workflow can also be started by hand from the Actions tab, on any branch.
That run tests and builds exactly as a release would and keeps both archives as
artifacts on the run's page, but skips the tag check and publishes nothing. Use
it to try a change to the workflow, or a branch that has not been built on
Windows before, without spending a version number on a release that fails.

Because those notes make a claim about where the code came from, the workflow
checks the claim before building. It requires the tagged commit to be contained
in the line's branch (`origin/main-local` or `origin/main-window`) and *not*
contained in `origin/main`. That rejects the
two ways of tagging something that is not a fork build: a commit that never
reached `main-local`, such as an unmerged work branch or a `main-local` that was
never pushed, and a commit on `main`, which mirrors upstream and carries no fork
work at all.

A tag that fails the check is already on the remote, since pushing a tag always
succeeds and only the workflow run fails. Remove it before retrying:

```sh
git push --delete origin fork-v0.1.0
git tag -d fork-v0.1.0
```

### Naming a release

The `major.minor` part follows the workspace version in `Cargo.toml`, which is
what the binary reports for `zellij --version`. Upstream bumps that ahead of the
matching release, so it names a version upstream has not tagged yet: while this
was written the crates said `0.46.0` and upstream's newest tag was `v0.45.1`.

The patch is the fork's own build counter against that base, not upstream's
patch number. `fork-v0.46.0` and `fork-v0.46.1` are two builds of the same
`0.46.0` tree carrying different amounts of fork work. When a sync moves the
workspace version on, the next build takes the new `major.minor` and starts
counting from zero again.

Reading a version number is never the reliable way to tell what a build
contains. That is recorded where it cannot go stale: the commit named on the
release page, and the range of commits the notes cover.

`window-v` tags follow the same scheme, with their own counter: the first
build is `window-v0.46.0` whatever number the `fork-v` series has reached.

Any tag starting with `fork-v` or `window-v` triggers the workflow, so the
scheme is a convention rather than something enforced.

### Why the tag prefix

`main-local` inherits upstream's `.github/workflows/release.yml`, which triggers
on `v*.*.*` tags. A tag named `v0.46.0` would therefore start two release runs
competing to publish the same tag. The `fork-v` and `window-v` prefixes match only the local
release workflow's filters, which leaves upstream's file untouched and free to
merge cleanly on every sync.

Keeping upstream's tags out of this fork means no `v*.*.*` tag is expected to
exist here at all, so the prefix is the second of two defences rather than the
only one. It still matters: it is what makes tagging one by hand harmless.

Upstream's `release.yml` can also be started by hand from the Actions tab, where
it builds every target and opens a draft release named `Release main`. That is
upstream's process, not this one. Do not run it here.

## What CI runs, and what it does not

Upstream's `rust.yml` and `e2e.yml` both trigger on `branches: [main]` only.
Neither runs for a commit on `main-local` or `main-window`, and neither runs for
a tag push. In practice a push to either branch gets no CI at all.

That is why `release-local.yml` carries its own test job rather than relying on
an existing one: a workflow cannot gate another workflow, so tests that decide
whether a release is published have to live inside the release workflow. It runs
what upstream's `rust.yml` runs on the two platforms it builds for: the whole
`cargo xtask test` on Linux, and on Windows the library tests of `zellij-utils`,
`zellij-server` and `zellij-client` without default features. That Windows set
is what upstream keeps passing there, so a failure in it is a real regression
rather than upstream code that was never meant to pass on Windows. macOS is not
tested, since nothing is built for it.

Work you intend to propose upstream still gets the full suite: it runs on the
pull request, against upstream's own matrix, once the branch is opened there.
