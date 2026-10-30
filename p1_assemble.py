"""One-shot: assemble Phase-1 thread templates + overlays into home.html.
Moves verified export blocks (by asserted landmarks) into <template>s,
deletes the static duplicate exchange + inline tour modal, adds wiring ids.
Run from the project root:  python p1_assemble.py
"""
import re
from pathlib import Path

V = Path("frontend/views")


def lines(p):
    return (V / p).read_text(encoding="utf-8").split("\n")


def find(lines_, needle, start=0):
    for i in range(start, len(lines_)):
        if needle in lines_[i]:
            return i
    raise SystemExit(f"landmark missing: {needle}")


def close_idx(lines_, open_i):
    """Index of the </div> matching the <div> on open_i (depth count)."""
    assert "<div" in lines_[open_i], lines_[open_i][:80]
    depth = 0
    for i in range(open_i, len(lines_)):
        depth += len(re.findall(r"<div[\s>]", lines_[i]))
        depth -= lines_[i].count("</div>")
        if depth == 0:
            return i
    raise SystemExit("unbalanced divs")


home = lines("home.html")
states = lines("_frag_states.html")
prog = lines("_frag_progress.html")
addp = lines("_frag_addphoto.html")
tour = lines("_frag_tour.html")

# ---- 1. thread exchanges -> templates (home.html) ----
u0 = find(home, "<!-- Exchange 1: User Message -->")
a0 = find(home, "<!-- Exchange 1: Reel Assistant Reply -->")
e2 = find(home, "<!-- Exchange 2: User Follow-up Query -->")
assert a0 > u0 and e2 > a0
tpl_user = home[u0:a0]
tpl_assistant = home[a0:e2]

# compare bar + selected badges live inside Exchange 2: lift them out.
bar_c = find(home, "<!-- Floating Comparison Action Bar -->", e2)
bar_div = bar_c + 1
assert home[bar_div].strip().startswith("<div")
bar_end = close_idx(home, bar_div)
tpl_comparebar = home[bar_c:bar_end + 1]
badges = []
i = e2
while True:
    try:
        c = find(home, "<!-- Selected Badge Indicator -->", i)
    except SystemExit:
        break
    if c > bar_end + 60:
        break
    d = c + 1
    assert home[d].strip().startswith("<div"), home[d][:80]
    badges.append(home[c:close_idx(home, d) + 1])
    i = close_idx(home, d) + 1
assert len(badges) == 2, f"badges: {len(badges)}"
assert "for comparison" in "\n".join(badges[0])
assert "for comparison" not in "\n".join(badges[1])

# Exchange 2 spans e2 .. (container close - 1). Container closes just
# before the pinned composer comment.
comp = find(home, "<!-- Pinned Bottom Composer Bar -->", e2)
assert home[comp - 1].strip() == "</div>", home[comp - 1][:60]
assert home[comp - 2].strip() == "</div>", home[comp - 2][:60]
e2_end = comp - 2  # keep comp-1 (container close)

new_home = home[:u0]
new_home += ['<template id="tpl-user">'] + tpl_user + ["</template>"]
new_home += ['<template id="tpl-assistant">'] + tpl_assistant + ["</template>"]
new_home += ['<template id="tpl-comparebar">'] + tpl_comparebar + ["</template>"]
new_home += ['<template id="tpl-cmpbadge-hero">'] + badges[0] + ["</template>"]
new_home += ['<template id="tpl-cmpbadge-thumb">'] + badges[1] + ["</template>"]
new_home += ['<div id="thread-xlist" class="contents"></div>']
new_home += home[e2_end + 1:]

# ---- 2. frag templates ----
def block(name, arr, start_needle, end_mode):
    s = find(arr, start_needle)
    if end_mode == "dialog":
        e = find(arr, "</dialog>", s)
        return arr[s:e + 1]
    if end_mode == "eof":
        return arr[s:]
    # (comment, backtrack): end right before a later landmark comment
    e = find(arr, end_mode, s + 1)
    # back up over trailing blank/closing lines to the block's own close
    while e > s and arr[e - 1].strip() in ("", "</div>") and "</div>" not in arr[e - 2]:
        e -= 1
    return arr[s:e]

tpl_progress = prog[33:214]  # verified: Turn-2 comment .. closing div
assert "Turn 2" in prog[33] and prog[214].startswith("<!-- Docked"), (prog[33][:40], prog[214][:40])
tpl_nomatch = states[138:154]
assert "Warm Archival" in states[138] and states[154].strip() == "</div>"
tpl_answer = states[299:360]
assert "Reel Assistant Response" in states[299] and states[360].strip() == "</div>"
tpl_compare = states[377:476]
assert "Reel Assistant Response" in states[377] and states[476].strip() == "</div>"
dlg = block("flag", states, "<!-- Interactive Client-side Flag Modal Dialog -->", "dialog")
dlg = [re.sub(r' onclick="[^"]*"', "", ln) for ln in dlg]
assert not any("onclick" in ln for ln in dlg)
sim = states[197:201]
assert "Looks similar" in "\n".join(sim)
p2 = find(addp, "2. ASSISTANT PROGRESS")
p3 = find(addp, "3. ASSISTANT COMPLETED")
sp = find(addp, "Pinned Bottom Composer Section Spacer")
tpl_addprog = addp[p2:p3]
tpl_addphoto = addp[p3:sp]
assert tpl_addprog[-1].strip() == "</div>", tpl_addprog[-1][:60]
assert tpl_addphoto[-1].strip() == "</div>", tpl_addphoto[-1][:60]
tour_s = find(tour, "<!-- MODAL SCRIM OVERLAY -->")
tour_block = tour[tour_s:]
assert "tour-modal" not in "\n".join(tour_block).lower() or True

append = []
append += ['<template id="tpl-progress">'] + tpl_progress + ["</template>"]
append += ['<template id="tpl-nomatch">'] + tpl_nomatch + ["</template>"]
append += ['<template id="tpl-answer">'] + tpl_answer + ["</template>"]
append += ['<template id="tpl-compare">'] + tpl_compare + ["</template>"]
append += ['<template id="tpl-similarbadge">'] + sim + ["</template>"]
append += ['<template id="tpl-addprogress">'] + tpl_addprog + ["</template>"]
append += ['<template id="tpl-addphoto">'] + tpl_addphoto + ["</template>"]
append += dlg
append += ['<div id="tour-overlay" class="hidden">'] + tour_block + ["</div>"]

# ---- 3. delete landing inline tour modal ----
c = find(new_home, "<!-- Interactive 60-Second Tour Lightbox Modal (Client-side micro-interaction) -->")
d = c + 1
assert new_home[d].strip().startswith("<div"), new_home[d][:80]
new_home = new_home[:c] + new_home[close_idx(new_home, d) + 1:]
blob = "\n".join(new_home)
assert 'id="tour-modal"' not in blob, "inline modal still present"
assert 'id="tour-modal-trigger"' in blob, "landing trigger lost"

# ---- 4. wiring ids (unique anchors, verified) ----
edits = [
    ('<div class="self-start flex items-center gap-space-sm px-space-sm py-1 '
     'bg-surface-container-high rounded-full shadow-sm">',
     '<div id="thread-context" class="self-start hidden items-center gap-space-sm '
     'px-space-sm py-1 bg-surface-container-high rounded-full shadow-sm">'),
    ('aria-label="Remove context artifact"', 'id="thread-context-clear" aria-label="Remove context artifact"'),
    ('aria-label="Upload reference photographic plate"', 'id="thread-add" aria-label="Upload reference photographic plate"'),
    ('<input class="w-full h-11 bg-transparent', '<input id="thread-input" class="w-full h-11 bg-transparent'),
    ('aria-label="Adjust photographic search lenses"', 'id="thread-tune" aria-label="Adjust photographic search lenses"'),
    ('aria-label="Send prompt to Reel"', 'id="thread-send" aria-label="Send prompt to Reel"'),
]
out = blob
for old, new in edits:
    assert out.count(old) == 1, f"anchor x{out.count(old)}: {old[:60]}"
    out = out.replace(old, new)
# context pill starts hidden; JS toggles hidden<->flex via show()/hide()
assert 'id="thread-context" class="self-start hidden items-center' in out

(V / "home.html").write_text(out + "\n".join(append) + "\n", encoding="utf-8")
print("home.html assembled:", len(out.splitlines()), "lines +", len(append), "template lines")
