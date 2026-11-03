from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.get_teacher_published_lesson_response_200_reason_type_1 import GetTeacherPublishedLessonResponse200ReasonType1
from ..models.get_teacher_published_lesson_response_200_reason_type_2_type_1 import GetTeacherPublishedLessonResponse200ReasonType2Type1
from ..models.get_teacher_published_lesson_response_200_reason_type_3_type_1 import GetTeacherPublishedLessonResponse200ReasonType3Type1
from typing import cast

if TYPE_CHECKING:
  from ..models.get_teacher_published_lesson_response_200_lesson_type_1 import GetTeacherPublishedLessonResponse200LessonType1





T = TypeVar("T", bound="GetTeacherPublishedLessonResponse200")



@_attrs_define
class GetTeacherPublishedLessonResponse200:
    """
        Attributes:
            lesson (GetTeacherPublishedLessonResponse200LessonType1 | None):
            published (bool):
            reason (GetTeacherPublishedLessonResponse200ReasonType1 | GetTeacherPublishedLessonResponse200ReasonType2Type1 |
                GetTeacherPublishedLessonResponse200ReasonType3Type1 | None):
     """

    lesson: GetTeacherPublishedLessonResponse200LessonType1 | None
    published: bool
    reason: GetTeacherPublishedLessonResponse200ReasonType1 | GetTeacherPublishedLessonResponse200ReasonType2Type1 | GetTeacherPublishedLessonResponse200ReasonType3Type1 | None
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.get_teacher_published_lesson_response_200_lesson_type_1 import GetTeacherPublishedLessonResponse200LessonType1
        lesson: dict[str, Any] | None
        if isinstance(self.lesson, GetTeacherPublishedLessonResponse200LessonType1):
            lesson = self.lesson.to_dict()
        else:
            lesson = self.lesson

        published = self.published

        reason: None | str
        if isinstance(self.reason, GetTeacherPublishedLessonResponse200ReasonType1):
            reason = self.reason.value
        elif isinstance(self.reason, GetTeacherPublishedLessonResponse200ReasonType2Type1):
            reason = self.reason.value
        elif isinstance(self.reason, GetTeacherPublishedLessonResponse200ReasonType3Type1):
            reason = self.reason.value
        else:
            reason = self.reason


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "lesson": lesson,
            "published": published,
            "reason": reason,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.get_teacher_published_lesson_response_200_lesson_type_1 import GetTeacherPublishedLessonResponse200LessonType1
        d = dict(src_dict)
        def _parse_lesson(data: object) -> GetTeacherPublishedLessonResponse200LessonType1 | None:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                lesson_type_1 = GetTeacherPublishedLessonResponse200LessonType1.from_dict(data)



                return lesson_type_1
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(GetTeacherPublishedLessonResponse200LessonType1 | None, data)

        lesson = _parse_lesson(d.pop("lesson"))


        published = d.pop("published")

        def _parse_reason(data: object) -> GetTeacherPublishedLessonResponse200ReasonType1 | GetTeacherPublishedLessonResponse200ReasonType2Type1 | GetTeacherPublishedLessonResponse200ReasonType3Type1 | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                reason_type_1 = GetTeacherPublishedLessonResponse200ReasonType1(data)



                return reason_type_1
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            try:
                if not isinstance(data, str):
                    raise TypeError()
                reason_type_2_type_1 = GetTeacherPublishedLessonResponse200ReasonType2Type1(data)



                return reason_type_2_type_1
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            try:
                if not isinstance(data, str):
                    raise TypeError()
                reason_type_3_type_1 = GetTeacherPublishedLessonResponse200ReasonType3Type1(data)



                return reason_type_3_type_1
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(GetTeacherPublishedLessonResponse200ReasonType1 | GetTeacherPublishedLessonResponse200ReasonType2Type1 | GetTeacherPublishedLessonResponse200ReasonType3Type1 | None, data)

        reason = _parse_reason(d.pop("reason"))


        get_teacher_published_lesson_response_200 = cls(
            lesson=lesson,
            published=published,
            reason=reason,
        )


        get_teacher_published_lesson_response_200.additional_properties = d
        return get_teacher_published_lesson_response_200

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
