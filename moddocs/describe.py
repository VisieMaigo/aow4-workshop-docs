"""Collect the facts for the Steam Workshop description.

Tooltip text is read with OCR (it has the real numbers players see); the .po
files add the tome's description and its Ascension skill, which the
encyclopedia doesn't show. Everything goes into one facts file, from which the
agent writes the short final description (style guide: AGENTS.md).
"""
import difflib
import json
import re
from pathlib import Path

from PIL import Image

from . import po
from .config import file_name, final_dir, tome_dir, unit_dir
from .locate import match_name, norm
from .ocr import read_lines

STOP = re.compile(r"^(Casting Cost|Base Upkeep|Upkeep|Requires|Unlocked by|Recruitable|Cooldown|"
                  r"(Combat|Tactical|Strategic|World) Casting|(Novice|Adept|Intermediate|Expert|Master|Mythic) Skill)",
                  re.I)
AFFINITIES = ["Astral", "Chaos", "Materium", "Nature", "Order", "Shadow"]
KEEP_SHORT = {"a", "an", "of", "to", "in", "is", "at", "by", "on", "or", "if", "it", "as", "be", "up", "no", "per"}
ROMAN = {"i", "ii", "iii", "iv", "v", "vi"}
NUMBER = re.compile(r"[+\-]?\d+%?")


def clean_line(text):
    """Remove bullet glyphs and the stray characters OCR makes of inline icons."""
    t = re.sub(r"^[^\w+\-(\"']+", "", text.strip())
    t = re.sub(r"([a-z])(\d)", r"\1 \2", t)          # "for3 Turns" -> "for 3 Turns"
    out = []
    for tok in t.split():
        core = tok.strip(".,;:!?()")
        if not core or re.fullmatch(r"[^\w]+", tok):  # pure symbols: icon junk
            continue
        if re.fullmatch(r"\d", core) and out and NUMBER.fullmatch(out[-1]):
            continue                                  # "-1 0 Status": the 0 is an icon
        if len(core) <= 2 and not (core.lower() in KEEP_SHORT or core.lower() in ROMAN or NUMBER.fullmatch(core)):
            continue
        out.append(tok)
    return " ".join(out)


def tooltip_type(line):
    """'Skill level IV - + Unit Enchantment - Tome of ...' -> 'Unit Enchantment'."""
    parts = [clean_line(p) for p in re.split(r"\s[-–]\s?|\s?[-–]\s", line)]
    parts = [p for p in parts if p]
    if len(parts) >= 2 and parts[0].lower().startswith("skill level"):
        return parts[1]
    return parts[0] if parts else ""


def skill_type(img):
    """Just the type of a captured tooltip ('Unit', 'Siege Project', ...)."""
    raw = [t for t, _ in sorted(read_lines(img, scale=2), key=lambda l: (l[1][1], l[1][0])) if clean_line(t)]
    return tooltip_type(raw[1]) if len(raw) > 1 and not re.search(r"[:.]$", clean_line(raw[1])) else ""


def fix_garbled(line, vocab):
    """Underlined links sometimes OCR as junk ('City-StabjJj.ty'); swap such words
    for the closest known term from the mod's .po files ('City Stability')."""
    toks = line.split()
    for i, tok in enumerate(toks):
        core = tok.rstrip(".,;:!?")
        if not re.search(r"[a-z][A-Z]|[A-Za-z][.\-_|][A-Za-z]", core):
            continue
        letters = re.sub(r"[^a-z]", "", core.lower())
        best = max(vocab, key=lambda v: difflib.SequenceMatcher(None, letters, norm(v)).ratio(), default=None)
        if best and difflib.SequenceMatcher(None, letters, norm(best)).ratio() >= 0.7:
            toks[i] = best + tok[len(core):]
    return " ".join(toks)


def _is_card_start(line, title):
    """An embedded unit card (summoned unit) begins with its NAME in caps or 'hp/hp'."""
    caps = re.sub(r"[^A-Za-z]", "", line)
    return bool(re.fullmatch(r"\d+/\d+", line)) or (len(caps) > 3 and caps.isupper() and norm(line) != norm(title))


def _quality(text):
    """How good an OCR reading looks: letters in plausible words, minus junk
    ('KngyyJgdgg', 'Jgg': odd capitals, j+consonant, long consonant runs)."""
    score = 0
    for tok in text.split():
        letters = len(re.findall(r"[A-Za-z]", tok))
        junk = re.search(r"[a-z][A-Z]|[jJ][^aeiouAEIOU\W]|[^aeiouyAEIOUY\W\d_]{4,}|[^\w\s+\-%',.:;/()]", tok)
        score += -2 * letters if junk else letters
    return score


def read_best(img, vocab, scales=(2, 1.5, 3)):
    """OCR at several zooms and keep, per line, the best reading.

    Underlined links ('Status Vulnerability') come and go between zoom levels,
    so no single zoom is reliable. Returns [(clean text, raw text, box)] by line.
    """
    readings = []
    for s in scales:
        for t, b in read_lines(img, scale=s):
            text = fix_garbled(clean_line(t), vocab)
            if text:
                readings.append((text, t, b))
    best = []
    for text, raw, box in sorted(readings, key=lambda r: (r[2][1], r[2][0])):
        cy = (box[1] + box[3]) / 2
        same = next((i for i, (_, _, b) in enumerate(best)
                     if abs((b[1] + b[3]) / 2 - cy) < 6 and b[0] < box[2] and box[0] < b[2]), None)
        if same is None:
            best.append((text, raw, box))
        elif _quality(text) > _quality(best[same][0]):
            best[same] = (text, raw, box)
    return sorted(best, key=lambda r: (r[2][1], r[2][0]))


def read_tooltip(img, names, tome_name, vocab=(), typed=True):
    """Structured content of one tooltip image. typed=False for unit abilities,
    whose second line is accuracy/range numbers rather than a type."""
    ocr = read_best(img, vocab)
    if not ocr:
        return None
    title = match_name(ocr[0][0], names) or po.title_case(ocr[0][0].split())
    if not typed:
        ocr = [ocr[0]] + [o for o in ocr[1:] if re.search(r"[A-Za-z]{3}", o[0])]
    # Line 2 is normally the type ("Skill level IV - Unit Enchantment - ..."), but
    # sub-tooltips (traits, statuses) go straight into their text.
    has_type = typed and len(ocr) > 1 and not re.search(r"[:.]$", ocr[1][0])
    kind = tooltip_type(ocr[1][1]) if has_type else ""

    body, eligible, section, prev_x = [], [], None, None
    for line, raw, box in ocr[2 if has_type else 1:]:
        if STOP.match(line) or norm(line) == norm(title) or _is_card_start(line, title):
            break
        if norm(tome_name) in norm(line) and len(line) < len(tome_name) + 5:
            continue  # wrapped "- Tome of ..." part of the type line
        if re.match(r"^Affects units of type", line, re.I):
            section = "eligible"
            continue
        if section == "eligible" and not line.endswith(":"):
            eligible.append(re.sub(r"\s+Unit$", "", line))
            continue
        section = None
        # A new item starts with a bullet glyph, a "+3"/"-1" number, or sticks out
        # left of the line above ("This effect stacks." after a bullet list).
        # Otherwise a line continues the text above unless that ended a sentence.
        bullet = bool(re.match(r"^\s*[^\w\s+\-(\"']", raw))
        outdent = prev_x is not None and box[0] < prev_x - 6
        wrapped = bool(body) and not (bullet or outdent or NUMBER.match(line)) and (
            line[0].islower() or not re.search(r"[.:!?]$", body[-1]))
        if wrapped:
            body[-1] += " " + line
        else:
            body.append(line)
        prev_x = box[0]
    return {"name": title, "type": kind, "body": body, "eligible": eligible}


def tome_header(strings, tome, manifest, folder, vocab):
    page_lines = manifest.get("page_lines", [])
    tier = None
    for line, _ in page_lines:
        if m := re.search(r"\bTier\s+([IVXl1]+)\b", line):  # OCR reads "II" as "11"
            tier = m.group(1).replace("1", "I").replace("l", "I")
            break
    root = po.tome_root(strings, tome["name"]) or ""
    gameplay = next((po.clean(v, strings) for k, v in strings.items()
                     if k.startswith(root) and "GAMEPLAY_DESCRIPTION" in k), "")
    return tier, gameplay, initial_bonus(folder / manifest["page"], page_lines, manifest["scale"], vocab)


def initial_bonus(page_file, page_lines, s, vocab):
    """Lines in the Initial Bonus box, read at two zooms (its underlined links are
    small and hard to read), with affinities matched by name."""
    head = next((b for t, b in page_lines if norm(t) == "initialbonus"), None)
    if not head:
        return []
    box = (int(head[0] - 90 * s), head[3], int(head[2] + 90 * s), int(head[3] + 110 * s))
    crop = Image.open(page_file).crop(box)
    found = []
    for zoom in (1.5, 2):
        for text, _ in read_lines(crop, scale=zoom):
            letters = re.sub(r"[^a-z]", "", text.lower())
            if "aff" in letters:
                guess = difflib.get_close_matches(letters.split("aff")[0], [a.lower() for a in AFFINITIES],
                                                  n=1, cutoff=0.5)
                amount = re.match(r"\s*([+\-]\d+)", text)
                if guess:
                    text = f"{amount.group(1) + ' ' if amount else ''}{guess[0].title()} Affinity"
            text = match_name(text, vocab, cutoff=0.8) or clean_line(text)
            readable = re.search(r"[A-Za-z]{3}", text) and not re.search(r"[^\w\s+\-%',.:]", text)
            if readable and norm(text) not in {norm(f) for f in found}:
                found.append(text)
    return found

ROMAN_VALUE = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6}


def tome_facts(cfg, tome, strings, names, vocab):
    folder = tome_dir(cfg, tome)
    manifest = json.loads((folder / "manifest.json").read_text())
    parsed = {}
    for e in manifest["tooltips"]:
        d = read_tooltip(Image.open(folder / e["file"]), names, tome["name"], vocab)
        if d:
            parsed[e["name"]] = (e, d)
    # Scroll skills in reading order, then Initial Bonus links.
    order = sorted((e for e, _ in parsed.values() if e["kind"] != "sub"),
                   key=lambda e: (e["kind"] != "icon", e["anchor"][1] // 60, e["anchor"][0]))
    configured = {(s["parent"], s["link"]) for s in tome["subtooltips"]}
    skills, candidates = [], {}
    for e in order:
        d = parsed[e["name"]][1]
        subs = [x_d for (x, x_d) in parsed.values() if x.get("parent") == e["name"]]
        skills.append({**d, "where": "Initial Bonus" if e["kind"] == "link" else "tome skill", "subs": subs})
        # Mod-defined names mentioned in the tooltip text are likely links with
        # nested tooltips of their own (traits, statuses, effects).
        text = norm(" ".join(d["body"]))
        found = [n for n in names if len(norm(n)) > 4 and norm(n) in text and (e["name"], n) not in configured]
        if found:
            candidates[e["name"]] = sorted(found)
    tier, gameplay, bonus = tome_header(strings, tome, manifest, folder, vocab)
    return {"name": tome["name"], "tier": tier, "gameplay": gameplay, "bonus": bonus, "skills": skills,
            "ascension": po.ascension(strings, tome["name"]), "candidates": candidates}


def unit_facts(cfg, unit, names, vocab):
    folder = unit_dir(cfg, unit)
    manifest = json.loads((folder / "manifest.json").read_text())
    card = [t for t, b in manifest["page_lines"] if b[0] > 0.74 * manifest["size"][0]]
    role = next((t for t in card if re.search(r"\bUnit\b", t) and norm(t) != norm(unit["name"])), "")
    tier = next((m.group(1).replace("1", "I") for t in card if (m := re.search(r"\bTier\s+([IVX1]+)", t))), None)
    abilities = []
    for e in manifest["tooltips"]:
        d = read_tooltip(Image.open(folder / e["file"]), names, unit["name"], vocab, typed=False)
        if d:
            abilities.append({**d, "sub": e["kind"] == "sub"})
    return {"name": unit["name"], "form": manifest.get("form"), "role": clean_line(role), "tier": tier,
            "listed": manifest.get("abilities", []), "abilities": abilities}


def facts_markdown(mod, data, units=()):
    out = [f"# Description facts: {mod}", "",
           f"Raw material for `{mod} - Description.txt`. Write that file following the",
           "style guide in AGENTS.md. Tooltip text is OCR - check names against the .po files.", ""]
    for t in data:
        out.append(f"## {t['name']}" + (f" (Tier {t['tier']})" if t["tier"] else ""))
        out.append(f"- Gameplay description (.po): {t['gameplay'] or '-'}")
        out.append(f"- Initial bonus (page): {', '.join(t['bonus']) or '-'}")
        for s in t["skills"]:
            out += ["", f"### {s['name']} - {s['type'] or '?'} ({s['where']})"]
            if s["eligible"]:
                out.append(f"Eligible units: {', '.join(s['eligible'])}")
            out += [f"    {line}" for line in s["body"]]
            for sub in s["subs"]:
                out.append(f"Nested tooltip '{sub['name']}':")
                out += [f"    {line}" for line in sub["body"]]
        if t["ascension"]:
            trait, grants = t["ascension"]
            out += ["", f"### {trait} - Ascension Skill (.po only, not shown in game; X = value computed by the game)"]
            for kind, name, desc in grants:
                out.append(f"{kind}: {name or '(unnamed)'}")
                out += [f"    {line}" for line in desc.splitlines()]
        out.append("")
    for u in units:
        out.append(f"## Unit: {u['name']}" + (f" (Tier {u['tier']})" if u["tier"] else ""))
        out.append(f"- Role (unit card): {u['role'] or '-'}" + (f"; shown in {u['form']} form" if u["form"] else ""))
        listed = [a["name"] + (" (attack)" if a["attack"] else "") + (" (mod)" if a["mod"] else "") for a in u["listed"]]
        out.append(f"- All abilities on the card: {', '.join(listed) or '-'}")
        for a in u["abilities"]:
            out += ["", f"### {'Nested tooltip ' if a['sub'] else ''}{a['name']}"]
            out += [f"    {line}" for line in a["body"]]
        out.append("")
    return "\n".join(out)


def describe(cfg, tomes, units=()):
    """Write the facts for the whole mod's description: every captured tome
    (lowest tier first), then the units."""
    strings, _ = po.load_mod_strings(cfg["mod_folder"], cfg["language"])
    names = po.name_strings(strings)
    vocab = sorted(set(names) | po.terms(strings))
    data = [tome_facts(cfg, t, strings, names, vocab) for t in tomes]
    data.sort(key=lambda t: ROMAN_VALUE.get(t["tier"] or "", 99))  # stable: ties keep project order
    unit_data = [unit_facts(cfg, u, names, vocab) for u in units]
    mod = file_name(Path(cfg["mod_folder"]).name)
    path = final_dir(cfg) / "_captures" / "description_facts.md"
    path.write_text(facts_markdown(mod, data, unit_data), encoding="utf-8")
    print(f"  {path}")
    print(f"  Covers: {', '.join([t['name'] for t in data] + [u['name'] for u in unit_data])}")
    print(f"  Next: the agent writes '{mod} - Description.txt' from these facts (see AGENTS.md).")
    if any(t["candidates"] for t in data):
        print("  Possible sub-tooltips (mod names linked inside tooltips; add to \"subtooltips\" to capture):")
        for t in data:
            for skill, links in t["candidates"].items():
                print(f"    {t['name']} > {skill}: {', '.join(links)}")
