"""Command line interface: ``anchor-paradox run | report | validate | traits``."""
from __future__ import annotations

import argparse
import glob
import sys
from typing import List, Optional


def _expand(patterns: List[str]) -> List[str]:
    """Expand globs to the files that actually exist.

    A pattern that matches nothing expands to nothing (it is NOT passed through as a
    literal path, which used to turn a typo into ``OSError [Errno 22]``).
    """
    paths: List[str] = []
    for pattern in patterns:
        paths.extend(sorted(glob.glob(pattern)))
    return paths


def _no_matches(patterns: List[str]) -> int:
    print(f"anchor-paradox: no files matched: {' '.join(patterns)}", file=sys.stderr)
    return 2


def _cmd_run(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    from .traits import TRAITS, get_traits

    # Validate the requested traits BEFORE any weights are downloaded or loaded:
    # a typo in a disposition name must not cost a full model download.
    valid = [t.name for t in TRAITS]
    unknown = [n for n in (args.traits or []) if n not in valid]
    if unknown:
        parser.error(f"unknown trait(s): {', '.join(unknown)}; choose from: {', '.join(valid)}")
    traits = get_traits(args.traits)

    try:
        from .model import LM
    except ModuleNotFoundError as exc:                # pragma: no cover - defence in depth
        return _missing_extra(exc)
    try:
        lm = LM(args.model, device=args.device, dtype=args.dtype, batch_size=args.batch_size,
                revision=args.revision)
    except ModuleNotFoundError as exc:
        if _torch_package(exc) is None:
            raise
        return _missing_extra(exc)

    if args.layer is not None and not 0 <= args.layer < lm.num_layers:
        parser.error(f"--layer {args.layer} is out of range for this model "
                     f"(0 <= layer < {lm.num_layers})")

    from .profile import render_markdown, save_profile
    from .protocol import AnchorProtocol, ProtocolConfig

    config = ProtocolConfig(layer=args.layer, meta=not args.no_meta, transfer=not args.no_transfer)
    profile = AnchorProtocol(lm, config, traits).run()
    save_profile(profile, args.out)
    print()
    print(render_markdown([profile]))
    print(f"Anchor Profile written to {args.out}")
    return 0


def _torch_package(exc: ModuleNotFoundError) -> Optional[str]:
    """The optional runtime dependency named by an import error, if it is one we ship."""
    name = (getattr(exc, "name", "") or "").split(".")[0]
    return name if name in {"torch", "transformers", "accelerate", "safetensors"} else None


def _missing_extra(exc: ModuleNotFoundError) -> int:
    name = _torch_package(exc) or "torch"
    print(f"anchor-paradox: 'run' needs the optional runtime extra ({name} is not installed); "
          f'install it with: pip install "anchor-paradox[run]"', file=sys.stderr)
    return 2


def _cmd_report(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    from .profile import load_profile, render_markdown
    paths = _expand(args.profiles)
    if not paths:
        return _no_matches(args.profiles)
    status = 0
    for path in paths:
        try:
            print(render_markdown([load_profile(path)]))
        except Exception as exc:                       # one bad file must not kill the batch
            status = 1
            print(f"✗ {path}: {type(exc).__name__}: {exc}", file=sys.stderr)
    return status


def _cmd_validate(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    from .profile import load_profile, validate_profile
    paths = _expand(args.profiles)
    if not paths:
        return _no_matches(args.profiles)
    status = 0
    for path in paths:
        try:
            profile = load_profile(path)
        except Exception as exc:
            status = 1
            print(f"✗ {path}: {type(exc).__name__}: {exc}")
            continue
        problems = validate_profile(profile)
        if problems:
            status = 1
            print(f"✗ {path}")
            for problem in problems:
                print(f"    {problem}")
        else:
            print(f"✓ {path}")
    return status


def _cmd_traits(_: argparse.Namespace, __: argparse.ArgumentParser) -> int:
    from .traits import TRAITS
    for t in TRAITS:
        print(f"{t.name:<20} {t.role:<17} {t.description}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    from . import __version__

    parser = argparse.ArgumentParser(
        prog="anchor-paradox",
        description="Measure what it costs to remove a disposition from an AI system (the Anchor Protocol).")
    parser.add_argument("--version", action="version", version=f"anchor-paradox {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run the Anchor Protocol and write an Anchor Profile")
    run.add_argument("--model", required=True, help="Hugging Face model id or local path")
    run.add_argument("--out", required=True, help="output path of the Anchor Profile (JSON)")
    run.add_argument("--revision", help="model revision / commit to pin")
    run.add_argument("--layer", type=int, help="decoder layer for the state surface (default: middle)")
    run.add_argument("--traits", nargs="*", help="target dispositions to measure (controls always included)")
    run.add_argument("--no-meta", action="store_true", help="skip second-order steerability")
    run.add_argument("--no-transfer", action="store_true", help="skip the transfer phase")
    run.add_argument("--batch-size", type=int, default=16)
    run.add_argument("--device", help="cuda, cpu, mps (default: auto)")
    run.add_argument("--dtype", default="auto", help="auto, float16, bfloat16, float32")
    run.set_defaults(func=_cmd_run)

    report = sub.add_parser("report", help="render one or more Anchor Profiles as Markdown")
    report.add_argument("profiles", nargs="+")
    report.set_defaults(func=_cmd_report)

    validate = sub.add_parser("validate", help="check that Anchor Profiles are well-formed")
    validate.add_argument("profiles", nargs="+")
    validate.set_defaults(func=_cmd_validate)

    traits = sub.add_parser("traits", help="list the dispositions measured")
    traits.set_defaults(func=_cmd_traits)

    args = parser.parse_args(argv)
    return args.func(args, parser)


if __name__ == "__main__":
    sys.exit(main())
