#!/usr/bin/env python3
"""Plans and assembles the builds described in builds.toml.

The same script runs in CI (.github/workflows/builds.yml) and locally, so a
stack that fails to merge in CI can be reproduced, resolved and recorded on
your own machine. Run it with --help, or see README.md.

Subcommands:

  plan       Decide which builds a workflow run should make.
  assemble   Merge one build's stack onto its base and print what came out.
  record     Save the conflict resolutions in a worktree so CI can replay them.

Python 3.11 or newer, standard library only.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

TOOLING = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = TOOLING / "builds.toml"
DEFAULT_RERERE = TOOLING / "rerere"

TRIGGERS = ("change", "nightly")
PLACEHOLDERS = {"upstream", "version", "date"}
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

# What builds.yml can compile, in the order it lists them. `bin` is where the
# binary lands, and `test` is the suite the job runs before building: Linux
# runs everything once, on whichever Linux target the build has first.
TARGETS = {
    "linux-musl": {
        "os": "ubuntu-latest",
        "triple": "x86_64-unknown-linux-musl",
        "bin": "target/x86_64-unknown-linux-musl/release",
        "test": "linux",
    },
    "linux-gnu": {
        "os": "ubuntu-latest",
        "triple": "x86_64-unknown-linux-gnu",
        "bin": "target/release",
        "test": "linux",
    },
    "windows": {
        "os": "windows-latest",
        "triple": "x86_64-pc-windows-msvc",
        "bin": "target/release",
        "test": "windows",
    },
}


class Fail(Exception):
    """An error meant for the reader, printed without a traceback."""


class AlreadyReleased(Exception):
    """The build's tag exists and cannot be renumbered."""


def git(*args: str, cwd: Path | str | None = None, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, text=True, capture_output=True
    )
    if check and result.returncode != 0:
        raise Fail(
            f"git {' '.join(args)} failed:\n{result.stderr.strip() or result.stdout.strip()}"
        )
    return result.stdout.strip()


def git_ok(*args: str, cwd: Path | str | None = None) -> bool:
    """Runs a git command that answers yes or no through its exit status."""
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True).returncode == 0


# Config


def load_config(text: str, source: str) -> dict[str, dict]:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise Fail(f"{source} is not valid TOML: {e}")
    builds = data.get("build", {})
    if not isinstance(builds, dict):
        raise Fail(f"{source}: [build] must be a table of [build.<name>] tables")
    for name, build in builds.items():
        validate(name, build, source)
    return builds


def validate(name: str, build: dict, source: str) -> None:
    where = f"{source}: [build.{name}]"
    if not NAME_RE.match(name):
        raise Fail(f"{where}: names are lowercase letters, digits and hyphens")
    known = {"tag", "base", "stack", "on", "version", "prerelease", "publish", "keep", "targets"}
    unknown = set(build) - known
    if unknown:
        raise Fail(f"{where}: unknown key(s) {', '.join(sorted(unknown))}")
    for key in ("tag", "base"):
        if not isinstance(build.get(key), str) or not build[key]:
            raise Fail(f"{where}: `{key}` is required")
    if not isinstance(build.get("stack", []), list) or not all(
        isinstance(s, str) for s in build.get("stack", [])
    ):
        raise Fail(f"{where}: `stack` is a list of refs")
    targets = build.get("targets", list(TARGETS))
    if (
        not isinstance(targets, list)
        or not targets
        or not all(t in TARGETS for t in targets)
        or len(set(targets)) != len(targets)
    ):
        raise Fail(f"{where}: `targets` is a non-empty list drawn from {', '.join(TARGETS)}")
    if build.get("on", "change") not in TRIGGERS:
        raise Fail(f"{where}: `on` is one of {', '.join(TRIGGERS)}")
    used = set(re.findall(r"\{([^}]*)\}", build["tag"]))
    if used - PLACEHOLDERS:
        raise Fail(
            f"{where}: unknown placeholder(s) in tag: {', '.join(sorted(used - PLACEHOLDERS))}"
        )
    if "version" in used and not isinstance(build.get("version"), str):
        raise Fail(f"{where}: the tag uses {{version}}, so `version` is required")
    if build.get("on", "change") == "nightly" and "date" not in used:
        raise Fail(f"{where}: a nightly build's tag needs {{date}} to stay unique")
    if "{" in build["tag"].split("{")[0] or not build["tag"].split("{")[0]:
        raise Fail(f"{where}: the tag must start with a fixed prefix, like `fork-v`")
    for ref in [build["base"], *build.get("stack", [])]:
        parse_ref(ref, where)


def build_targets(build: dict) -> list[dict]:
    """The build's targets as builds.yml's matrix wants them, in TARGETS order."""
    chosen = build.get("targets", list(TARGETS))
    out, tested = [], set()
    for name, target in TARGETS.items():
        if name not in chosen:
            continue
        test = target["test"] if target["test"] not in tested else ""
        tested.add(target["test"])
        out.append({"name": name, **target, "test": test})
    return out


def parse_ref(ref: str, where: str = "") -> tuple[str, str]:
    """Turns a config ref into (remote, refspec source).

    upstream:main         upstream's branch main
    upstream:pull/5652    upstream pull request 5652, as its author last pushed it
    feat/x, origin:feat/x this fork's branch feat/x
    """
    remote, sep, rest = ref.partition(":")
    if not sep:
        remote, rest = "origin", ref
    if remote not in ("origin", "upstream") or not rest:
        raise Fail(f"{where}: `{ref}` is not `branch`, `origin:branch`, `upstream:branch` or `upstream:pull/N`")
    m = re.fullmatch(r"pull/(\d+)", rest)
    if m:
        if remote != "upstream":
            raise Fail(f"{where}: `{ref}`: pull requests are taken from upstream")
        return remote, f"refs/pull/{m.group(1)}/head"
    return remote, f"refs/heads/{rest}"


# plan


def cmd_plan(args: argparse.Namespace) -> None:
    config = load_config(Path(args.config).read_text(), args.config)

    if args.event == "workflow_dispatch":
        wanted = [n.strip() for n in args.only.split(",") if n.strip()] or ["all"]
        if wanted == ["all"]:
            names = list(config)
        else:
            missing = [n for n in wanted if n not in config]
            if missing:
                raise Fail(f"no build named {', '.join(missing)} in {args.config}")
            names = wanted
    elif args.event == "schedule":
        names = [n for n, b in config.items() if b.get("on", "change") == "nightly"]
    elif args.event == "push":
        before = {}
        if args.before and set(args.before) != {"0"}:
            text = git("show", f"{args.before}:builds.toml", cwd=TOOLING, check=False)
            if text:
                before = load_config(text, f"builds.toml at {args.before[:9]}")
        names = [n for n, b in config.items() if before.get(n) != b]
        for n in before:
            if n not in config:
                print(f"{n}: removed from the config, nothing to build", file=sys.stderr)
    else:
        raise Fail(f"unknown event {args.event}")

    for n in names:
        print(f"{n}: will build", file=sys.stderr)
    print(json.dumps(names))


# assemble


def cmd_assemble(args: argparse.Namespace) -> None:
    config = load_config(Path(args.config).read_text(), args.config)
    if args.name not in config:
        raise Fail(f"no build named {args.name} in {args.config}")
    build = config[args.name]
    repo = Path(args.repo).resolve()
    common = Path(git("rev-parse", "--path-format=absolute", "--git-common-dir", cwd=repo))

    for remote in ("origin", "upstream"):
        if not git("remote", "get-url", remote, cwd=repo, check=False):
            raise Fail(f"{repo} has no `{remote}` remote")

    # Fetched under a namespace of their own, so nothing here moves a branch or
    # remote-tracking ref the reader has.
    refs = [build["base"], *build.get("stack", [])]
    resolved = []
    for i, ref in enumerate(refs):
        remote, src = parse_ref(ref)
        dst = f"refs/fork-builds/{args.name}/{i}"
        git("fetch", "--quiet", "--no-tags", remote, f"+{src}:{dst}", cwd=repo)
        resolved.append({"ref": ref, "sha": git("rev-parse", dst, cwd=repo)})
    base, stack = resolved[0], resolved[1:]

    rerere = Path(args.rerere)
    if rerere.is_dir():
        # Added to rather than replaced, so resolutions recorded locally but not
        # yet saved into the tooling are not thrown away.
        shutil.copytree(rerere, common / "rr-cache", dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("README.md"))

    worktree = Path(args.worktree) if args.worktree else Path(
        tempfile.mkdtemp(prefix=f"fork-build-{args.name}-")
    )
    if worktree.exists() and any(worktree.iterdir()):
        raise Fail(f"{worktree} is not empty")
    git("worktree", "add", "--quiet", "--detach", str(worktree), base["sha"], cwd=repo)
    print(f"{args.name}: {base['ref']} at {base['sha'][:9]}, in {worktree}", file=sys.stderr)

    rr = ["-c", "rerere.enabled=true", "-c", "rerere.autoUpdate=true"]
    for item in stack:
        if git_ok("merge-base", "--is-ancestor", item["sha"], "HEAD", cwd=worktree):
            print(f"  {item['ref']} ({item['sha'][:9]}) is already in the base; it can come out of the stack",
                  file=sys.stderr)
            item["merged"] = False
            continue
        msg = f"Stack {item['ref']} ({item['sha'][:9]}) onto {args.name}"
        merge = subprocess.run(
            ["git", *rr, "merge", "--quiet", "--no-ff", "--no-edit", "-m", msg, item["sha"]],
            cwd=worktree, text=True, capture_output=True,
        )
        if merge.returncode != 0:
            unmerged = git("diff", "--name-only", "--diff-filter=U", cwd=worktree).splitlines()
            if not unmerged and git_ok("rev-parse", "--verify", "--quiet", "MERGE_HEAD", cwd=worktree):
                git(*rr, "commit", "--quiet", "--no-edit", cwd=worktree)
                print(f"  {item['ref']}: conflicts resolved from recorded resolutions", file=sys.stderr)
            else:
                raise Fail(conflict_help(args, item, unmerged, worktree, merge.stderr))
        item["merged"] = True
        print(f"  merged {item['ref']} ({item['sha'][:9]})", file=sys.stderr)

    sha = git("rev-parse", "HEAD", cwd=worktree)
    upstream = workspace_version(worktree / "Cargo.toml")
    try:
        tag = choose_tag(build, upstream, args, repo)
        skip = ""
    except AlreadyReleased as e:
        tag, skip = "", str(e)
        print(f"{args.name}: {skip}", file=sys.stderr)

    result = {
        "name": args.name,
        "sha": sha,
        "tag": tag,
        "prefix": build["tag"].split("{")[0],
        "prerelease": bool(build.get("prerelease", build.get("on") == "nightly")),
        "publish": bool(build.get("publish", True)),
        "upstream_version": upstream,
        "targets": build_targets(build),
        "base": base,
        "stack": stack,
        "worktree": str(worktree),
        "skip": skip,
    }
    if tag:
        print(f"{args.name}: {sha[:9]}, would be tagged {tag}", file=sys.stderr)
    print(json.dumps(result))


def conflict_help(args, item, unmerged, worktree, stderr) -> str:
    files = "\n".join(f"    {f}" for f in unmerged) or "    (none listed)\n" + stderr
    head = (
        f"merging {item['ref']} ({item['sha'][:9]}) into build `{args.name}` conflicts in:\n"
        f"{files}\n\nNo recorded resolution covers it. "
    )
    record = (
        f"  python3 tooling/builds.py record --worktree {'<that worktree>' if os.environ.get('CI') else worktree}\n"
        f"then commit the new files under rerere/ to fork-tooling and push. Later builds\n"
        f"replay the resolution, for as long as the conflict looks the same."
    )
    if os.environ.get("CI"):
        return head + (
            f"To record one, on your own machine, from a fork-tooling checkout:\n"
            f"  python3 tooling/builds.py assemble {args.name} --repo <your zellij clone>\n"
            f"resolve the files in the worktree it names, then run\n" + record
        )
    return head + (
        f"The merge is left in progress in\n  {worktree}\n"
        f"Resolve the files there, then run\n" + record + "\n"
        f"Remove the worktree afterwards with `git worktree remove --force {worktree}`."
    )


def workspace_version(cargo_toml: Path) -> str:
    data = tomllib.loads(cargo_toml.read_text())
    version = data.get("workspace", {}).get("package", {}).get("version")
    if not isinstance(version, str):
        version = data.get("package", {}).get("version")
    if not isinstance(version, str):
        raise Fail(f"no version in {cargo_toml}")
    return version


def choose_tag(build: dict, upstream: str, args: argparse.Namespace, repo: Path) -> str:
    date = args.date or datetime.datetime.now(datetime.timezone.utc).strftime("%y%m%d")
    tag = build["tag"].format(upstream=upstream, version=build.get("version", ""), date=date)
    if not git_ok("check-ref-format", f"refs/tags/{tag}"):
        raise Fail(f"`{tag}` is not a valid tag name")
    existing = {
        line.split("refs/tags/", 1)[1].removesuffix("^{}")
        for line in git("ls-remote", "--tags", "origin", cwd=repo).splitlines()
    }
    if tag not in existing:
        return tag
    if "{date}" in build["tag"]:
        n = 2
        while f"{tag}.{n}" in existing:
            n += 1
        return f"{tag}.{n}"
    # Not an error: the first push of a config, or a change to some other key,
    # reaches here for a release that already went out. Reported, and the build
    # is left out of the run.
    raise AlreadyReleased(
        f"{tag} is already released. Bump `version` for this build in builds.toml "
        f"to cut a new one."
    )


# record


def cmd_record(args: argparse.Namespace) -> None:
    worktree = Path(args.worktree).resolve()
    if not git_ok("rev-parse", "--verify", "--quiet", "MERGE_HEAD", cwd=worktree):
        raise Fail(f"{worktree} is not in the middle of a merge, so there is nothing to record")
    # Resolved files may or may not be staged; what counts is that the working
    # tree no longer has conflict markers in it, since that is what rerere reads.
    unmerged = git("diff", "--name-only", "--diff-filter=U", cwd=worktree).splitlines()
    marked = [f for f in unmerged if has_markers(worktree / f)]
    if marked:
        raise Fail("these files still have conflict markers, resolve them first:\n"
                   + "\n".join(f"    {f}" for f in marked))
    # Records the resolution of every conflict in the worktree as it stands now.
    git("-c", "rerere.enabled=true", "rerere", cwd=worktree)
    common = Path(git("rev-parse", "--path-format=absolute", "--git-common-dir", cwd=worktree))
    cache = common / "rr-cache"
    dest = Path(args.rerere)
    saved = 0
    for entry in sorted(cache.iterdir()) if cache.is_dir() else []:
        # Only complete entries: a preimage with no postimage is a conflict that
        # was seen but never resolved, and replaying it would resolve nothing.
        if any(p.name.startswith("postimage") for p in entry.iterdir()):
            target = dest / entry.name
            if not target.exists():
                shutil.copytree(entry, target)
                saved += 1
                print(f"saved {entry.name}", file=sys.stderr)
    if not saved:
        print("nothing new to save", file=sys.stderr)
    else:
        print(f"\n{saved} resolution(s) saved under {dest}. Commit them to fork-tooling.",
              file=sys.stderr)


def has_markers(path: Path) -> bool:
    if not path.is_file():
        return False
    with path.open("rb") as f:
        return any(line.startswith((b"<<<<<<< ", b">>>>>>> ")) for line in f)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("plan", help="list the builds a workflow run should make, as JSON")
    p.add_argument("--event", required=True, choices=["push", "workflow_dispatch", "schedule"])
    p.add_argument("--before", default="", help="for push: the commit before the push")
    p.add_argument("--only", default="all", help="for workflow_dispatch: comma-separated names, or all")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("assemble", help="merge a build's stack and print the result as JSON")
    p.add_argument("name")
    p.add_argument("--repo", default=".", help="a zellij clone with `origin` and `upstream` remotes")
    p.add_argument("--worktree", help="where to assemble; a new temporary directory by default")
    p.add_argument("--rerere", default=str(DEFAULT_RERERE), help="recorded resolutions to replay")
    p.add_argument("--date", help="yymmdd to use for {date}; today, UTC, by default")
    p.set_defaults(func=cmd_assemble)

    p = sub.add_parser("record", help="save the conflict resolutions in a worktree")
    p.add_argument("--worktree", required=True)
    p.add_argument("--rerere", default=str(DEFAULT_RERERE), help="where to save them")
    p.set_defaults(func=cmd_record)

    args = parser.parse_args()
    try:
        args.func(args)
    except Fail as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
