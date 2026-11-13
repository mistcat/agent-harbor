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
