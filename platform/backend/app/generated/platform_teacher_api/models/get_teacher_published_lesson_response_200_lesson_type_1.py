from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..types import UNSET, Unset
from typing import cast

if TYPE_CHECKING:
  from ..models.published_classroom_view import PublishedClassroomView





T = TypeVar("T", bound="GetTeacherPublishedLessonResponse200LessonType1")



@_attrs_define
class GetTeacherPublishedLessonResponse200LessonType1:
    """
        Attributes:
            classroom (PublishedClassroomView):
            classroom_id (str):
            course_id (str):
            lesson_id (str):
            published_at (float | None | Unset):
     """

    classroom: PublishedClassroomView
    classroom_id: str
    course_id: str
    lesson_id: str
    published_at: float | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.published_classroom_view import PublishedClassroomView
        classroom = self.classroom.to_dict()

        classroom_id = self.classroom_id

        course_id = self.course_id

        lesson_id = self.lesson_id

        published_at: float | None | Unset
        if isinstance(self.published_at, Unset):
            published_at = UNSET
        else:
            published_at = self.published_at


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "classroom": classroom,
            "classroomId": classroom_id,
            "courseId": course_id,
            "lessonId": lesson_id,
        })
        if published_at is not UNSET:
            field_dict["publishedAt"] = published_at

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.published_classroom_view import PublishedClassroomView
        d = dict(src_dict)
        classroom = PublishedClassroomView.from_dict(d.pop("classroom"))




        classroom_id = d.pop("classroomId")

        course_id = d.pop("courseId")

        lesson_id = d.pop("lessonId")

        def _parse_published_at(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        published_at = _parse_published_at(d.pop("publishedAt", UNSET))


        get_teacher_published_lesson_response_200_lesson_type_1 = cls(
            classroom=classroom,
            classroom_id=classroom_id,
            course_id=course_id,
            lesson_id=lesson_id,
            published_at=published_at,
        )


        get_teacher_published_lesson_response_200_lesson_type_1.additional_properties = d
        return get_teacher_published_lesson_response_200_lesson_type_1

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
