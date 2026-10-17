Recorded conflict resolutions, in the layout of git's own `rr-cache`. Each
directory is one conflict, named by a hash of its conflicting hunks, holding
what the file looked like mid-conflict (`preimage`) and once resolved
(`postimage`).

`tooling/builds.py assemble` copies them into the repository it merges in, and
git replays any that match. Add to them with `tooling/builds.py record`, as
described in the README at the root of this branch. A resolution stops matching
once either side of the conflict changes, and is then simply never used again,
so stale ones are harmless; delete them whenever convenient.
