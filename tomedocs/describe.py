"""Write Steam Workshop descriptions (BBCode) from the captured tooltips.

Tooltip text is read with OCR (it has the real numbers players see); the .po
files add the tome's description and its Ascension skill, which the
encyclopedia doesn't show. Output is a draft to review, not final copy.
"""
import difflib
import json
import re
from pathlib import Path

from PIL import Image

from . import po
from .config import file_name, final_dir, tome_dir
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


def read_tooltip(img, names, tome_name, vocab=()):
    """Structured content of one tooltip image."""
    ocr = read_best(img, vocab)
    if not ocr:
        return None
    title = match_name(ocr[0][0], names) or po.title_case(ocr[0][0].split())
    # Line 2 is normally the type ("Skill level IV - Unit Enchantment - ..."), but
    # sub-tooltips (traits, statuses) go straight into their text.
    has_type = len(ocr) > 1 and not re.search(r"[:.]$", ocr[1][0])
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


def _lower_first(item):
    """'Deal +2 Frost Damage' -> 'deal +2 ...' (but keep names like 'Frigid Presence, ...')."""
    words = item.split()
    if len(words) > 1 and words[0][0].isupper() and not words[1][0].isupper():
        return words[0][0].lower() + item[1:]
    return item


def effects(d):
    """Body lines -> sentences, folding 'Header:' lines into the items after them."""
    out, header, items = [], None, []

    def flush():
        if header and items:
            out.append(f"{header} " + "; ".join(_lower_first(i.rstrip(".")) for i in items) + ".")
        elif header:
            out.append(header)
        else:
            out.extend(items)

    for line in d["body"]:
        if line.endswith(":"):
            flush()
            header, items = line, []
        else:
            items.append(line)
    flush()
    return out


def unit_summary(d):
    """'A Shield Unit that wears down enemies...' -> ('Shield Unit', 'Wears down enemies...')."""
    first = d["body"][0] if d["body"] else ""
    m = re.match(r"^An?\s+(.+?\bUnit)\s+(?:that|which|who)\s+(.*?)\.?$", first)
    if m:
        return m.group(1), m.group(2)[0].upper() + m.group(2)[1:] + "."
    return None, first


def entry_lines(d, subs):
    """(headline, [detail lines]) for one skill."""
    if d["type"].lower() == "unit":
        cls, summary = unit_summary(d)
        return f"[b]{d['name']}[/b] — Unit{f' ({cls})' if cls else ''}", [summary]
    details = []
    if d["eligible"]:
        details.append("Eligible: " + ", ".join(d["eligible"]) + " units")
    details += effects(d)
    for s in subs:
        details.append(f"{s['name']}: " + " ".join(effects(s)))
    return f"[b]{d['name']}[/b] — {d['type']}", details


def ascension_line(strings, tome_name):
    asc = po.ascension(strings, tome_name)
    if not asc:
        return None
    trait, grants = asc
    parts = []
    for kind, name, desc in grants:
        text = re.sub(r"^Grants:\s*", "", desc).replace("\n• ", "; ").replace("• ", "").replace("\n", " ")
        text = text.replace(":;", ":").rstrip(".")
        parts.append(f"{name} ({text})" if name and text else name or text)
    return f"[b]{trait}[/b] — Ascension Skill", ["Grants " + "; ".join(parts) + "."] if parts else []


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


def describe_tome(cfg, tome, strings, names, vocab):
    folder = tome_dir(cfg, tome)
    manifest = json.loads((folder / "manifest.json").read_text())
    parsed = {}
    for e in manifest["tooltips"]:
        d = read_tooltip(Image.open(folder / e["file"]), names, tome["name"], vocab)
        if d:
            parsed[e["name"]] = (e, d)
    # Scroll skills in reading order, then Initial Bonus links, then Ascension.
    order = sorted((e for e, _ in parsed.values() if e["kind"] != "sub"),
                   key=lambda e: (e["kind"] != "icon", e["anchor"][1] // 60, e["anchor"][0]))
    entries, candidates = [], {}
    configured = {(s["parent"], s["link"]) for s in tome["subtooltips"]}
    for e in order:
        d = parsed[e["name"]][1]
        subs = [x_d for (x, x_d) in parsed.values() if x.get("parent") == e["name"]]
        entries.append(entry_lines(d, subs))
        # Mod-defined names mentioned in the tooltip text are likely links with
        # nested tooltips of their own (traits, statuses, effects).
        text = norm(" ".join(d["body"]))
        found = [n for n in names if len(norm(n)) > 4 and norm(n) in text and (e["name"], n) not in configured]
        if found:
            candidates[e["name"]] = sorted(found)
    asc = ascension_line(strings, tome["name"])
    if asc:
        entries.append(asc)
    tier, gameplay, bonus = tome_header(strings, tome, manifest, folder, vocab)
    return {"name": tome["name"], "tier": tier, "gameplay": gameplay, "bonus": bonus, "entries": entries,
            "candidates": candidates}


def bbcode(tomes, style):
    out = []
    for t in tomes:
        tier = f" (Tier {t['tier']})" if t["tier"] else ""
        out.append(f"[h2]{t['name']}{tier}[/h2]")
        if t["gameplay"]:
            out.append(f"[i]{t['gameplay']}[/i]")
        if t["bonus"]:
            out.append(f"[b]Initial bonus:[/b] {', '.join(t['bonus'])}")
        out.append("[list]")
        for head, details in t["entries"]:
            if style == "compact":
                # [Name] — [Type]: [Effect] (Eligible: ...)
                eligible = [d for d in details if d.startswith("Eligible:")]
                rest = [d if re.search(r"[.!?]$", d) else d + "." for d in details if d not in eligible]
                tail = f" ({eligible[0]})" if eligible else ""
                out.append(f"[*]{head}: {' '.join(rest)}{tail}")
            else:
                out.append(f"[*]{head}")
                if details:
                    out.append("[list]" + "".join(f"[*]{d}" for d in details) + "[/list]")
        out.append("[/list]")
        out.append("")
    return "\n".join(out).strip() + "\n"


ROMAN_VALUE = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6}


def describe(cfg, tomes):
    """One description for the whole mod: every captured tome, lowest tier first."""
    strings, _ = po.load_mod_strings(cfg["mod_folder"], cfg["language"])
    names = po.name_strings(strings)
    vocab = sorted(set(names) | po.terms(strings))
    data = [describe_tome(cfg, t, strings, names, vocab) for t in tomes]
    data.sort(key=lambda t: ROMAN_VALUE.get(t["tier"] or "", 99))  # stable: ties keep project order
    mod = file_name(Path(cfg["mod_folder"]).name)
    for style in ("structured", "compact"):
        text = bbcode(data, style)
        path = final_dir(cfg) / f"{mod} - Description ({style}).txt"
        path.write_text(text, encoding="utf-8")
        note = "  <- your default" if style == cfg.get("description_style", "structured") else ""
        print(f"  {path}  ({len(text)} of Steam's 8000 characters){note}")
    order = [t["name"] + (f" (Tier {t['tier']})" if t["tier"] else "") for t in data]
    print(f"  Tomes in order: {', '.join(order)}")
    if any(re.search(r"\bX\b", line) for t in data for _, d in t["entries"] for line in d):
        print("  Note: 'X' marks numbers the game computes (not in the .po files) - fill them in.")
    if any(t["candidates"] for t in data):
        print("  Possible sub-tooltips (mod names linked inside tooltips; add to \"subtooltips\" to capture):")
        for t in data:
            for skill, links in t["candidates"].items():
                print(f"    {t['name']} > {skill}: {', '.join(links)}")
