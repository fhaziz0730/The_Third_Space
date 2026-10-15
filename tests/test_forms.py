import unittest
from datetime import datetime, time, timezone
from types import SimpleNamespace

from app.groups import GroupForm
from app.models import AvailabilityWindow, Group, Membership
from app.profiles import ProfileForm, parse_schedule
from app.scheduling import shared_times


class FormTests(unittest.TestCase):
    def test_invalid_profile_does_not_modify_membership(self):
        member = Membership(
            timezone_name="UTC",
            hobbies="coffee",
            broad_location="Boston",
            latitude=42.36,
            longitude=-71.06,
            travel_radius_km=25,
        )
        member.windows = [AvailabilityWindow(weekday=0, starts_at=time(9), ends_at=time(10))]
        form = ProfileForm(
            timezone_name="America/New_York",
            hobbies=["walking"],
            schedule="1,10:00,12:00",
            latitude="invalid",
        )
        with self.assertRaises(ValueError):
            form.apply_to(member)
        self.assertEqual(member.timezone_name, "UTC")
        self.assertEqual(member.hobbies, "coffee")
        self.assertEqual(member.latitude, 42.36)
        self.assertEqual(member.windows[0].weekday, 0)

    def test_schedule_validation_accepts_adjacent_windows_and_rejects_nested_overlap(self):
        self.assertEqual(len(parse_schedule("0,09:00,10:00\n0,10:00,11:00", "UTC")), 2)
        with self.assertRaisesRegex(ValueError, "overlap on Monday"):
            parse_schedule("0,09:00,13:00\n0,10:00,11:00", "UTC")

    def test_group_metadata_uses_the_same_validation_for_create_and_edit(self):
        group = Group(
            name="Existing", description="Existing description", hobbies="coffee", member_limit=5
        )
        for limit in ("invalid", "0", "-1", "1", "2147483648"):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                GroupForm(name="Edited", member_limit=limit).apply_to(group, member_count=3)
            self.assertEqual(group.name, "Existing")
            self.assertEqual(group.member_limit, 5)
        with self.assertRaisesRegex(ValueError, "current number"):
            GroupForm(name="Edited", member_limit="2").apply_to(group, member_count=3)
        GroupForm(name="  Edited  ", visibility="private", member_limit="4").apply_to(
            group, member_count=3
        )
        self.assertEqual(group.name, "Edited")
        self.assertTrue(group.is_private)
        self.assertEqual(GroupForm.from_group(group).member_limit, "4")

    def test_shared_times_are_unique_and_respect_each_members_timezone(self):
        # All three windows overlap Tuesday 09:00-11:00 UTC in October.
        members = [
            SimpleNamespace(
                timezone_name=zone,
                windows=[AvailabilityWindow(weekday=1, starts_at=time(start), ends_at=time(end))],
            )
            for zone, start, end in (
                ("UTC", 9, 11),
                ("America/New_York", 5, 7),
                ("Europe/London", 10, 12),
            )
        ]
        now = datetime(2026, 10, 12, 8, tzinfo=timezone.utc)
        slots = list(shared_times(members, ["coffee"], now, horizon_days=2))
        self.assertEqual(len(slots), 1)
        self.assertEqual(slots[0].starts_at, datetime(2026, 10, 13, 9, tzinfo=timezone.utc))
        self.assertEqual(len(slots[0].available), 3)
