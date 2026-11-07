# AoW4 Tome Docs

Steam Workshop images and descriptions for **Age of Wonders 4 tome mods**,
captured straight from the game's encyclopedia:

- **`<Tome> - Overview.png`** – the tome page as shown in game, side panel blended away
- **`<Tome> - Tooltips.png`** – every skill tooltip with your icon art beside it
  (units are left out – they deserve their own images)
- **`<Mod> - Description (structured).txt` / `(compact).txt`** – a BBCode draft
  for the Workshop page, covering all the mod's tomes (lowest tier first)

The tool drives the game itself: opens the encyclopedia from the main menu,
searches each tome, reads the page to find the skills and hovers each one.

## How to use it

Open an AI coding agent (Claude Code, Copilot, Codex, ...) in this folder and
tell it what you want, e.g.:

> Make workshop images and a description for my mod in
> `C:\...\Age of Wonders 4\Mods\My Tome Mod`. My icons are in `C:\Mod Graphics\My Tome`.

The agent follows [AGENTS.md](AGENTS.md). You only need to:

1. Have **Python 3.10+** installed.
2. Start the game (**Display Mode: Borderless or Windowed**, English, mod
   enabled) and stay on the **main menu**.
3. When the agent asks, **let go of the mouse** for ~30 seconds per tome
   while it captures.

Prefer doing it by hand? See the commands in [AGENTS.md](AGENTS.md).

Finished files land in `output/<project>/` (working files in its `_captures`
folder). The description is a draft - give it a read.
