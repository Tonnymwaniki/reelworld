"""One-shot: extract <main> content from final screens into working views.
Keeps markup/classes exactly; drops export head/header/footer/scripts.
Run from the project root:  python p1_extract.py
"""
import re
from pathlib import Path

R = Path("frontend/design/stitch_export_final")
V = Path("frontend/views")


def main_inner(name):
    t = (R / name / "code.html").read_text(encoding="utf-8")
    m = re.search(r"<main[^>]*>(.*)</main>", t, re.S)
    assert m, name
    body = re.sub(r"<script[\s\S]*?</script>", "", m.group(1))
    return body.strip()


def write(path, content):
    p = V / path
    p.write_text(content + "\n", encoding="utf-8")
    print(f"wrote {p} ({len(content) // 1024} KB)")


# Home = landing sections + thread UI + progress/compare/flag/tour templates.
landing = main_inner("reelworld_landing_page")
thread = main_inner("reel_conversation_thread_desktop")
write("home.html",
      "<!-- Reel home: landing hero + sections (before the first message), then the thread. -->\n"
      '<section id="landing">\n' + landing + "\n</section>\n"
      '<section class="hidden" id="thread-wrap">\n' + thread + "\n</section>")

write("credits.html", main_inner("reelworld_photo_credits_license_directory"))
write("about.html", main_inner("reelworld_about_reelworld_reel"))

# Fragments needed as templates / overlays (kept aside, composed by hand).
write("_frag_progress.html", main_inner("chat_live_progress_while_assistant_works"))
write("_frag_states.html", main_inner("reel_reply_states_flag_controls_desktop"))
write("_frag_addphoto.html", main_inner("chat_adding_a_photo_live_place_identification"))
write("_frag_tour.html", main_inner("reelworld_the_60_second_tour"))
