# Nerves — PyAutoNerves

**What it owns:** the configuration and serialization layer that connects the
organism's conventions to every scientific library. It ships as the
`autonerves` package: layered config with overrides, the workspace↔library
version handshake, `test_mode`, and FITS/JSON I/O. PyAutoFit, PyAutoArray,
PyAutoGalaxy and PyAutoLens all import it as their base layer.

**Repo:** [PyAutoLabs/PyAutoNerves](https://github.com/PyAutoLabs/PyAutoNerves)
· live board: <https://pyautolabs.github.io/PyAutoNerves/>

The repo was renamed from PyAutoConf, and its package from `autoconf` to
`autonerves`. Older code and notes may still use the old names.

## The defining function: connecting

Nerves carry signals from one part of the body to another. This organ does the
same for conventions: a setting written once in a workspace's config reaches
every library that reads it, and the version handshake tells a workspace
straight away when it is talking to a library it was not written for.

## An organ that is also a library

Most organs own state or effects and leave libraries alone. Nerves is the
exception: it is an organ that also supplies a library package. The
[responsibility roles](https://github.com/PyAutoLabs/PyAutoBrain/blob/main/ORGANISM.md#responsibility-roles)
in ORGANISM.md describe this directly: roles are responsibilities, not levels
in a tree, so one repo can carry both.

This is also where new config surfaces go. The organism's growth rule says new
configuration or signalling belongs in Nerves, not in a new organ.

## Its neighbours

- **DNA** records which software stacks are specified, tested and installed;
  Nerves enforces compatibility at runtime through the version handshake.
- **Heart** checks version skew across repos as part of its readiness verdict.
  Nerves catches a mismatch at runtime; Heart catches it before a release.

## For an adopter

Nerves sits outside the framework/instance split described in
{doc}`../concepts/organism`: it is neither framework you fork nor state you
recreate. You need it only if your own libraries want a shared config and
serialization layer. If they do, the `autonerves` package is the pattern to
follow: one base layer every library imports, with configuration declared in
files rather than scattered through code.
