# Agent guide: AoW4 Tome Docs

You're helping an Age of Wonders 4 mod author make Steam Workshop images and a
description for their tome mod. Windows only.

## Ground rules

- **Capturing moves the user's mouse.** Never run `preview`, `capture` or `run`
  until the user has the game on the main menu and has said go. Tell them how
  long it takes (~10 s for preview, ~30 s per tome for capture). `check`,
  `compose`, `describe` and `init` don't touch input and are always safe.
- Look at the results (open the PNGs, read the description) before reporting
  back, and show the user what was produced.

## Workflow

1. Setup (once): `pip install -r requirements.txt`
2. Create a project from the mod folder (reads `Language/EN/*.po` to find tomes):
   `python tomedocs.py init "<mod folder>"` -> `projects/<name>.json`
3. Ask for / fill in per-tome settings in that JSON (see below), especially
   `icon_folder`.
4. User starts the game, goes to the main menu. Run `python tomedocs.py check`
   (passive: finds the window, warns if screenshots are black = fullscreen).
5. Optional: `python tomedocs.py preview <name>` lists what each page offers to
   capture. Confirm with the user, add `subtooltips` they want.
6. `python tomedocs.py run <name>` = capture + compose + describe.
   Re-capture a few skills only: `capture <name> --tome X --only "Skill A,Skill B"`.
   Rebuild without the game: `compose <name>`, `describe <name>`.
7. Review the results, fix things up, report. Layout:
   - `output/<name>/<Tome> - Overview.png`, `<Tome> - Tooltips.png`
   - `output/<name>/<Mod> - Description (structured|compact).txt` - one
     description for the whole mod, every captured tome, lowest tier first
   - `output/<name>/_captures/<tome>/` - working files (page shot, tooltip
     crops, icon snapshots, manifest.json); `compose`/`describe` rebuild from these.
   - `X` in descriptions = values the game computes that the .po files don't
     have (mostly the Ascension skill) - ask the user.
8. **Always offer a second pass.** Show the user the results, then ask what to
   tweak - in particular which nested tooltips to add. `describe` prints
   "Possible sub-tooltips" (mod-defined names linked inside each tooltip);
   suggest those. Add the chosen ones to `subtooltips`, then re-capture only
   what changed: `capture <name> --tome X --only "Parent skill"` followed by
   `compose` and `describe` (ask for go first - it moves the mouse).

## Project settings (`projects/<name>.json`)

| Key | Meaning |
|---|---|
| `output_size` | Image size, default `[1920, 1080]`; `null` = game resolution. |
| `description_style` | `structured` (nested lists) or `compact` (one line per skill). Both files are always written. |
| `tomes[].icon_folder` | The mod's icon PNGs. Matched to skills by **picture** (vs. the in-game icon), or by name for text links. |
| `tomes[].icons` | Manual picks: `{"Skill name": "file.png"}`. |
| `tomes[].subtooltips` | Nested tooltips: `[{"parent": "Skill name", "link": "Link text inside its tooltip"}]`. Stacked under the parent. |
| `tomes[].hide_in_tooltips_image` | Extra skills to leave out of the Tooltips image (units are always left out). |
| `tomes[].skip` | Names on the page not to hover. |
| `tomes[].extra_hovers` | Base-game names on the page to capture too (only the mod's own names are hovered by default). |

## How it works (for debugging)

- `tomedocs/capture.py` – navigation: main-menu "i" button -> Tomes tab ->
  search box -> result -> page. Button images in `templates/`; the UI scale is
  measured from them. Each run saves `page.png` and `manifest.json` per tome.
- `tomedocs/locate.py` – finds skills on the page: OCR'd labels that match a
  name from the mod's .po files (stale .po entries never appear on the page, so
  they're ignored); icon = circle above the label, else it's a text link.
- `tomedocs/tooltips.py` – tooltip = difference between frames with and
  without hover, snapped to the tooltip's border line.
- `tomedocs/background.py` – removes the encyclopedia UI: mirrored opposite
  side, Poisson-blended; plain background for the Tooltips image.
- `tomedocs/describe.py` – OCR of tooltips -> BBCode; Ascension from the .po.
- If navigation breaks after a game update, the usual fix is re-cutting
  `templates/info_button.png` / `back_button.png` from a 1920x1080 screenshot.
