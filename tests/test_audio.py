"""A capture card's sound (framegen/audio.py, framegen/capture.py): held back to meet the picture, picked by name, and
read from a recording standing in for a card. No sound is played: a stand-in output records what it's given."""
import time

import av
import numpy as np
import pytest

from framegen import capture as c
from framegen.audio import DelayLine

RATE, CH = 48000, 2
FRAME = CH * 2


def _pcm(seconds, value=0):
    return np.full(int(round(seconds * RATE)) * CH, value, np.int16).tobytes()


def _blocks_of(line, seconds, block_s=0.01):
    n = int(round(block_s * RATE)) * FRAME
    return b"".join(line.pull(n) for _ in range(int(round(seconds / block_s))))


def test_silence_until_the_delay_then_the_sound_in_order():
    line = DelayLine(RATE, CH)
    line.set_delay(0.1)
    out = b""
    for i in range(30):  # 10 ms in, 10 ms out
        line.push(_pcm(0.01, i + 1))
        out += _blocks_of(line, 0.01)
    v = np.frombuffer(out, np.int16)[::CH]
    first = int(np.argmax(v != 0)) / RATE
    assert 0.06 <= first <= 0.11  # silence while it fills (to within a jump), then...
    sound = v[v != 0]
    assert np.all(np.diff(sound.astype(int)) >= 0) and sound[0] == 1  # ...from the start, in order
    assert abs(line.queued_s - 0.1) < 0.045


def test_the_delay_holds_when_the_card_clock_runs_fast_or_slow():
    for speed in (1.002, 0.998):  # 0.2%: far more than real clocks differ
        line = DelayLine(RATE, CH)
        line.set_delay(0.05)
        got = 0.0
        for i in range(3000):  # 30 s
            got += 0.01 * speed
            line.push(_pcm(round(got, 4) - round(got - 0.01 * speed, 4), 100))
            queued = line.queued_s  # (before the output takes its block)
            line.pull(int(0.01 * RATE) * FRAME)
        assert abs(queued - 0.05) < 0.006, (speed, queued)
        assert line.jumps == 0  # nudged back, by playing a little faster or slower


def test_a_big_change_jumps():
    line = DelayLine(RATE, CH)
    line.set_delay(0.3)
    for _ in range(60):
        line.push(_pcm(0.01, 7))
        line.pull(int(0.01 * RATE) * FRAME)
    line.set_delay(0.03)
    line.push(_pcm(0.01, 7))
    line.pull(int(0.01 * RATE) * FRAME)
    assert line.queued_s < 0.05 and line.jumps >= 1
    n = int(0.01 * RATE) * FRAME
    assert len(line.pull(n)) == n


def test_the_cards_sound_device_is_found_by_name():
    D = c.Device
    devs = [D("USB3.0 Capture", "video"), D("Digital Audio Interface (USB3.0 Capture)", "audio"),
            D("Microphone (Realtek Audio)", "audio"), D("Cam Link 4K", "video"), D("Cam Link 4K", "audio"),
            D("Game Capture HD60 X", "video"), D("Game Capture HD60 X Audio", "audio")]
    assert c.pick_audio("USB3.0 Capture", devs) == "Digital Audio Interface (USB3.0 Capture)"
    assert c.pick_audio("Cam Link 4K", devs) == "Cam Link 4K"
    assert c.pick_audio("Game Capture HD60 X", devs) == "Game Capture HD60 X Audio"
    assert c.pick_audio("USB Video", devs) is None  # generic words only: no guess
    assert c.pick_audio("Elgato 4K X", [D("Elgato 4K X", "video"), D("Line (Elgato 4K X)", "audio"),
                                         D("Line (Elgato Wave)", "audio")]) == "Line (Elgato 4K X)"


class _Out:
    """Stands in for framegen.audio.Player."""

    def __init__(self, rate, channels):
        self.rate, self.channels, self.pushed, self.delays = rate, channels, [], []

    def push(self, pcm):
        self.pushed.append((time.perf_counter(), pcm))

    def set_delay(self, s):
        self.delays.append(s)

    def close(self):
        pass


def _clip(path, seconds=1.0, fps=60, flash=0.5):
    """A recording with a flash in the picture and a click in the sound at the same moment."""
    out = av.open(path, "w", format="matroska")
    vs = out.add_stream("mpeg4", rate=fps)
    vs.width, vs.height, vs.pix_fmt = 64, 48, "yuv420p"
    aus = out.add_stream("pcm_s16le", rate=RATE, layout="stereo")
    per = RATE // fps
    for i in range(int(seconds * fps)):
        img = np.full((48, 64, 3), 230 if i == int(flash * fps) else 20, np.uint8)
        f = av.VideoFrame.from_ndarray(img, format="bgr24")
        f.pts = i
        for p in vs.encode(f):
            out.mux(p)
        a = np.zeros((1, per * CH), np.int16)
        if i == int(flash * fps):
            a[:] = 20000
        af = av.AudioFrame.from_ndarray(a, format="s16", layout="stereo")
        af.sample_rate, af.pts = RATE, i * per
        for p in aus.encode(af):
            out.mux(p)
    for st in (vs, aus):
        for p in st.encode(None):
            out.mux(p)
    out.close()


def test_a_recordings_sound_comes_out_with_its_picture(tmp_path):
    path = str(tmp_path / "clip.mkv")
    _clip(path)
    outs = []
    src = c.CardSource.video_file(path, device="cpu", colour=(False, False),
                                  audio=lambda r, ch: outs.append(_Out(r, ch)) or outs[-1])
    assert src.can_delay_audio() and not src.can_press()
    src.set_audio_delay(40)
    ticks = list(src)
    src.close()
    out = outs[0]
    assert (out.rate, out.channels) == (RATE, CH) and out.delays == [pytest.approx(0.04)]
    flash = next(t for t in ticks if t.frame.float().mean() > 120)
    click = next(t for t, pcm in out.pushed if np.abs(np.frombuffer(pcm, np.int16)).max() > 10000)
    assert abs(click - flash.t_arrival) < 0.04  # out with the picture, not when the file was read ahead
    total = sum(len(pcm) for _, pcm in out.pushed) / FRAME / RATE
    assert 0.9 < total < 1.1


def test_no_sound_wanted_or_none_there(tmp_path):
    path = str(tmp_path / "clip.mkv")
    _clip(path, seconds=0.2)
    src = c.CardSource.video_file(path, device="cpu", colour=(False, False))  # audio=None: the picture only
    assert not src.can_delay_audio() and src.astream is None
    assert len(list(src)) == 12
    src.close()


def test_a_card_with_no_sound_device_of_its_own_tries_its_video_device_for_sound(monkeypatch):
    """The AVerMedia GC573 (issue 9): its sound is a pin on the video device, so Windows lists no sound device."""
    import types
    import run
    from framegen import capture as c
    name = "AVerMedia HD Capture GC573 1"
    monkeypatch.setattr(c, "list_devices", lambda: [c.Device(name, "video"), c.Device("OBS Virtual Camera", "video"),
                                                    c.Device("Microphone (USB Audio)", "audio")])
    monkeypatch.setattr(c.CardSource, "open", classmethod(lambda cls, *args, **kw: kw))
    monkeypatch.setattr(run, "sound_player", lambda: object())
    a = types.SimpleNamespace(capture_backend="pyav", capture_colour="auto", capture_audio="auto", capture=name,
                              capture_format="auto", capture_fps=60.0)
    assert run.open_capture(a, 1920, 1080, None)["audio_device"] == name


def test_no_sound_on_the_video_device_plays_the_picture_alone(monkeypatch, capsys):
    import av
    from framegen import capture as c
    name = "AVerMedia HD Capture GC573 1"
    tried = []

    def fake_open(url, **kw):
        tried.append(url)
        raise av.error.OSError(5, "Could not find audio only device with name")

    monkeypatch.setattr(av, "open", fake_open)
    monkeypatch.setattr(c, "_open_card", lambda device, opts: "picture only")
    monkeypatch.setattr(c.CardSource, "__init__", lambda self, container, *a, **kw: setattr(self, "container", container))
    src = c.CardSource.open(name, mode=c.Mode("nv12", True, 1920, 1080, 60.0, 60.0), audio_device=name, audio=object())
    assert tried == [f"video={name}:audio={name}"] and src.container == "picture only"
    assert "no sound from the card itself" in capsys.readouterr().out
