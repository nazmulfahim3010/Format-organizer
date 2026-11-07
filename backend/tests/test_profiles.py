from app.schemas.profile import FormattingProfile
from app.services.profiles import carry_over, validate_against_analysis
from app.template_engine.analyzer import analyze_template, build_default_profile


def test_default_profile_is_valid_for_its_own_template(templates):
    for n in ("default", "university", "messy", "bangla", "twocol", "rtl"):
        a = analyze_template(templates[n])
        assert validate_against_analysis(build_default_profile(a), a) == [], n


def test_invalid_roles_and_table_style_are_reported(templates):
    a = analyze_template(templates["university"])
    p = build_default_profile(a)
    p.roles["heading_1"] = "Nope"; p.roles["bogus"] = "Normal"; p.table.template_style_id = "Missing"
    msgs = validate_against_analysis(p, a)
    assert len(msgs) == 3 and any("Nope" in m for m in msgs) and any("Unknown role" in m for m in msgs)


def test_carry_over_keeps_user_choices_and_repairs_the_rest(templates):
    old_a = analyze_template(templates["university"])
    old = build_default_profile(old_a)
    old.roles["body"] = "Normal"; old.labels.abstract = "Zusammenfassung"; old.table.header_shading = "EEEEEE"
    new_a = analyze_template(templates["messy"])            # has no heading/caption styles at all
    moved = carry_over(old, new_a)
    assert moved.labels.abstract == "Zusammenfassung" and moved.table.header_shading == "EEEEEE"
    assert "heading_1" not in moved.roles                    # nothing to map to -> generator creates a style
    assert moved.table.borders == "template"                  # TableGrid still exists in the new template
    assert validate_against_analysis(moved, new_a) == []
    new_a["styles"] = [x for x in new_a["styles"] if x["type"] != "table"]
    moved2 = carry_over(old, new_a)                           # table style gone -> direct borders
    assert moved2.table.borders == "all" and moved2.table.template_style_id is None
    assert validate_against_analysis(moved2, new_a) == []
