"""Read a mod's PoEdit .po localisation files and turn AoW4 markup into plain text."""
import re
from pathlib import Path

SMALL_WORDS = {"of", "the", "and", "a", "an", "in", "on", "to", "for", "by", "with"}


def parse_po(path):
    """{msgid: msgstr} from one .po file (multi-line strings joined)."""
    entries, cur, field = {}, None, None
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        m = re.match(r'^(msgid|msgstr) "(.*)"$', raw)
        if m:
            field = m.group(1)
            if field == "msgid":
                cur = [m.group(2), ""]
            else:
                cur[1] = m.group(2)
                entries[cur[0]] = cur[1]
            continue
        m = re.match(r'^"(.*)"$', raw)
        if m and cur is not None:
            if field == "msgid":
                cur[0] += m.group(1)
            else:
                cur[1] += m.group(1)
                entries[cur[0]] = cur[1]
    return {k: v.replace('\\"', '"').replace("\\n", "\n") for k, v in entries.items() if k}


def load_mod_strings(mod_folder, language="EN"):
    """All strings from <mod>/Language/<language>/*.po, plus which file each came from."""
    strings, source = {}, {}
    for po in sorted((Path(mod_folder) / "Language" / language).glob("*.po")):
        for k, v in parse_po(po).items():
            strings[k] = v
            source[k] = po.stem
    return strings, source


def title_case(words):
    out = []
    for i, w in enumerate(words):
        w = w.lower()
        out.append(w if i and w in SMALL_WORDS else w.capitalize())
    return " ".join(out)


def _token_name(token, strings):
    """Readable name for a placeholder like GLOBAL.PROPERTIES.CHILLED.Hyperlink."""
    parts = [p for p in token.split(".") if p not in ("GLOBAL", "Hyperlink", "Name", "Icon", "PROPERTIES",
                                                       "EQUIPMENT", "UNITS", "SPELLS", "ABILITIES")]
    if not parts:
        return ""
    key = parts[-1]
    if re.search(r"[a-z]", key):  # CamelCase concept, e.g. FrostDamageConcept
        key = re.sub(r"Concept$", "", key)
        return " ".join(re.findall(r"[A-Z][a-z]*|[a-z]+|\d+", key))
    # Mod-defined id (VM_TEW_FROZEN_FURY): look for a NAME string whose key has
    # a matching segment (..@FROZEN_FURY@NAME). Single words (FROZEN) are base game.
    words = key.split("_")
    for n in range(len(words), 1, -1):
        tail = "_".join(words[-n:])
        for k, v in strings.items():
            if tail in re.split(r"[@.]", k) and k.endswith("NAME") and "{" not in v:
                return v
    # Otherwise drop short prefix codes (VM, TEW) and title-case the rest.
    while len(words) > 1 and len(words[0]) <= 3:
        words = words[1:]
    return title_case(words)


def clean(text, strings=None):
    """AoW4 markup -> plain text. Numbers computed in game become 'X'."""
    strings = strings or {}
    t = text
    t = re.sub(r"\{LOC\.[^}]*\}", "", t)                                  # boilerplate inserts
    t = re.sub(r"\[hyperlink,[^\]]*\](.*?)\[/hyperlink\]", r"\1", t)
    t = re.sub(r"<<m:(.*?)>>", lambda m: m.group(1) + "\x00plural", t)

    def placeholder(m):
        inner = m.group(1)
        if ">" in inner:                                                 # computed value
            return "X"
        return _token_name(inner, strings)

    t = re.sub(r"\{([^{}]*)\}", placeholder, t)
    t = re.sub(r"(\w+)\x00plural", lambda m: m.group(1) if m.group(1).endswith("s") else m.group(1) + "s", t)
    t = re.sub(r"\^\w", "", t)                                          # a/an grammar markers
    t = re.sub(r"\[bullet/\]", "\n• ", t)
    t = re.sub(r"\[br/\]", "\n", t)
    t = re.sub(r"\[/?[a-zA-Z_]+[^\]]*\]", "", t)                        # any other tags
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r" +([.,:;])", r"\1", t)
    return "\n".join(line.strip() for line in t.splitlines() if line.strip())


def find_tomes(strings):
    """Likely tome names: strings under a TOME...NAME key, or starting 'Tome of'."""
    names = []
    for k, v in strings.items():
        if "{" in v or len(v) > 60:
            continue
        if re.search(r"TOME@NAME$|TOME_NAME$", k) or v.startswith("Tome of "):
            if v not in names:
                names.append(v)
    return names


def name_strings(strings):
    """Strings that look like names of things (skills, units, improvements...)."""
    out = {}
    for k, v in strings.items():
        if any(x in k for x in ("LORE", "AUTHOR")):
            continue
        v = re.sub(r"\[[^\]]*/\]\s*", "", v).strip()  # inline icons, e.g. "[forester/] Frost Shrine"
        if not v or len(v) > 40 or any(c in v for c in "{[<") or v.endswith((".", ":", "!")):
            continue
        out[v] = k
    return out


def tome_root(strings, tome_name):
    """Key prefix shared by a tome's strings, e.g. 'VM@TOME_LOOMING_FROST@'."""
    for k, v in strings.items():
        if v == tome_name:
            sep = "@" if "@" in k else "_"
            parts = k.split(sep)
            return sep.join(parts[:2]) + sep if len(parts) > 2 else k
    return None


def ascension(strings, tome_name):
    """(trait name, [(kind, name, description)]) for the tome's Ascension skill, or None.

    Ascension isn't shown in the encyclopedia, so it comes from the .po files:
    the 'Ascension: ...' string under the tome's key prefix, plus the strings
    next to it (abilities, properties, spells it grants).
    """
    root = tome_root(strings, tome_name)
    traits = [(k, v) for k, v in strings.items() if v.startswith("Ascension:") and (not root or k.startswith(root))]
    if not traits:
        return None
    key, trait = traits[0]
    sep = "@" if "@" in key else "_"
    parts = key.split(sep)
    i = next((n for n, p in enumerate(parts) if "ASCENSION" in p.upper()), len(parts) - 2)
    prefix = sep.join(parts[: i + 1]) + sep
    grants = {}
    for k, v in strings.items():
        if not k.startswith(prefix) or k == key:
            continue
        sub = k[len(prefix):].split(sep)
        group = sub[0]  # ABILITY@NAME and ABILITY@EFFECT@DESCRIPTION belong together
        if "TRAIT" in group.upper():
            continue
        g = grants.setdefault(group, {"kind": sub[0].title(), "name": "", "description": ""})
        if sub[-1].upper().endswith("NAME"):
            g["name"] = clean(v, strings)
        elif "DESCRIPTION" in sub[-1].upper() and not g["description"]:
            g["description"] = clean(v, strings)
    return trait, [(g["kind"], g["name"], g["description"]) for g in grants.values() if g["name"] or g["description"]]


def terms(strings):
    """Names of things the mod's text links to ({GLOBAL.CityStabilityConcept...} ->
    'City Stability'), used to repair words OCR garbles."""
    out = set()
    for v in strings.values():
        for inner in re.findall(r"\{([^{}>]*)\}", v):
            name = _token_name(inner, strings)
            if name and len(name) > 3:
                out.add(name)
    return out


def find_units(strings):
    """Likely unit names: strings under a ...UNIT@NAME / UNIT_NAME key."""
    names = []
    for k, v in strings.items():
        if re.search(r"(^|[@_])UNIT[@_]NAME$", k) and "{" not in v and v not in names:
            names.append(v)
    return names
