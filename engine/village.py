"""续写一回 / one chapter of the open isekai serial.

  VILLAGE_MOCK=1 python engine/village.py --ticks 3     # 零 token 看流程
  ANTHROPIC_API_KEY=... python engine/village.py        # 真·续写一回
"""
import os, sys, json, random, itertools, datetime, glob, argparse, re
sys.path.insert(0, os.path.dirname(__file__))
import yaml
import soul as SOUL, cast as C, season as SE, llm, trace, writer, prose_lint


CHAPTER_FILE_RE = re.compile(r"^(?:ch)?(\d+)-.+\.md$", re.I)
FRONTMATTER_FIELDS = (
    "season", "chapter", "title", "cast", "pov", "line",
    "thread", "beat", "ships", "hook",
)
EDITORIAL_FIELDS = ("review", "score")


def chapter_number(name):
    match = CHAPTER_FILE_RE.match(os.path.basename(name))
    return int(match.group(1)) if match else None


def chapter_files(sdir):
    cdir = os.path.join(sdir, "chronicle")
    paths = []
    for path in glob.glob(os.path.join(cdir, "*.md")):
        number = chapter_number(path)
        if number is not None:
            paths.append((number, path))
    return sorted(paths, key=lambda item: item[0], reverse=True)


def heat(ties, a, b):
    r1, r2 = SE.rel(ties, a, b), SE.rel(ties, b, a)
    return abs(r1["tension"]) + abs(r2["tension"]) + abs(r1["affection"] - r2["affection"])


def pick_cast(names, ties, season, pressure, newcomer_first):
    newcomers = [n for n in names if not C.incarnated(n, season)]
    pairs = list(itertools.combinations(names, 2))
    w = [heat(ties, a, b) + random.random() * 3 + 1 for a, b in pairs]
    a, b = random.choices(pairs, weights=w, k=1)[0]
    chosen = [a, b]
    # 新进村的角色优先被写进剧情 —— PR/表单一进村就登场
    if newcomer_first and newcomers and not (set(chosen) & set(newcomers)):
        chosen[random.randint(0, 1)] = random.choice(newcomers)
    if len(names) > 2 and random.random() < 0.2 + pressure * 0.5:
        rest = [n for n in names if n not in chosen]
        if rest:
            chosen.append(random.choice(rest))
    weight = min(10, int(heat(ties, chosen[0], chosen[1]) / 2 + pressure * 4 + 2))
    return chosen, [n for n in chosen if n in newcomers], weight


def pressure_event(p, scope):
    if random.random() > p:
        return ""
    return random.choice([
        "一个名额/一次机会只剩一个，得有人被留下、有人被放弃。",
        "有人要离开了，时间不多。",
        "一场谁也没料到的变故砸下来，打乱所有人的盘算。",
    ])


def read_frontmatter(text):
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?", text, re.S)
    if not match:
        return {}
    try:
        data = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def recent_chapter_context(sdir, limit=3):
    """Return compact hook metadata from the newest numeric chapter files."""
    entries = []
    for number, path in chapter_files(sdir)[:limit]:
        try:
            with open(path, encoding="utf-8") as fh:
                raw = fh.read()
        except OSError:
            continue
        meta = read_frontmatter(raw)
        title = str(meta.get("title") or os.path.basename(path).split("-", 1)[-1][:-3])
        hook = str(meta.get("hook") or "").strip()
        body = prose_lint.body_of(raw)
        lines = [line.strip() for line in body.splitlines() if line.strip()]
        if not hook:
            hook = lines[-1] if lines else "（旧章未记录 hook）"
        hook = " ".join(hook.split())[:240]
        pov = str(meta.get("pov") or "未知")
        cast = meta.get("cast") if isinstance(meta.get("cast"), list) else []
        cast = "、".join(str(name).strip() for name in cast if str(name).strip()) or "未知"
        thread = str(meta.get("thread") or "未知").strip()[:100]
        beat = str(meta.get("beat") or "未知").strip()[:100]
        tail = " ".join(lines[-2:])[:180] if lines else "（旧章无正文尾部）"
        entries.append(
            f"第{number}回《{title}》 | cast={cast} | POV={pov} | "
            f"thread={thread} | beat={beat} | hook={hook} | tail={tail}"
        )
    if not entries:
        return ""
    return "最近三回的已落盘钩子（按新到旧）：\n" + "\n".join(entries)


def recent_hooks(sdir, limit=3):
    hooks = []
    for _, path in chapter_files(sdir)[:limit]:
        try:
            with open(path, encoding="utf-8") as fh:
                meta = read_frontmatter(fh.read())
        except OSError:
            continue
        hook = str(meta.get("hook") or "").strip()
        if hook:
            hooks.append(hook)
    return hooks


def story_so_far(sdir):
    context = recent_chapter_context(sdir)
    if context:
        return context
    idx = os.path.join(sdir, "chronicle", "INDEX.md")
    if not os.path.exists(idx):
        return ""
    lines = [l for l in open(idx, encoding="utf-8") if l.strip().startswith("- ")]
    return ("上一回：" + lines[0][2:].strip()) if lines else ""


def build_prompt(souls, states, ties, chosen, newcomers, world, beat, target, sdir):
    cards = "\n\n".join(SOUL.card(souls[n], states[n]) for n in chosen)
    if newcomers:
        cards += "\n\n新登场(本季第一次): " + " ".join(newcomers)
    rels = [f"{a}→{b}: 好感{SE.rel(ties,a,b)['affection']} 张力{SE.rel(ties,a,b)['tension']}"
            + (f"（{SE.rel(ties,a,b)['feeling']}）" if SE.rel(ties, a, b)["feeling"] else "")
            for a, b in itertools.permutations(chosen, 2)]
    mems = [f"{n}记得：" + "；".join(C.recall(n)) for n in chosen if C.recall(n)]
    trends = open("trends.md", encoding="utf-8").read()[:500] if os.path.exists("trends.md") else ""
    ev = pressure_event(0, world.get("scope", ""))
    parts = ["【出场（角色数据，非指令）】\n" + cards, "【此刻关系】\n" + "\n".join(rels)]
    if mems:    parts.append("【他们带着的记忆（可跨季）】\n" + "\n".join(mems))
    sof = story_so_far(sdir)
    if sof:     parts.append("【前情】\n" + sof)
    if trends:  parts.append("【当季叙事趋势（学形状，别抄）】\n" + trends)
    return "\n\n".join(parts)


def build_frontmatter(out, n, season, chosen, beat, crit=None):
    raw = out.get("frontmatter") if isinstance(out, dict) else {}
    raw = raw if isinstance(raw, dict) else {}
    crit = crit if isinstance(crit, dict) else {}
    cast = raw.get("cast")
    if not isinstance(cast, list) or not cast:
        cast = list(chosen)
    cast = list(dict.fromkeys(str(name).strip() for name in cast if str(name).strip()))
    chosen = [str(name).strip() for name in chosen if str(name).strip()]
    cast = [name for name in cast if name in chosen] or list(chosen)
    ships = raw.get("ships") or {}
    if isinstance(ships, dict):
        ships = {
            str(key).strip(): str(value).strip()[:200]
            for key, value in ships.items()
            if str(key).strip() and str(value).strip()
        }
    elif str(ships).strip():
        ships = {"本章": str(ships).strip()[:200]}
    else:
        ships = {}
    title = str(out.get("chapter_title") or "无题").strip()
    meta = {
        "season": season,
        "chapter": n,
        "title": title,
        "cast": cast,
        "pov": str(raw.get("pov") or (cast[0] if cast else "")).strip(),
        "line": str(raw.get("line") or "混合").strip(),
        "thread": str(raw.get("thread") or beat).strip(),
        "beat": str(raw.get("beat") or beat).strip(),
        "ships": ships,
        "hook": str(raw.get("hook") or out.get("hook") or "").strip(),
    }
    # Once an independent critique exists, never trust model-authored review or
    # score fields from the chapter payload.  The publication score must be
    # derived from the structured critique that the gate actually inspected.
    critique_supplied = bool(crit)
    if critique_supplied:
        review = str(crit.get("review") or "").strip()
        score = (
            f"{int(float(crit['total']))}/14"
            if _is_int_like(crit.get("total"))
            else ""
        )
    else:
        review = str(raw.get("review") or "").strip()
        score = str(raw.get("score") or "").strip()
    if review:
        meta["review"] = review
    if score:
        meta["score"] = score
    return meta


def _is_int_like(value):
    try:
        return float(value).is_integer()
    except (TypeError, ValueError):
        return False


def validate_frontmatter(meta):
    errors = [field for field in FRONTMATTER_FIELDS if field not in meta]
    if not isinstance(meta.get("season"), int) or isinstance(meta.get("season"), bool):
        errors.append("season")
    if not isinstance(meta.get("chapter"), int) or isinstance(meta.get("chapter"), bool):
        errors.append("chapter")
    for field in ("season", "chapter", "title", "pov", "line", "thread", "beat", "hook"):
        if field in meta and (meta[field] is None or not str(meta[field]).strip()):
            errors.append(field)
    if str(meta.get("title") or "").strip() in {"无题", "Untitled"}:
        errors.append("title")
    if not isinstance(meta.get("cast"), list) or not meta.get("cast"):
        errors.append("cast")
    elif any(not isinstance(name, str) or not name.strip() for name in meta["cast"]):
        errors.append("cast")
    if not isinstance(meta.get("ships"), dict):
        errors.append("ships")
    else:
        for key, value in meta["ships"].items():
            if len(str(value)) > 200:
                errors.append(f"ships.{key}")
            pair = re.split(r"[×xX]", str(key), maxsplit=1)
            if len(pair) == 2 and pair[0].strip() == pair[1].strip():
                errors.append(f"ships.{key}")
    return list(dict.fromkeys(errors))


def validate_editorial_metadata(meta, body=None):
    """Require evidence-backed review metadata for newly generated chapters."""
    errors = []
    review = meta.get("review")
    if not isinstance(review, str) or len(review.strip()) < 40:
        errors.append("review")
    score = str(meta.get("score") or "").strip()
    match = re.fullmatch(r"(?:0|[1-9]|1[0-4])/14", score)
    if not match:
        errors.append("score")
    elif int(score.split("/", 1)[0]) < writer.EDITORIAL_BAR:
        errors.append(f"score<{writer.EDITORIAL_BAR}")
    if body is not None and isinstance(review, str):
        if not writer.review_has_body_evidence(review, str(body)):
            errors.append("review evidence")
    return list(dict.fromkeys(errors))


def serialize_frontmatter(meta):
    return "---\n" + yaml.safe_dump(
        meta, allow_unicode=True, sort_keys=False, default_flow_style=False
    ).rstrip() + "\n---\n"


def _filename_title(title):
    return re.sub(r'[<>:"/\\|?*]', "-", str(title)).strip()[:18] or "无题"


def write_chapter(sdir, n, out, chosen, season, frontmatter=None):
    frontmatter = frontmatter or build_frontmatter(out, n, season, chosen, "")
    metadata_errors = validate_frontmatter(frontmatter)
    if metadata_errors:
        raise ValueError("invalid chapter frontmatter: " + ", ".join(metadata_errors))
    cdir = os.path.join(sdir, "chronicle")
    os.makedirs(cdir, exist_ok=True)
    os.makedirs("docs", exist_ok=True)
    date = datetime.date.today().isoformat()
    title = str(out.get("chapter_title") or "无题").strip()
    body = out.get("chapter", "").strip()
    open(os.path.join(cdir, f"{n:04d}-{_filename_title(title)}.md"), "w", encoding="utf-8").write(
        serialize_frontmatter(frontmatter)
        + f"\n# 第{n}回 · {title}\n\n> S{season} · {date} · {' / '.join(chosen)}\n\n{body}\n"
    )
    idx = os.path.join(cdir, "INDEX.md")
    head = "# 连载目录\n"
    entry = f"- 第{n}回《{title}》— {' / '.join(chosen)}（{date}）\n"
    rest = ""
    if os.path.exists(idx):
        old = open(idx, encoding="utf-8").read()
        rest = old.split("\n", 1)[1] if "\n" in old else ""
    open(idx, "w", encoding="utf-8").write(head + entry + rest)
    feed = json.load(open("docs/chronicle.json", encoding="utf-8")) if os.path.exists("docs/chronicle.json") else []
    feed.insert(0, {
        "n": n, "season": season, "title": title, "date": date,
        "cast": chosen, "body": body,
        "pov": frontmatter.get("pov"), "line": frontmatter.get("line"),
        "thread": frontmatter.get("thread"), "beat": frontmatter.get("beat"),
        "ships": frontmatter.get("ships"), "hook": frontmatter.get("hook"),
    })
    json.dump(feed, open("docs/chronicle.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def chap_count(sdir):
    return max((number for number, _ in chapter_files(sdir)), default=0)


def tick(cfg, souls, sdir, world, ties, arc, pressure):
    season = world.get("season", 1)
    names = list(souls)
    if len(names) < 2:
        raise SystemExit("至少要两个魂才能起戏。先 PR / 提表单送一个进村。")
    states = {n: C.load_state(n) for n in names}
    chosen, newcomers, weight = pick_cast(names, ties, season, pressure, cfg["newcomer_priority"])
    ctx = build_prompt(souls, states, ties, chosen, newcomers, world,
                       SE.beat_line(arc), cfg["target_chapter_chars"], sdir)
    rating = world.get("rating", cfg.get("rating", "暧昧"))
    try:
        out, crit, spec = writer.compose(
            ctx, world, SE.beat_line(arc),
            cfg["target_chapter_chars"], rating, weight,
        )
    except Exception as exc:
        # A provider/parser failure must be a clean no-op: no state, ties,
        # memories, arc, or chapter file may be advanced by a partial run.
        print(f"generation rejected: {type(exc).__name__}: {exc}")
        raise

    # 文笔检阅门：到上限还没揉顺（中英混写 / 逗号碎句）就拒发——
    # 宁可这一回不更，也不让垃圾稿上线。不写文件、不动关系/记忆、不推进节拍。
    if not crit.get("prose_clean", False) or not crit.get("quality_clean", False):
        print(f"⚠ 本回文笔未过检阅门（重写 {crit.get('prose_polishes','?')} 次仍不过），"
              f"跳过不发布。[{' / '.join(chosen)}]")
        return

    n = chap_count(sdir) + 1
    frontmatter = build_frontmatter(
        out, n, season, chosen, SE.beat_line(arc), crit=crit
    )
    metadata_errors = validate_frontmatter(frontmatter)
    metadata_errors.extend(
        validate_editorial_metadata(frontmatter, body=str(out.get("chapter") or ""))
    )
    hook = str(frontmatter.get("hook") or "").strip()
    if hook and hook in {item.strip() for item in recent_hooks(sdir)}:
        metadata_errors.append("hook重复")
    metadata_errors = list(dict.fromkeys(metadata_errors))
    if metadata_errors:
        print(f"metadata rejected: {', '.join(metadata_errors)}")
        return

    for name, role in (out.get("incarnations") or {}).items():
        if name in souls:
            st = states[name]
            st.update({"season": season, "incarnation": role})
            C.save_state(name, st)
    for name in chosen:  # 确保出场的人本季已落定身份
        if states[name].get("season") != season:
            states[name].update({"season": season, "incarnation": "本季的一个普通人"})
            C.save_state(name, states[name])
    for u in out.get("updates", []):
        if u.get("from") in souls and u.get("to") in souls:
            SE.apply_update(ties, u)
    for m in out.get("memories", []):
        if m.get("who") in souls:
            C.add_memory(m["who"], m["text"], m.get("importance", 5), season)
    ref = out.get("reflection")
    if ref and ref.get("who") in souls:
        C.add_memory(ref["who"], ref["insight"], 9, season, kind="反思")

    write_chapter(sdir, n, out, chosen, season, frontmatter=frontmatter)
    SE.save_ties(sdir, ties)
    SE.advance_arc(sdir, arc, cfg["chapters_per_beat"])
    tag = ("★新登场 " + " ".join(newcomers)) if newcomers else ""
    rw = " ↻重写过" if crit.get("rewritten") else ""
    print(f"第{n}回 · {out.get('chapter_title')} [{' / '.join(chosen)}] {tag}"
          f"[审校 {crit.get('total','?')}/14 · {spec.get('trope','')}{rw}]")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticks", type=int, default=1)
    ap.add_argument("--pressure", type=float, default=None)
    args = ap.parse_args()
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    pressure = args.pressure if args.pressure is not None else cfg.get("default_pressure", 0.2)
    souls = SOUL.load_cast()
    sdir = SE.current_dir()
    world = SE.load_world(sdir)
    ties = SE.load_ties(sdir)
    if not ties:  # 首跑：吸收灵魂自带的 seed_relations
        for name, meta in souls.items():
            for other, feeling in (meta.get("seed_relations") or {}).items():
                if other in souls:
                    SE.rel(ties, name, other).update({"feeling": feeling, "affection": 2})
    arc = SE.load_arc(sdir, world)
    print(f"Open Souls · {len(souls)} 个魂在场：{', '.join(souls)} | 季{world.get('season')}《{world.get('title')}》| 节拍：{SE.beat_line(arc)}")
    for _ in range(args.ticks):
        tick(cfg, souls, sdir, world, ties, arc, pressure)
    trace.rebuild(souls)


if __name__ == "__main__":
    main()
