"""Profiles: a tool + an account + where it runs. Every origin in the harness is a profile.

Someone may have several accounts in the same tool (a personal and a work
Claude Code), and the same account may run locally and in the cloud with
different files. Each combination is a separate profile, registered once
in core/profiles.yaml; everything else refers to it by its readable id.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import asdict, dataclass

from . import yaml_io
from .provenance import now_iso
from .repo import ContentRepo
from .text import slugify

ENVIRONMENTS = ("local", "cloud")
HEADER = "# Every tool account that feeds this harness. Other files refer to these ids.\n"


class ProfileError(Exception):
    pass


@dataclass(frozen=True)
class Profile:
    id: str
    tool: str
    label: str
    added_at: str
    environment: str | None = None
    description: str | None = None

    @staticmethod
    def make_id(tool: str, label: str, environment: str | None = None) -> str:
        return slugify("-".join(p for p in (tool, label, environment) if p))

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


class ProfileRegistry:
    #: Folders that are organised per profile (renamed together with the profile).
    PROFILE_FOLDERS = ("sessions/{id}", "native/{id}", "core/instructions/{id}", "inbox/conflicts/{id}")

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
            profile_id: str | None = None, environment: str | None = None) -> Profile:
        """Register a profile. Adding an existing id with the same tool returns it unchanged."""
        self._check_environment(environment)
        profile_id = profile_id or Profile.make_id(tool, label, environment)
        for existing in self.all():
            if existing.id == profile_id:
                if existing.tool != tool:
                    raise ProfileError(f"Profile {profile_id!r} already exists for tool {existing.tool!r}")
                return existing
        profile = Profile(id=profile_id, tool=tool, label=label, added_at=now_iso(),
                          environment=environment, description=description)
        self._save(self.all() + [profile])
        return profile

    def update(self, profile_id: str, **fields: str | None) -> Profile:
        """Change label, environment or description of a profile."""
        self._check_environment(fields.get("environment"))
        profiles = self.all()
        current = self.get(profile_id)
        changed = Profile(**{**current.to_dict(), **{k: v for k, v in fields.items() if v is not None}})
        self._save([changed if p.id == profile_id else p for p in profiles])
        return changed

    def rename(self, old: str, new: str) -> list[str]:
        """Rename a profile everywhere in the repository. Returns what was changed."""
        new = slugify(new)
        if new in self.ids():
            raise ProfileError(f"Profile {new!r} already exists")
        current = self.get(old)
        changes = []
        for pattern in self.PROFILE_FOLDERS:
            source = self.repo.path(pattern.format(id=old))
            if source.is_dir():
                target = self.repo.path(pattern.format(id=new))
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(source), str(target))
                changes.append(f"{pattern.format(id=old)} -> {pattern.format(id=new)}")
        reference = re.compile(rf"^(\s*(?:-\s*)?profile:\s*){re.escape(old)}(\s*)$", re.MULTILINE)
        for path in sorted(self.repo.root.rglob("*")):
            if path.suffix not in (".yaml", ".md") or ".git" in path.parts or path == self.path:
                continue
            text = path.read_text("utf-8")
            updated = text
            if old in text:  # provenance/meta references, `native:` keys and storage keys
                updated = reference.sub(rf"\g<1>{new}\g<2>", text)
                updated = updated.replace(f" {old}:", f" {new}:").replace(f" {old}/", f" {new}/")
            if updated != text:
                path.write_text(updated, encoding="utf-8")
                changes.append(path.relative_to(self.repo.root).as_posix())
        renamed = Profile(**{**current.to_dict(), "id": new})
        self._save([renamed if p.id == old else p for p in self.all()])
        return changes

    def _save(self, profiles: list[Profile]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(HEADER + yaml_io.dump({"profiles": [p.to_dict() for p in profiles]}),
                             encoding="utf-8")

    @staticmethod
    def _check_environment(environment: str | None) -> None:
        if environment is not None and environment not in ENVIRONMENTS:
            raise ProfileError(f"environment must be one of {', '.join(ENVIRONMENTS)}")
