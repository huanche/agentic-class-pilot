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





T = TypeVar("T", bound="PublishedLesson")



@_attrs_define
class PublishedLesson:
    """
        Attributes:
            classroom (PublishedClassroomView):
            id (str):
            order (float):
            title (str):
            lesson_number (float | None | Unset):
            published_at (float | None | Unset):
            teaching_hours (float | None | Unset):
            week (float | None | Unset):
     """

    classroom: PublishedClassroomView
    id: str
    order: float
    title: str
    lesson_number: float | None | Unset = UNSET
    published_at: float | None | Unset = UNSET
    teaching_hours: float | None | Unset = UNSET
    week: float | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.published_classroom_view import PublishedClassroomView
        classroom = self.classroom.to_dict()

        id = self.id

        order = self.order

        title = self.title

        lesson_number: float | None | Unset
        if isinstance(self.lesson_number, Unset):
            lesson_number = UNSET
        else:
            lesson_number = self.lesson_number

        published_at: float | None | Unset
        if isinstance(self.published_at, Unset):
            published_at = UNSET
        else:
            published_at = self.published_at

        teaching_hours: float | None | Unset
        if isinstance(self.teaching_hours, Unset):
            teaching_hours = UNSET
        else:
            teaching_hours = self.teaching_hours

        week: float | None | Unset
        if isinstance(self.week, Unset):
            week = UNSET
        else:
            week = self.week


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "classroom": classroom,
            "id": id,
            "order": order,
            "title": title,
        })
        if lesson_number is not UNSET:
            field_dict["lessonNumber"] = lesson_number
        if published_at is not UNSET:
            field_dict["publishedAt"] = published_at
        if teaching_hours is not UNSET:
            field_dict["teachingHours"] = teaching_hours
        if week is not UNSET:
            field_dict["week"] = week

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.published_classroom_view import PublishedClassroomView
        d = dict(src_dict)
        classroom = PublishedClassroomView.from_dict(d.pop("classroom"))




        id = d.pop("id")

        order = d.pop("order")

        title = d.pop("title")

        def _parse_lesson_number(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        lesson_number = _parse_lesson_number(d.pop("lessonNumber", UNSET))


        def _parse_published_at(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        published_at = _parse_published_at(d.pop("publishedAt", UNSET))


        def _parse_teaching_hours(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        teaching_hours = _parse_teaching_hours(d.pop("teachingHours", UNSET))


        def _parse_week(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        week = _parse_week(d.pop("week", UNSET))


        published_lesson = cls(
            classroom=classroom,
            id=id,
            order=order,
            title=title,
            lesson_number=lesson_number,
            published_at=published_at,
            teaching_hours=teaching_hours,
            week=week,
        )


        published_lesson.additional_properties = d
        return published_lesson

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
