import numpy as np

from app import audio as A
from app.text import apply_pronunciations, segment_script, split_sentences


def test_sentence_split_keeps_abbreviations():
    s = split_sentences("Dr. Smith arrived at 9 a.m. today. He was late! Was he? Yes.")
    assert s[0].startswith("Dr. Smith")
    assert "He was late!" in s


def test_segment_script_paragraphs_and_merging():
    chunks = segment_script("Hi. This is the first paragraph with a sentence.\n\nSecond paragraph here. And more.")
    assert [c.paragraph_index for c in chunks] == [0, 1]
    assert chunks[0].text.startswith("Hi. This")  # short "Hi." merged with next sentence


def test_long_sentence_is_split():
    long = ", ".join(["this is a clause that keeps going"] * 30) + "."
    chunks = segment_script(long, max_chars=200)
    assert len(chunks) > 1 and all(len(c.text) <= 200 for c in chunks)


def test_pronunciations_whole_word():
    out = apply_pronunciations("GIF files and gifts", [{"term": "gif", "say": "jif"}])
    assert out == "jif files and gifts"


def test_quality_flags_short_and_quiet():
    q = A.analyze_quality(np.zeros(24000 * 2, dtype=np.float32), 24000)
    assert not q["usable"] and q["grade"] == "poor"


def test_effects_change_duration():
    sr = 24000
    x = (0.3 * np.sin(2 * np.pi * 220 * np.arange(sr * 2) / sr)).astype(np.float32)
    faster = A.apply_effects(x, sr, speed=1.25)
    assert abs(faster.size / x.size - 0.8) < 0.03
    shifted = A.apply_effects(x, sr, pitch_semitones=3)
    assert abs(shifted.size / x.size - 1.0) < 0.03  # pitch shift keeps duration


def test_encode_mp3_has_disclosure_tag():
    sr = 24000
    x = (0.2 * np.sin(2 * np.pi * 220 * np.arange(sr) / sr)).astype(np.float32)
    data = A.encode(x, sr, "mp3", bitrate_kbps=128, out_sr=44100, metadata={"comment": "AI-generated"})
    assert data[:3] == b"ID3" and b"AI-generated" in data
