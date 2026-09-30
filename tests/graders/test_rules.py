from acb_graders.checks import CONTAINERFILE_CHECKS
from acb_graders.rules import render


def test_explicit_arm_lists_every_scored_rule():
    text = render("explicit", "containerfile")
    for check in CONTAINERFILE_CHECKS:
        assert (check.rule in text) == (check.weight > 0)


def test_implicit_arm_adds_nothing():
    assert render("implicit", "containerfile") == ""


def test_check_ids_are_unique_across_families():
    from acb_graders.checks import CHECKS_BY_FAMILY

    ids = [c.id for checks in CHECKS_BY_FAMILY.values() for c in checks]
    assert len(ids) == len(set(ids)), sorted(i for i in ids if ids.count(i) > 1)
