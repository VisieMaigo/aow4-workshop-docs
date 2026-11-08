"""AoW4 Tome Docs - Steam Workshop images and descriptions for Age of Wonders 4 tome mods.

  python tomedocs.py init "<mod folder>"         create a project from the mod's .po files
  python tomedocs.py check                       check the game window / screen setup (no input sent)
  python tomedocs.py preview <project>           list what would be captured (opens the pages, hovers nothing)
  python tomedocs.py capture <project> [--only "Skill A,Skill B"]
  python tomedocs.py compose <project>
  python tomedocs.py describe <project>
  python tomedocs.py run <project>               capture + compose + describe

All of them take --tome T / --unit U (partial names, repeatable) to limit the
run; naming only tomes leaves units out and vice versa.

Capture moves your mouse: start it with the game on the main menu and don't
touch the mouse/keyboard until it's done (about 30 s per tome or unit).
"""
import argparse
import sys

from tomedocs import config


def cmd_init(args):
    path, tomes, units = config.init(args.mod_folder, args.name, args.language)
    print(f"Created {path}")
    print(f"Tomes found: {', '.join(tomes) or 'none - add them by hand'}")
    print(f"Units found: {', '.join(units) or 'none - add them by hand'}")
    print("Optional: edit it to set icon_folder and subtooltips per tome, and form (racial units) per unit.")
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
        p.add_argument("--unit", action="append", help="only this unit (partial name; repeatable)")
        if name in ("capture", "run"):
            p.add_argument("--only", help="comma-separated skill names to re-capture (others kept)")
    args = ap.parse_args()

    if args.cmd == "init":
        return cmd_init(args)
    if args.cmd == "check":
        return cmd_check(args)
    cfg = config.load(args.project)
    tomes, units = config.pick(cfg, args.tome, args.unit)
    if args.cmd == "preview":
        from tomedocs.capture import capture
        return capture(cfg, tomes, units, preview=True)
    if args.cmd in ("capture", "run"):
        from tomedocs.capture import capture
        capture(cfg, tomes, units, [s.strip() for s in args.only.split(",")] if args.only else None)

    def done(item, folder):
        return (folder(cfg, item) / "manifest.json").exists()

    for kind, items, folder in (("tome", tomes, config.tome_dir), ("unit", units, config.unit_dir)):
        for x in items:
            if not done(x, folder):
                print(f"[{x['name']}] not captured yet - skipped (run: capture {cfg['name']} --{kind} \"{x['name']}\")")
    if args.cmd in ("compose", "run"):
        from tomedocs.compose import compose, compose_unit
        for t in tomes:
            if done(t, config.tome_dir):
                print(f"[{t['name']}]")
                compose(cfg, t)
        for u in units:
            if done(u, config.unit_dir):
                print(f"[{u['name']}]")
                compose_unit(cfg, u)
    if args.cmd in ("describe", "run"):
        # The description covers the whole mod, so it uses everything captured.
        all_tomes = [t for t in cfg["tomes"] if done(t, config.tome_dir)]
        all_units = [u for u in cfg["units"] if done(u, config.unit_dir)]
        if all_tomes or all_units:
            from tomedocs.describe import describe
            describe(cfg, all_tomes, all_units)


if __name__ == "__main__":
    sys.exit(main())
