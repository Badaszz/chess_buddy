from app.coach import display, pop_sentences, validate


def test_split_never_breaks_inside_brackets():
    s, rest = pop_sentences("Play [[Nf3]]. Then [[O-O]] is")
    assert s == ["Play [[Nf3]]. "] and rest == "Then [[O-O]] is"


def test_validator():
    allowed = {"Nf3", "Nc6"}
    assert validate("Try [[Nf3]] and [[Nc6]].", allowed) == []
    assert validate("Try [[Nxe5+]].", allowed) == ["Nxe5"]     # bracketed, not in facts
    assert validate("Then Bb5 is strong.", allowed) == ["Bb5"]  # unbracketed piece move is still caught
    assert display("Try [[Nf3]].") == "Try Nf3."