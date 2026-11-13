import re

from agent_panel.colors import FAMILIES, model_color
from agent_panel.model import Agent
from agent_panel.tree import fmt_burn, render_tree


def ag(id, parent, depth, label="task", model="sonnet 5.5", status="running", burn=10_288, **kw):
    d = dict(id=id, parent_id=parent, depth=depth, label=label, agent_type="x", model=model, effort="medium",
             status=status, burn=burn, cache_read=0, advisor_calls=0, last_advisor_at=None, linked=True)
    d.update(kw)
    return Agent(**d)


def lines(agents, width=80, frame=0, advisor_model=None):
    return render_tree(agents, width, frame, advisor_model).plain.split("\n")


def line_for(ls, needle):
    return next(l for l in ls if needle in l)


def start(line):
    return re.search(r"[a-z]", line).start()


def test_fmt_burn():
    assert fmt_burn(10_288) == "10k"
    assert fmt_burn(1_250_000) == "1.2M"
    assert fmt_burn(950) == "950"


def test_model_colors_distinct():
    assert FAMILIES == ("opus", "sonnet", "haiku", "other")
    cols = {model_color(m) for m in ("opus 5.5", "sonnet 5.5", "haiku 5.5", "fable 5.1")}
    assert len(cols) == 4
    assert model_color("mystery") == model_color("fable 5.1")


def test_tree_nests_children_under_parent():
    ls = lines([ag("main", None, 0, "main", "opus 5.5"), ag("a1", "main", 1, "one"), ag("a2", "a1", 2, "two")])
    assert start(line_for(ls, "two")) > start(line_for(ls, "one")) > start(line_for(ls, "main"))


def test_tree_shows_model_burn_and_status():
    ls = lines([ag("main", None, 0, "main", "opus 5.5"), ag("a1", "main", 1, "work", status="done"), ag("a2", "main", 1, "busy")])
    done, busy = line_for(ls, "work"), line_for(ls, "busy")
    assert "sonnet 5.5" in done and "10k" in done and "✓" in done
    assert "✓" not in busy and busy.rstrip()[-1] in "◐◓◑◒"


def test_tree_marks_unlinked_with_question_mark():
    ls = lines([ag("main", None, 0, "main"), ag("a1", "main", 1, "lost", linked=False), ag("a2", "main", 1, "ok")])
    assert "?" in line_for(ls, "lost") and "?" not in line_for(ls, "ok")


def test_tree_advisor_line():
    ls = lines([ag("main", None, 0, "main", "opus 5.5", advisor_calls=2, last_advisor_at="2026-11-13T14:02:00Z")], advisor_model="fable 5.1")
    l = line_for(ls, "advisor")
    assert "2 calls" in l and "fable 5.1" in l


def test_tree_no_advisor_line_without_calls():
    assert not any("advisor" in l for l in lines([ag("main", None, 0, "main")]))


def test_tree_truncates_at_50_cols():
    ls = lines([ag("main", None, 0, "main", "opus 5.5"), ag("a1", "main", 1, "x" * 200, burn=2_000_000)], width=50)
    assert all(len(l) <= 50 for l in ls)
    l = line_for(ls, "xxx")
    assert "sonnet 5.5" in l and "2.0M" in l and "…" in l


def test_tree_survives_tiny_width():
    ls = lines([ag("main", None, 0, "main", "opus 5.5"), ag("a1", "main", 1, "y" * 50)], width=8)
    assert ls


def test_tree_pulse_moves_with_frame():
    running = [ag("main", None, 0, "main"), ag("a1", "main", 1, "run")]
    assert line_for(lines(running, frame=0), "run") != line_for(lines(running, frame=1), "run")
    done = [ag("main", None, 0, "main"), ag("a1", "main", 1, "fin", status="done")]
    assert line_for(lines(done, frame=0), "fin") == line_for(lines(done, frame=1), "fin")
