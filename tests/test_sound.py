import wave

from agent_panel.sound import WAV, Boomer


def test_boomer_rate_limits():
    b = Boomer(True, player="true")
    assert b.boom(0) is True
    assert b.boom(1) is False
    assert b.boom(2.5) is True


def test_boomer_disabled_and_missing_player():
    assert Boomer(False, player="true").boom(0) is False
    assert Boomer(True, player="no-such-binary-xyz").boom(0) is False


def test_cannon_wav_valid():
    with wave.open(str(WAV)) as w:
        assert w.getnchannels() == 1 and w.getframerate() == 22050
        assert 0.5 <= w.getnframes() / w.getframerate() <= 1.2


# ---- The attention call ----
from agent_panel.session import Snapshot
from agent_panel.sound import AHOY_WAV, ATTENTION_GAP_S, ATTENTION_WAV, Attention, attention_player, waiting_on_user
from tests.test_tree import ag


def snap(turn_ended, sub="done", ship_sub="done", ship="idle", session="s1"):
    return Snapshot(session, [ag("main", None, 0, status="idle"), ag("a1", "main", 1, status=sub),
                              ag("w/main", None, 0, status=ship, ship="w"), ag("w/a1", "w/main", 1, status=ship_sub, ship="w")],
                    0, None, turn_ended)


def test_waiting_on_user_needs_an_ended_turn_and_no_running_subagent():
    assert waiting_on_user(snap(True))
    assert not waiting_on_user(snap(False))
    assert not waiting_on_user(snap(True, sub="running"))
    # A controller that handed work to the fleet waits on the fleet, not on the user.
    assert not waiting_on_user(snap(True, ship="running"))
    assert not waiting_on_user(snap(True, ship_sub="running"))


def rings(a, timeline):
    """Feed (time, snapshot) pairs, polled every half second in between; return the times it rang."""
    out = []
    for (t, sn), nxt in zip(timeline, timeline[1:] + [(timeline[-1][0] + 0.5, None)]):
        while t < nxt[0]:
            if a.update(sn, t):
                out.append(t)
            t += 0.5
    return out


def test_happy_path_rings_once_after_the_settle_time_and_not_again_while_waiting():
    from agent_panel.sound import SETTLE_S
    assert rings(Attention(), [(0, snap(False)), (10, snap(True)), (200, snap(True))]) == [10 + SETTLE_S]


def test_a_quiet_background_subagent_rings_at_most_once_per_ended_turn():
    # The turn ends while a subagent works; its status flaps as it goes quiet (30 s reads "done") and talks.
    timeline = [(0, snap(False)), (5, snap(True, sub="running"))]
    for t in range(40, 400, 40):
        timeline += [(t, snap(True, sub="done")), (t + 10, snap(True, sub="running"))]
    assert len(rings(Attention(), timeline)) <= 1


def test_another_worktrees_session_never_arms_the_call():
    timeline = [(0, snap(True))]  # the flagship was already waiting when the panel started
    for t in range(10, 300, 20):
        timeline += [(t, snap(True, ship="running")), (t + 10, snap(True, ship="idle"))]
    assert rings(Attention(), timeline) == []


def test_a_finishing_subagent_does_not_ring_when_the_controller_resumes_within_the_settle_time():
    from agent_panel.sound import SETTLE_S
    timeline = [(0, snap(False)), (5, snap(True, sub="running")), (60, snap(True)), (60 + SETTLE_S - 2, snap(False))]
    assert rings(Attention(), timeline) == []


def test_the_rate_limit_defers_a_ring_instead_of_dropping_it():
    from agent_panel.sound import SETTLE_S
    a = Attention(min_gap_s=30)
    got = rings(a, [(0, snap(False)), (1, snap(True)), (1 + SETTLE_S + 1, snap(False)), (12, snap(True)), (100, snap(True))])
    assert got == [1 + SETTLE_S, 1 + SETTLE_S + 30]  # the second turn's ring waits out the gap, then sounds


def test_does_not_ring_on_the_first_poll_of_an_idle_session_or_after_a_switch():
    assert rings(Attention(), [(0, snap(True)), (100, snap(True))]) == []
    assert rings(Attention(), [(0, snap(False, session="old")), (1, snap(True, session="new")), (100, snap(True, session="new"))]) == []


def test_a_new_turn_cancels_a_pending_ring():
    assert rings(Attention(), [(0, snap(False)), (1, snap(True)), (2, snap(False)), (100, snap(False))]) == []


def test_attention_player_modes():
    assert attention_player("boom", True).wav == ATTENTION_WAV and attention_player("boom", True).enabled
    ahoy = attention_player("ahoy", True)
    assert ahoy.wav == AHOY_WAV and ahoy.wav.name == "ahoy.wav" and ahoy.wav.exists() and ahoy.enabled
    assert ahoy.player == "afplay" and ahoy.args is None and ahoy.min_gap_s == ATTENTION_GAP_S
    say = attention_player("say", True)
    assert say.player == "say" and say.args == ["Ahoy, matey"]
    assert not attention_player("off", True).enabled
    assert not attention_player("ahoy", False).enabled
    assert not attention_player("boom", False).enabled and not attention_player("say", False).enabled  # --no-sound


def test_say_with_a_missing_player_is_silent():
    from agent_panel.sound import Boomer
    assert Boomer(True, player="no-such-binary-xyz", args=["hi"]).boom(0) is False


def test_attention_wav_is_deeper_and_longer_than_the_cannon():
    with wave.open(str(ATTENTION_WAV)) as w, wave.open(str(WAV)) as c:
        assert w.getnchannels() == 1 and w.getframerate() == 22050
        assert w.getnframes() > 1.5 * c.getnframes()


def test_ahoy_wav_is_a_readable_voice_clip():
    with wave.open(str(AHOY_WAV)) as w:
        assert w.getnchannels() == 1 and w.getframerate() == 44100
        assert 0.8 <= w.getnframes() / w.getframerate() <= 2.5


def test_a_ship_that_only_keeps_watch_does_not_hold_the_call():
    # A controller ship on a Monitor shows running for up to half an hour; the flagship's call must not wait on it.
    s = Snapshot("s1", [ag("main", None, 0, status="idle"),
                        ag("w/main", None, 0, status="running", ship="w", watching=True, controller=True)], 0, None, True)
    assert waiting_on_user(s)
    # An agent ship on watch (a background test run) is still busy: the controller waits on it.
    s.agents[1].controller = False
    assert not waiting_on_user(s)
