from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..types import UNSET, Unset
from typing import cast

if TYPE_CHECKING:
  from ..models.get_student_course_roster_progress_body_lesson_revisions import GetStudentCourseRosterProgressBodyLessonRevisions





T = TypeVar("T", bound="GetStudentCourseRosterProgressBody")



@_attrs_define
class GetStudentCourseRosterProgressBody:
    """
        Attributes:
            active_session_keys (list[str]):
            lesson_revisions (GetStudentCourseRosterProgressBodyLessonRevisions):
            user_ids (list[str]):
            detail_user_id (None | str | Unset):
     """

    active_session_keys: list[str]
    lesson_revisions: GetStudentCourseRosterProgressBodyLessonRevisions
    user_ids: list[str]
    detail_user_id: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.get_student_course_roster_progress_body_lesson_revisions import GetStudentCourseRosterProgressBodyLessonRevisions
        active_session_keys = self.active_session_keys



        lesson_revisions = self.lesson_revisions.to_dict()

        user_ids = self.user_ids



        detail_user_id: None | str | Unset
        if isinstance(self.detail_user_id, Unset):
            detail_user_id = UNSET
        else:
            detail_user_id = self.detail_user_id


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "activeSessionKeys": active_session_keys,
            "lessonRevisions": lesson_revisions,
            "userIds": user_ids,
        })
        if detail_user_id is not UNSET:
            field_dict["detailUserId"] = detail_user_id

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.get_student_course_roster_progress_body_lesson_revisions import GetStudentCourseRosterProgressBodyLessonRevisions
        d = dict(src_dict)
        active_session_keys = cast(list[str], d.pop("activeSessionKeys"))


        lesson_revisions = GetStudentCourseRosterProgressBodyLessonRevisions.from_dict(d.pop("lessonRevisions"))




        user_ids = cast(list[str], d.pop("userIds"))


        def _parse_detail_user_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        detail_user_id = _parse_detail_user_id(d.pop("detailUserId", UNSET))


        get_student_course_roster_progress_body = cls(
            active_session_keys=active_session_keys,
            lesson_revisions=lesson_revisions,
            user_ids=user_ids,
            detail_user_id=detail_user_id,
        )


        get_student_course_roster_progress_body.additional_properties = d
        return get_student_course_roster_progress_body

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
