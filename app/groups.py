"""Shared fields and validation for creating and editing a group."""

from pydantic import BaseModel

from .models import Group


class GroupForm(BaseModel):
    name: str = ""
    description: str = ""
    hobbies: str = ""
    visibility: str = "public"
    member_limit: str = ""

    @classmethod
    def from_group(cls, group: Group):
        return cls(
            name=group.name,
            description=group.description,
            hobbies=group.hobbies,
            visibility="private" if group.is_private else "public",
            member_limit=str(group.member_limit) if group.member_limit is not None else "",
        )

    def apply_to(self, group: Group, *, member_count: int):
        if not self.name.strip():
            raise ValueError("Enter a group name.")
        if self.visibility not in {"public", "private"}:
            raise ValueError("Choose public or private visibility.")
        try:
            limit = int(self.member_limit) if self.member_limit.strip() else None
            if limit is not None and not 2 <= limit <= 2_147_483_647:
                raise ValueError
        except ValueError as exc:
            raise ValueError("Enter a member limit of at least two, or leave it blank.") from exc
        if limit is not None and limit < member_count:
            raise ValueError("The member limit cannot be lower than the current number of members.")
        group.name = self.name.strip()[:100]
        group.description = self.description.strip()[:500]
        group.hobbies = self.hobbies[:1000]
        group.is_private = self.visibility == "private"
        group.member_limit = limit
