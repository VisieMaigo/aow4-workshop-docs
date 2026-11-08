# Agent guide: AoW4 Tome Docs

You're helping an Age of Wonders 4 mod author make Steam Workshop images and a
description for their tome mod - its tomes and its tome units. Windows only.

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
3. Ask for / fill in the settings in that JSON (see below): per tome especially
   `icon_folder`; per unit, for racial units, which `form` to show (Human by
   default - authors often prefer a non-human form). `init` lists the tomes and
   units it found in the .po files; check the lists with the user.
4. User starts the game, goes to the main menu. Run `python tomedocs.py check`
   (passive: finds the window, warns if screenshots are black = fullscreen).
5. `python tomedocs.py preview <name>` lists what each page offers to capture
   (~10 s per page). For **units, always ask which abilities to show**: preview
   lists every ability on the unit's card, marked attack / mod, with the
   default pick (attacks + the mod's own abilities). 3-5 per unit read best.
   Put the user's choice, in display order, in the unit's `abilities`. Also
   ask about `subtooltips` worth adding.
6. `python tomedocs.py run <name>` = capture + compose + describe.
   Re-capture a few skills only: `capture <name> --tome X --only "Skill A,Skill B"`.
   Rebuild without the game: `compose <name>`, `describe <name>`.
7. **Write the description yourself** from
   `output/<name>/_captures/description_facts.md`, following the style guide
   below, into `output/<name>/<Mod> - Description.txt` (`<Mod>` = mod folder name).
8. Review everything and report. Layout:
   - `output/<name>/<Tome> - Overview.png`, `<Tome> - Tooltips.png`
   - `output/<name>/<Unit>.png` - the unit page (model + stat card) with the
     chosen ability tooltips, shrunk, left of the model (and below it if needed)
   - `output/<name>/<Mod> - Description.txt` - one description for the whole
     mod, every captured tome, lowest tier first
   - `output/<name>/_captures/` - working files (page shots, tooltip crops,
     icon snapshots, manifests, description facts); `compose`/`describe`
     rebuild from these.
9. **Always offer a second pass.** Show the user the results, then ask what to
   tweak - in particular which nested tooltips to add. `describe` prints
   "Possible sub-tooltips" (mod-defined names linked inside each tooltip);
   suggest those. Add the chosen ones to `subtooltips`, then re-capture only
   what changed: `capture <name> --tome X --only "Parent skill"` followed by
   `compose` and `describe` (ask for go first - it moves the mouse).

## Writing the description

Players skim Workshop pages. Give each skill **one short line** with its gist -
the tooltip images carry the full detail.

```
[h2]<Tome> (Tier <N>)[/h2]
[i]<gameplay description>[/i]
[b]Initial bonus:[/b] <affinity>, <improvement>
[list]
[*][b]<Skill>[/b] — <Type>: <effect>
...
[*][b]Ascension: <Trait>[/b] — Ascension Skill: <what it grants>
[/list]
```

Tomes go lowest tier first; skills in page order, then Initial Bonus items,
then the Ascension skill. Then a `[h2]Units[/h2]` section, one entry per unit:

```
[*][b]<Unit>[/b] — Tier <N> <Role>: <one-line summary>
[list][*][b]<Ability>[/b]: <gist>[*]...[/list]
```

covering the captured abilities (attacks and the mod's own abilities), with the
same keep / leave-out rules as skills.

**Keep:** damage amounts and types, stat changes, the status effects inflicted
(by name), what is summoned or created, terrain changes, resource yields, and
for unit enchantments the eligible unit types in brackets at the end.

**Leave out:** casting costs, upkeep, requirements, turn durations, chance
percentages ("has a chance to inflict Chilled", not "a base 90% chance"),
"base", stacking notes, edge cases ("Effects are increased for Single Shot
attacks"), lore, and nested-tooltip details beyond the core effect.

**Check the facts.** Tooltip text is OCR: fix misreadings against the .po files
and base-game terms (e.g. "Ice Oueen" -> Ice Queen). If the .po text and the
in-game tooltip disagree, or something looks wrong (a missing number, a wrong
status), tell the user - it may be a bug in their mod. Ascension values marked
`X` come from the game, not the .po: ask the user for them.

By type:

| Type | Say |
|---|---|
| Unit | its class/role and a one-line summary - not its abilities |
| Unit Enchantment | what enchanted units gain (damage, statuses, resistances, immunities, auras) + (eligible types) |
| Damage / Debuff Spell | what it hits, damage type, statuses applied, how it spreads |
| Siege Project | what happens while it's active |
| Sustained City Spell | the ongoing effect on the domain |
| Summon Spell | what it summons |
| Terraforming Spell | damage dealt, terrain changes, units spawned |
| Combat Enchantment | the repeating or ongoing combat effect |
| Special Province Improvement | yields, adjacency bonuses, terrain changes, special effects |
| Ascension Skill | the trait name and everything it grants, in one line |

Examples:

```
[*][b]Frigid Imbuement[/b] — Unit Enchantment: Attacks deal +2 Frost Damage and have a chance to inflict Status Vulnerability (Battle Mage, Support, Magic Fighter, Ranged, Skirmisher).
[*][b]Frigid Presence[/b] — Unit Enchantment: Reduces the Frost Protection and Status Resistance of nearby enemy units (Shield, Polearm, Shock, Fighter, Magic Fighter).
[*][b]Cascading Chill[/b] — Damage/Debuff Spell: Deals 20 Frost Damage and has a chance to inflict Chilled, then cascades to adjacent enemies.
```

## Project settings (`projects/<name>.json`)

| Key | Meaning |
|---|---|
| `output_size` | Image size, default `[1920, 1080]`; `null` = game resolution. |
| `tomes[].icon_folder` | The mod's icon PNGs. Matched to skills by **picture** (vs. the in-game icon), or by name for text links. |
| `tomes[].icons` | Manual picks: `{"Skill name": "file.png"}`. |
| `tomes[].subtooltips` | Nested tooltips: `[{"parent": "Skill name", "link": "Link text inside its tooltip"}]`. Stacked under the parent. |
| `tomes[].hide_in_tooltips_image` | Extra skills to leave out of the Tooltips image (units are always left out). |
| `tomes[].skip` | Names on the page not to hover. |
| `tomes[].extra_hovers` | Base-game names on the page to capture too (only the mod's own names are hovered by default). |
| `units[].form` | Racial units: form to show, e.g. `"Orcoid"`. Empty = the game's default (Human). |
| `units[].abilities` | Abilities to capture, in display order, e.g. `["Frost Cloak", "Melee Strike"]`. Empty = attacks + the mod's own (.po-named) abilities. |
| `units[].subtooltips` | Nested tooltips inside ability tooltips, as for tomes. |
| `units[].page_image` | Own screenshot of the unit page (no tooltip open, same resolution) to use instead of the captured one - the model is animated, so this picks the pose. Then just `compose`. |
| `units[].rank_rewards` | Unit rank rewards to capture, e.g. `["Champion Arcfire Strike"]`: links in the tooltip of the card's "Tier N Recruit" line, shown after the abilities. |
| `units[].tooltip_scale` | Fixed tooltip size, e.g. `0.9` (may then overlap the model). Default: as large as fits beside the model. |
| `units[].base_image` | Own finished unit picture (encyclopedia UI already removed, same resolution): used as is, only the tooltips are laid on top. |

## How it works (for debugging)

- `tomedocs/capture.py` – navigation: main-menu "i" button -> Tomes tab ->
  search box -> result -> page. Button images in `templates/`; the UI scale is
  measured from them. Each run saves `page.png` and `manifest.json` per tome.
- `tomedocs/locate.py` – finds skills on the page: OCR'd labels that match a
  name from the mod's .po files (stale .po entries never appear on the page, so
  they're ignored); icon = circle above the label, else it's a text link.
- `tomedocs/tooltips.py` – tooltip = difference between frames with and
  without hover, snapped to the tooltip's border line; sub-tooltips are cut to
  the bordered box around their title.
- `tomedocs/background.py` – removes the encyclopedia UI: mirrored opposite
  side, Poisson-blended; plain background for the Tooltips image.
- `tomedocs/describe.py` – OCR of tooltips (several zooms, best reading per
  line) + .po text -> `description_facts.md`.
- Units: the Tome Units tab, then the same search. Racial units have a Forms
  button (`templates/forms_button.png`) opening a scrollable list.
  `locate.unit_abilities` reads the ability column of the stat card. Ability
  tooltips are cut by their title + border, because the animated unit model
  defeats frame differences.
- If navigation breaks after a game update, the usual fix is re-cutting
  `templates/*.png` from a 1920x1080 screenshot.
- To teach the tool a new part of the UI, record the user doing it:
  `python tools/watch.py <name>` (passive: screenshots on every click and on
  F7/F8, F9 stops) -> `output/_watch/<name>/`.
