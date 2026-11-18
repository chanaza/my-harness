"""Profiles: a tool + an account. Every origin in the harness is a profile.

Someone may have several accounts in the same tool (e.g. a personal and a
work Claude Code). Each is a separate profile, registered once in
core/profiles.yaml; everything else refers to it by its readable id.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from . import yaml_io
from .provenance import now_iso
from .repo import ContentRepo
from .text import slugify


class ProfileError(Exception):
    pass


@dataclass(frozen=True)
class Profile:
    id: str
    tool: str
    label: str
    added_at: str
    description: str | None = None

    @staticmethod
    def make_id(tool: str, label: str) -> str:
        return slugify(f"{tool}-{label}")

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


class ProfileRegistry:
    def __init__(self, repo: ContentRepo) -> None:
        self.repo = repo
        self.path = repo.path(repo.layout.profiles_file)

    def all(self) -> list[Profile]:
        if not self.path.is_file():
            return []
        data = yaml_io.load(self.path.read_text("utf-8")) or {}
        return [Profile(**entry) for entry in data.get("profiles") or []]

    def get(self, profile_id: str) -> Profile:
        for profile in self.all():
            if profile.id == profile_id:
                return profile
        known = ", ".join(p.id for p in self.all()) or "none"
        raise ProfileError(f"Unknown profile {profile_id!r} (registered: {known}). "
                           "Add it with `harness profile add`.")

    def ids(self) -> set[str]:
        return {p.id for p in self.all()}

    def add(self, tool: str, label: str, description: str | None = None,
            profile_id: str | None = None) -> Profile:
        """Register a profile. Adding an existing id with the same tool returns it unchanged."""
        profile_id = profile_id or Profile.make_id(tool, label)
        for existing in self.all():
            if existing.id == profile_id:
                if existing.tool != tool:
                    raise ProfileError(f"Profile {profile_id!r} already exists for tool {existing.tool!r}")
                return existing
        profile = Profile(id=profile_id, tool=tool, label=label, added_at=now_iso(), description=description)
        entries = [p.to_dict() for p in self.all()] + [profile.to_dict()]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            "# Every tool account that feeds this harness. Other files refer to these ids.\n"
            + yaml_io.dump({"profiles": entries}),
            encoding="utf-8",
        )
        return profile
