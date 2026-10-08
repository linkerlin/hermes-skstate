"""Console entry: ``skstate``, ``python -m skstate``.

``skstate`` and ``skstate serve`` run the stdio MCP server.
``skstate setup`` wires one project into OpenCode or Codex.
``skstate status`` prints a human-readable Chinese summary.
``skstate hooks`` installs OpenCode or Codex session hooks under a project.
"""

from __future__ import annotations

import argparse
import json
import sys


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="skstate",
        description="SKILL.state MCP runtime. The host agent is the model.",
    )
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="Run the stdio MCP server")
    serve.add_argument("-v", "--verbose", action="store_true", help="Log to stderr")

    setup = sub.add_parser("setup", help="Wire one project into OpenCode or Codex")
    setup.add_argument("--platform", choices=["opencode", "codex"])
    setup.add_argument(
        "--project-dir",
        default=".",
        help="Project root that receives opencode.json or .codex/ (default: cwd)",
    )
    setup.add_argument("--uninstall", action="store_true", help="Remove what setup installed")
    setup.add_argument("--force", action="store_true", help="Overwrite an existing MCP entry")
    setup.add_argument(
        "--example",
        action="store_true",
        help="Also copy the shelf-demo example skill into skills/",
    )

    sub.add_parser("status", help="Print a human-readable status summary")

    skill = sub.add_parser("skill", help="Create or check skill files")
    skill_sub = skill.add_subparsers(dest="skill_command", required=True)
    skill_new = skill_sub.add_parser("new", help="Write a skill template")
    skill_new.add_argument("name")
    skill_new.add_argument("--project-dir", default=".")
    skill_new.add_argument("--force", action="store_true", help="Overwrite an existing skill")
    skill_check = skill_sub.add_parser("check", help="Print what the runtime reads")
    skill_check.add_argument("name", nargs="?", default="")

    sub.add_parser("doctor", help="Check that this install can run the hooks and the server")

    hook = sub.add_parser("hook", help="Run one session hook (called by the IDE)")
    hook.add_argument("event", choices=["session-start", "session-end"])

    hooks = sub.add_parser("hooks", help="Install or remove OpenCode and Codex session hooks")
    hooks.add_argument("--platform", choices=["opencode", "codex"])
    hooks.add_argument(
        "--project-dir",
        default=".",
        help="Project root that receives .opencode/ or .codex/ (default: cwd)",
    )
    hooks.add_argument("--uninstall", action="store_true", help="Remove skstate hooks")
    hooks.add_argument("--force", action="store_true", help="Rewrite managed hook files")
    return parser


def _setup(args: argparse.Namespace) -> None:
    from skstate.setup_cmd import setup_project, teardown_project

    project = args.project_dir or "."
    platform = args.platform or ""
    if platform not in {"opencode", "codex"} and not args.example:
        print("platform is required: opencode or codex", file=sys.stderr)
        raise SystemExit(2)
    result: dict = {}
    try:
        if platform in {"opencode", "codex"}:
            if args.uninstall:
                result = teardown_project(platform, project)
            else:
                result = setup_project(platform, project, force=args.force)
        if args.example and not args.uninstall:
            from skstate.examples import copy_example

            result["example"] = str(copy_example(project, force=args.force))
    except (ValueError, FileExistsError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def _skill(args: argparse.Namespace) -> None:
    from skstate.skill_cmd import check_skills, create_skill, format_check

    if args.skill_command == "new":
        try:
            target = create_skill(args.name, args.project_dir, force=args.force)
        except (ValueError, FileExistsError) as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(1) from exc
        print(f"已写入 {target}")
        return
    try:
        results = check_skills(args.name or "")
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    if not results:
        print("没有技能文件。")
        return
    failed = False
    for result in results:
        print(format_check(result))
        print()
        failed = failed or not result["ok"]
    if failed:
        raise SystemExit(1)


def _status() -> None:
    from skstate.status_cmd import format_status, status_report

    sys.stdout.write(format_status(status_report()) + "\n")


def _hooks(args: argparse.Namespace) -> None:
    from skstate.hooks.setup import hooks_status, install_hooks, uninstall_hooks

    project = args.project_dir or "."
    platform = args.platform or ""
    try:
        if args.uninstall:
            if platform not in {"opencode", "codex"}:
                print("platform is required for uninstall: opencode or codex", file=sys.stderr)
                raise SystemExit(2)
            result = uninstall_hooks(platform, project)
        elif platform:
            result = install_hooks(platform, project, force=args.force)
        else:
            result = hooks_status(project)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def _stdio_hint() -> None:
    """Only when a person runs us in a terminal. Never on a pipe or IDE stdio."""
    if not sys.stdin.isatty():
        return
    print("skstate 是 stdio MCP 服务，正在等待 IDE 连接。", file=sys.stderr)
    print("状态用 skstate status，接入用 skstate setup --platform opencode|codex", file=sys.stderr)


def _doctor() -> None:
    from skstate.doctor import doctor_report, format_doctor

    report = doctor_report()
    sys.stdout.write(format_doctor(report) + "\n")
    if not report["ok"]:
        raise SystemExit(1)


def _hook_event(event: str) -> None:
    """Compat-friendly entry: the hook modules keep their own entry points."""
    if event == "session-start":
        from skstate.hooks import session_start

        session_start.main()
    else:
        from skstate.hooks import session_end

        session_end.main()


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    if args.command == "setup":
        _setup(args)
        return
    if args.command == "status":
        _status()
        return
    if args.command == "skill":
        _skill(args)
        return
    if args.command == "doctor":
        _doctor()
        return
    if args.command == "hook":
        _hook_event(args.event)
        return
    if args.command == "hooks":
        _hooks(args)
        return
    _stdio_hint()
    from skstate.mcp_server import run_server

    run_server(verbose=bool(getattr(args, "verbose", False)))


if __name__ == "__main__":
    main()
