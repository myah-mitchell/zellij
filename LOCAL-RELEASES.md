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

**`main-local`** is the integration branch. It carries `main` plus every
fork-only commit: this document, the local release workflow, and any work that
is finished enough to run but not yet accepted upstream. It is merged *into*,
never branched *from* for upstream work. Its history is expected to diverge from
upstream permanently.

**Work branches** are branched from `main`, one per change you intend to
propose. Because they start from an exact copy of upstream, the pull request
they open contains only their own commits. A work branch you also want to run
locally gets merged into `main-local` as well, which is what puts it into a
local release without entangling it with the fork's tooling commits.

```
upstream/main ──▶ main ──┬──▶ work branch ──▶ PR to zellij-org/zellij
                         │         │
                         │         └──▶ merged into main-local (to run it)
                         └──▶ main-local ──▶ fork-v* tag ──▶ fork release
```

## Syncing from upstream

`.github/workflows/sync-upstream.yml` runs daily at 06:00 UTC, and on demand
from the Actions tab. It fast-forwards `main` to `upstream/main` and mirrors any
new upstream tags. It never forces, so it fails rather than rewriting anything.
A failed run means one of two things, and the run's summary and error say which:

- **The fast-forward was refused.** Something has been committed to `main` that
  upstream does not have. Move it to `main-local`, then reset `main` to
  `upstream/main`.
- **The push was refused for want of the workflow scope.** See below.

### Letting upstream's workflow changes through

The token GitHub gives a workflow run may not push a commit that adds or changes
anything under `.github/workflows/`, and no entry in a `permissions:` block can
grant that. Zellij edits its own workflow files every few weeks, so those syncs
fail while every other sync succeeds.

To let them through, create a personal access token with the `workflow` scope
and add it to this fork as a repository secret named `SYNC_TOKEN`, under
Settings, Secrets and variables, Actions. The workflow uses it when it is
present and falls back to the built-in token when it is not.

Without that secret the sync still works most days. It just stops on the days
upstream touches a workflow, and `main` has to be fast-forwarded by hand that
once, with the commands under "To sync by hand" below.

`main-local` is deliberately left alone by that job. Merging `main` into it is
the one step that can conflict, exactly when upstream lands a change the fork
already carries, and that is a decision to make rather than something to
discover from a failed overnight run. Each run's summary says whether
`main-local` has fallen behind, and the merge is a two-line job:

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

### Where upstream's tags live

Upstream's tags are mirrored to `refs/upstream-tags/*`, not `refs/tags/*`. They
are kept because `git-cliff` needs a previous tag to measure a release's notes
against, and hiding them from `refs/tags/` buys two things: this fork's tag list
shows its own releases rather than 76 of upstream's, and no `v*.*.*` tag ever
exists here for the inherited `release.yml` to fire on.

They are invisible to a normal `git fetch`. To read them:

```sh
git ls-remote origin | grep refs/upstream-tags/     # list them
git fetch origin "+refs/upstream-tags/*:refs/tags/*"  # fetch as local tags
```

The release workflow does that fetch itself before generating a changelog, so
nothing needs doing by hand for a release. Nothing is mirrored until the sync
workflow has run at least once, though, so run it once before cutting the first
release. Otherwise there is no earlier tag to measure against and the notes
cover the entire history of the project. The release run says so in a notice
when it happens.

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

A local commit whose content has landed upstream can then be dropped from
`main-local` entirely by rebasing the branch onto `main`. This is optional
housekeeping, worth doing when the same conflict keeps reappearing on later
syncs.

## Cutting a local release

Releases are built by `.github/workflows/release-local.yml`, which runs on
pushed tags matching `fork-v*`.

```sh
git switch main-local
git push origin main-local          # push the branch before the tag
git tag -a fork-v0.1.0 -m "fork-v0.1.0"
git push origin fork-v0.1.0
```

The workflow runs `cargo xtask test`, and only if that passes builds the
`x86_64-unknown-linux-musl` binary with `cargo xtask ci cross`, the same command
and target upstream uses for its own musl artifact. It publishes
`zellij-x86_64-unknown-linux-musl.tar.gz` and a matching `.sha256sum` as a
release on this fork, with notes generated by `git-cliff`.

The artifact carries upstream's own naming, so it drops into anything that
already unpacks a zellij release. The notes are what say this is a fork build
and name the exact commit it came from, since the release page is all the
context a reader gets.

The checksum covers the tarball under its bare name, so verifying a download is
`sha256sum -c zellij-x86_64-unknown-linux-musl.sha256sum` in the directory both
files landed in. Upstream's own releases hash the unpacked binary at its build
path instead, so the two files are not interchangeable.

The notes cover the commits since the previous fork release, or since the newest
upstream release the build descends from when there is no earlier fork build to
compare against. That range is worked out by walking the history rather than by
asking `git-cliff` for the latest tag: fork tags and mirrored upstream tags sit
on branches that diverged, so ordering them by date interleaves them, and a
release would re-list everything the one before it already shipped.

Only that one target is built. Upstream's release covers six targets in both
web and no-web variants plus a Windows installer, which is a long and expensive
run for a build you install on one machine. Adding a second target means giving
the release job a build matrix and uploading the extra file.

Because those notes make a claim about where the code came from, the workflow
checks the claim before building. It requires the tagged commit to be contained
in `origin/main-local` and *not* contained in `origin/main`. That rejects the
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

The number after `fork-v` is this fork's own, counted independently of
upstream's versions. It deliberately does not track the upstream version the
build sits on: a tag like `fork-v0.46.1` would come to mean something false the
moment upstream released its own 0.46.1. What the build is based on is recorded
where it cannot go stale, in the commit named on the release page and in the
range of commits the notes cover.

Any tag starting with `fork-v` triggers the workflow, so the scheme is a
convention rather than something enforced. A plain increasing series is enough:
bump the patch for a rebuild on the same upstream base, the minor when the fork
picks up a new upstream release.

### Why the tag prefix

`main-local` inherits upstream's `.github/workflows/release.yml`, which triggers
on `v*.*.*` tags. A tag named `v0.46.0` would therefore start two release runs
competing to publish the same tag. The `fork-v` prefix matches only the local
release workflow's filter, which leaves upstream's file untouched and free to
merge cleanly on every sync.

Mirroring upstream's tags out of `refs/tags/` means no `v*.*.*` tag is expected
to exist on this fork at all, so the prefix is now the second of two defences
rather than the only one. It still matters: it is what makes tagging one by hand
harmless.

Upstream's `release.yml` can also be started by hand from the Actions tab, where
it builds every target and opens a draft release named `Release main`. That is
upstream's process, not this one. Do not run it here.

## What CI runs, and what it does not

Upstream's `rust.yml` and `e2e.yml` both trigger on `branches: [main]` only.
Neither runs for a commit on `main-local`, and neither runs for a tag push. In
practice a push to `main-local` gets no CI at all.

That is why `release-local.yml` carries its own test job rather than relying on
an existing one: a workflow cannot gate another workflow, so tests that decide
whether a release is published have to live inside the release workflow. It runs
`cargo xtask test` on Linux, which is the same job upstream's `rust.yml` runs,
without the macOS and Windows matrix that a Linux-only fork build does not need.

Work you intend to propose upstream still gets the full suite: it runs on the
pull request, against upstream's own matrix, once the branch is opened there.
