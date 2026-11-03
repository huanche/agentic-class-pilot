from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..types import UNSET, Unset
from typing import cast






T = TypeVar("T", bound="PlatformLearningContextV1LessonCatalogItem")



@_attrs_define
class PlatformLearningContextV1LessonCatalogItem:
    """
        Attributes:
            id (str):
            lesson_number (int | None | Unset):
            order (int | None | Unset):
            segment_count (int | Unset):
            teaching_hours (float | None | Unset):
            title (None | str | Unset):
            week (int | None | Unset):
     """

    id: str
    lesson_number: int | None | Unset = UNSET
    order: int | None | Unset = UNSET
    segment_count: int | Unset = UNSET
    teaching_hours: float | None | Unset = UNSET
    title: None | str | Unset = UNSET
    week: int | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        id = self.id

        lesson_number: int | None | Unset
        if isinstance(self.lesson_number, Unset):
            lesson_number = UNSET
        else:
            lesson_number = self.lesson_number

        order: int | None | Unset
        if isinstance(self.order, Unset):
            order = UNSET
        else:
            order = self.order

        segment_count = self.segment_count

        teaching_hours: float | None | Unset
        if isinstance(self.teaching_hours, Unset):
            teaching_hours = UNSET
        else:
            teaching_hours = self.teaching_hours

        title: None | str | Unset
        if isinstance(self.title, Unset):
            title = UNSET
        else:
            title = self.title

        week: int | None | Unset
        if isinstance(self.week, Unset):
            week = UNSET
        else:
            week = self.week


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "id": id,
        })
        if lesson_number is not UNSET:
            field_dict["lessonNumber"] = lesson_number
        if order is not UNSET:
            field_dict["order"] = order
        if segment_count is not UNSET:
            field_dict["segmentCount"] = segment_count
        if teaching_hours is not UNSET:
            field_dict["teachingHours"] = teaching_hours
        if title is not UNSET:
            field_dict["title"] = title
        if week is not UNSET:
            field_dict["week"] = week

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        id = d.pop("id")

        def _parse_lesson_number(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        lesson_number = _parse_lesson_number(d.pop("lessonNumber", UNSET))


        def _parse_order(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        order = _parse_order(d.pop("order", UNSET))


        segment_count = d.pop("segmentCount", UNSET)

        def _parse_teaching_hours(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        teaching_hours = _parse_teaching_hours(d.pop("teachingHours", UNSET))


        def _parse_title(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        title = _parse_title(d.pop("title", UNSET))


        def _parse_week(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        week = _parse_week(d.pop("week", UNSET))


        platform_learning_context_v1_lesson_catalog_item = cls(
            id=id,
            lesson_number=lesson_number,
            order=order,
            segment_count=segment_count,
            teaching_hours=teaching_hours,
            title=title,
            week=week,
        )


        platform_learning_context_v1_lesson_catalog_item.additional_properties = d
        return platform_learning_context_v1_lesson_catalog_item

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
