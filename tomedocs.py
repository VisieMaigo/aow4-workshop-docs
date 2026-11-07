"""AoW4 Tome Docs - Steam Workshop images and descriptions for Age of Wonders 4 tome mods.

  python tomedocs.py init "<mod folder>"         create a project from the mod's .po files
  python tomedocs.py check                       check the game window / screen setup (no input sent)
  python tomedocs.py preview <project> [--tome T]   list what would be captured (opens the pages, hovers nothing)
  python tomedocs.py capture <project> [--tome T] [--only "Skill A,Skill B"]
  python tomedocs.py compose <project> [--tome T]
  python tomedocs.py describe <project> [--tome T]
  python tomedocs.py run <project> [--tome T]    capture + compose + describe

Capture moves your mouse: start it with the game on the main menu and don't
touch the mouse/keyboard until it's done (about 30 s per tome).
"""
import argparse
import sys

from tomedocs import config


def cmd_init(args):
    path, tomes = config.init(args.mod_folder, args.name, args.language)
    print(f"Created {path}")
    print(f"Tomes found: {', '.join(tomes) or 'none - add them by hand'}")
    print("Optional: edit it to set icon_folder, subtooltips, hide_in_tooltips_image per tome.")
    print(f"Next: start the game, go to the main menu, then run:  python tomedocs.py run {path.stem}")


def cmd_check(args):
    from tomedocs.game import Game
    from tomedocs.locate import find_template
    game = Game()
    w, h = game.size
    device, mon = game.monitor()
    print(f"Game window: {w}x{h} on {device} (monitor {mon[2] - mon[0]}x{mon[3] - mon[1]} at {mon[0]},{mon[1]})")
    if game.looks_black():
        print("PROBLEM: screenshots come out black. Set Display Mode to Borderless or Windowed in the game settings.")
        return
    if w < 1280:
        print("Note: small window - text recognition works best at 1920x1080 or larger.")
    info = find_template(game.grab(), "info_button", region=(w * 0.8, 0, w, h * 0.1))
    if info:
        print(f"Main menu detected, UI scale {info[2]:.2f}. Ready to capture.")
    else:
        print("Main menu not detected - go to the main menu before capturing.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init", help="create a project for a mod")
    p.add_argument("mod_folder")
    p.add_argument("--name", help="project name (default: from the folder name)")
    p.add_argument("--language", default="EN")
    sub.add_parser("check", help="check the game window and screen setup")
    for name in ("preview", "capture", "compose", "describe", "run"):
        p = sub.add_parser(name)
        p.add_argument("project")
        p.add_argument("--tome", action="append", help="only this tome (partial name; repeatable)")
        if name in ("capture", "run"):
            p.add_argument("--only", help="comma-separated skill names to re-capture (others kept)")
    args = ap.parse_args()

    if args.cmd == "init":
        return cmd_init(args)
    if args.cmd == "check":
        return cmd_check(args)
    cfg = config.load(args.project)
    tomes = config.pick_tomes(cfg, args.tome)
    if args.cmd == "preview":
        from tomedocs.capture import capture
        return capture(cfg, tomes, preview=True)
    if args.cmd in ("capture", "run"):
        from tomedocs.capture import capture
        capture(cfg, tomes, [s.strip() for s in args.only.split(",")] if args.only else None)
    captured = [t for t in tomes if (config.tome_dir(cfg, t) / "manifest.json").exists()]
    for t in tomes:
        if t not in captured:
            print(f"[{t['name']}] not captured yet - skipped (run: capture {cfg['name']} --tome \"{t['name']}\")")
    if args.cmd in ("compose", "run"):
        from tomedocs.compose import compose
        for t in captured:
            print(f"[{t['name']}]")
            compose(cfg, t)
    if args.cmd in ("describe", "run"):
        # The description covers the whole mod, so it uses every captured tome.
        everything = [t for t in cfg["tomes"] if (config.tome_dir(cfg, t) / "manifest.json").exists()]
        if everything:
            from tomedocs.describe import describe
            describe(cfg, everything)


if __name__ == "__main__":
    sys.exit(main())
