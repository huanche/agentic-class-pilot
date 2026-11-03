from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..types import UNSET, Unset
from typing import cast

if TYPE_CHECKING:
  from ..models.learning_context_v1_classroom_type_0 import LearningContextV1ClassroomType0





T = TypeVar("T", bound="PlatformLearningContextV1LessonsItem")



@_attrs_define
class PlatformLearningContextV1LessonsItem:
    """
        Attributes:
            classroom (LearningContextV1ClassroomType0 | None):
            id (str):
            title (None | str):
            lesson_number (int | None | Unset):
            order (int | Unset):
            teaching_hours (float | None | Unset):
            week (int | None | Unset):
     """

    classroom: LearningContextV1ClassroomType0 | None
    id: str
    title: None | str
    lesson_number: int | None | Unset = UNSET
    order: int | Unset = UNSET
    teaching_hours: float | None | Unset = UNSET
    week: int | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.learning_context_v1_classroom_type_0 import LearningContextV1ClassroomType0
        classroom: dict[str, Any] | None
        if isinstance(self.classroom, LearningContextV1ClassroomType0):
            classroom = self.classroom.to_dict()
        else:
            classroom = self.classroom

        id = self.id

        title: None | str
        title = self.title

        lesson_number: int | None | Unset
        if isinstance(self.lesson_number, Unset):
            lesson_number = UNSET
        else:
            lesson_number = self.lesson_number

        order = self.order

        teaching_hours: float | None | Unset
        if isinstance(self.teaching_hours, Unset):
            teaching_hours = UNSET
        else:
            teaching_hours = self.teaching_hours

        week: int | None | Unset
        if isinstance(self.week, Unset):
            week = UNSET
        else:
            week = self.week


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "classroom": classroom,
            "id": id,
            "title": title,
        })
        if lesson_number is not UNSET:
            field_dict["lessonNumber"] = lesson_number
        if order is not UNSET:
            field_dict["order"] = order
        if teaching_hours is not UNSET:
            field_dict["teachingHours"] = teaching_hours
        if week is not UNSET:
            field_dict["week"] = week

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.learning_context_v1_classroom_type_0 import LearningContextV1ClassroomType0
        d = dict(src_dict)
        def _parse_classroom(data: object) -> LearningContextV1ClassroomType0 | None:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                componentsschemas_learning_context_v1_classroom_type_0 = LearningContextV1ClassroomType0.from_dict(data)



                return componentsschemas_learning_context_v1_classroom_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(LearningContextV1ClassroomType0 | None, data)

        classroom = _parse_classroom(d.pop("classroom"))


        id = d.pop("id")

        def _parse_title(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        title = _parse_title(d.pop("title"))


        def _parse_lesson_number(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        lesson_number = _parse_lesson_number(d.pop("lessonNumber", UNSET))


        order = d.pop("order", UNSET)

        def _parse_teaching_hours(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        teaching_hours = _parse_teaching_hours(d.pop("teachingHours", UNSET))


        def _parse_week(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        week = _parse_week(d.pop("week", UNSET))


        platform_learning_context_v1_lessons_item = cls(
            classroom=classroom,
            id=id,
            title=title,
            lesson_number=lesson_number,
            order=order,
            teaching_hours=teaching_hours,
            week=week,
        )


        platform_learning_context_v1_lessons_item.additional_properties = d
        return platform_learning_context_v1_lessons_item

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
