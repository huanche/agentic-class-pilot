from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast






T = TypeVar("T", bound="GetStudentCourseProgressResponse200")



@_attrs_define
class GetStudentCourseProgressResponse200:
    """
        Attributes:
            ended_sessions (int):
            last_active_at (None | str):
            learned_lessons (int):
            session_count (int):
            stars (int):
     """

    ended_sessions: int
    last_active_at: None | str
    learned_lessons: int
    session_count: int
    stars: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        ended_sessions = self.ended_sessions

        last_active_at: None | str
        last_active_at = self.last_active_at

        learned_lessons = self.learned_lessons

        session_count = self.session_count

        stars = self.stars


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "endedSessions": ended_sessions,
            "lastActiveAt": last_active_at,
            "learnedLessons": learned_lessons,
            "sessionCount": session_count,
            "stars": stars,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        ended_sessions = d.pop("endedSessions")

        def _parse_last_active_at(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        last_active_at = _parse_last_active_at(d.pop("lastActiveAt"))


        learned_lessons = d.pop("learnedLessons")

        session_count = d.pop("sessionCount")

        stars = d.pop("stars")

        get_student_course_progress_response_200 = cls(
            ended_sessions=ended_sessions,
            last_active_at=last_active_at,
            learned_lessons=learned_lessons,
            session_count=session_count,
            stars=stars,
        )


        get_student_course_progress_response_200.additional_properties = d
        return get_student_course_progress_response_200

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
