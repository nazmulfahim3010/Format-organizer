"""Pure helpers for formatting profiles (no database, no web framework)."""
from __future__ import annotations

from typing import List

from ..schemas.profile import ROLES, FormattingProfile, rule_paths


def validate_against_analysis(profile: FormattingProfile, analysis: dict) -> List[str]:
    """Problems that would make the profile unusable with this template. Empty list = OK."""
    para_ids = {s["id"] for s in analysis["styles"] if s["type"] == "paragraph"}
    table_ids = {s["id"] for s in analysis["styles"] if s["type"] == "table"}
    problems: List[str] = []
    for role, sid in profile.roles.items():
        if role not in ROLES:
            problems.append(f"Unknown role '{role}'.")
        elif sid not in para_ids:
            problems.append(f"Role '{role}' points to style '{sid}', which does not exist in the template.")
    if profile.table.borders == "template" and profile.table.template_style_id not in table_ids:
        problems.append("Table borders are set to 'template' but no valid table style is chosen.")
    if not profile.roles.get("body") and not any(s.get("default") and s["type"] == "paragraph" for s in analysis["styles"]):
        problems.append("No body style could be determined.")
    return problems


def _get(model, path: str):
    for part in path.split("."):
        model = getattr(model, part)
    return model


def record_user_edits(base: FormattingProfile, edited: FormattingProfile) -> FormattingProfile:
    """Origins are decided by the server: what the client sends in `origins` is ignored. Every rule
    or role that differs from `base` becomes 'user'; the rest keeps base's origin."""
    out = edited.model_copy(deep=True)
    origins = dict(base.origins)
    for path in rule_paths(edited):
        if _get(edited, path) != _get(base, path):
            origins[path] = "user"
    for role in set(base.roles) | set(edited.roles):
        key = f"roles.{role}"
        if role not in edited.roles:
            origins.pop(key, None)
        elif edited.roles[role] != base.roles.get(role):
            origins[key] = "user"
    out.origins = origins
    return out


def carry_over(old: FormattingProfile, new_analysis: dict) -> FormattingProfile:
    """Reuse an approved profile on a new template version.

    Roles that still exist keep the user's choice. Roles whose style vanished
    fall back to the new analysis' suggestion (or are dropped), and the origin
    records that. The result is a DRAFT: the user must approve it again.
    """
    para_ids = {s["id"] for s in new_analysis["styles"] if s["type"] == "paragraph"}
    table_ids = {s["id"] for s in new_analysis["styles"] if s["type"] == "table"}
    p = old.model_copy(deep=True)
    suggested = new_analysis["suggested_roles"]
    for role in list(p.roles):
        if p.roles[role] not in para_ids:
            if role in suggested:
                p.roles[role] = suggested[role]
                p.origins[f"roles.{role}"] = "template"
            else:
                del p.roles[role]
    evidence = new_analysis.get("role_evidence", {})
    for role, sid in suggested.items():
        if role not in p.roles:
            p.roles[role] = sid
            by = evidence.get(role, {}).get("by", "style_id")
            p.origins[f"roles.{role}"] = "inferred" if by == "usage" else "template"
    for role in list(p.origins):
        if role.startswith("roles.") and role[6:] not in p.roles:
            del p.origins[role]
    if p.table.borders == "template" and p.table.template_style_id not in table_ids:
        p.table.borders = "all"
        p.table.template_style_id = None
        p.origins["table.borders"] = "default"
    return p
