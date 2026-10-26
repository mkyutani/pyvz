from pyvz.ui.screen import COVERED, PLAIN, Screen, Style, clip, clip_start, text_width

RED = Style(fg=1)


def test_put_and_text():
    screen = Screen(6, 2)
    assert screen.put(0, 1, "abc") == 4
    assert screen.text(0) == " abc  "


def test_put_clips_at_the_right_edge():
    screen = Screen(4, 1)
    assert screen.put(0, 2, "abc") == 4
    assert screen.text(0) == "  ab"


def test_wide_character_covers_two_cells():
    screen = Screen(4, 1)
    screen.put(0, 0, "あ")
    assert screen.chars[0][:2] == ["あ", COVERED]


def test_wide_character_that_does_not_fit_leaves_a_space():
    screen = Screen(3, 1)
    screen.put(0, 0, "abあ")
    assert screen.chars[0] == ["a", "b", " "]


def test_writing_over_half_a_wide_character_clears_the_other_half():
    screen = Screen(4, 1)
    screen.put(0, 0, "あい")
    screen.put(0, 1, "x")
    assert screen.chars[0] == [" ", "x", "い", COVERED]
    screen.put(0, 2, "y")
    assert screen.chars[0] == [" ", "x", "y", " "]


def test_wide_character_over_the_half_of_another():
    screen = Screen(5, 1)
    screen.put(0, 0, "あい")
    screen.put(0, 1, "う")
    assert screen.chars[0] == [" ", "う", COVERED, " ", " "]


def test_zero_width_characters_join_the_one_before():
    screen = Screen(4, 1)
    screen.put(0, 0, "éx")
    assert screen.chars[0][:2] == ["é", "x"]


def test_render_from_nothing_clears_and_draws_everything():
    screen = Screen(3, 1)
    screen.put(0, 0, "ab")
    out = screen.render(None)
    assert "\x1b[2J" in out
    assert "\x1b[1;1H" in out
    assert "ab " in out


def test_render_sends_only_changes():
    before = Screen(5, 2)
    before.put(0, 0, "hello")
    after = Screen(5, 2)
    after.put(0, 0, "help!")
    out = after.render(before)
    assert "\x1b[2J" not in out
    assert "\x1b[1;4H\x1b[0mp!" in out
    assert "hel" not in out


def test_render_places_the_character_after_a_wide_one_explicitly():
    before = Screen(4, 1)
    after = Screen(4, 1)
    after.put(0, 0, "あb")
    out = after.render(before)
    assert "あ\x1b[1;3Hb" in out


def test_render_styles_and_cursor():
    before = Screen(3, 1)
    after = Screen(3, 1)
    after.put(0, 0, "a", RED)
    after.cursor = (0, 2)
    out = after.render(before)
    assert RED.sgr() + "a" in out
    assert out.endswith("\x1b[0m\x1b[1;3H\x1b[?25h\x1b[?2026l")


def test_sgr():
    assert PLAIN.sgr() == "\x1b[0m"
    assert Style(fg=3, bold=True).sgr() == "\x1b[0;1;33m"
    assert Style(fg=8, bg=12, reverse=True).sgr() == "\x1b[0;7;90;104m"
    assert Style(fg=200).sgr() == "\x1b[0;38;5;200m"


def test_widths_and_clipping():
    assert text_width("aあ") == 3
    assert clip("aあb", 2) == "a"
    assert clip_start("abcdef", 4) == "…def"
    assert clip_start("abc", 4) == "abc"
