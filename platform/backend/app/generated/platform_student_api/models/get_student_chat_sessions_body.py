from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..types import UNSET, Unset
from typing import cast






T = TypeVar("T", bound="GetStudentChatSessionsBody")



@_attrs_define
class GetStudentChatSessionsBody:
    """
        Attributes:
            user_ids (list[str]):
            classroom_id (None | str | Unset):
            lesson_id (None | str | Unset):
            limit (int | Unset):
            offset (int | None | Unset):
     """

    user_ids: list[str]
    classroom_id: None | str | Unset = UNSET
    lesson_id: None | str | Unset = UNSET
    limit: int | Unset = UNSET
    offset: int | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        user_ids = self.user_ids



        classroom_id: None | str | Unset
        if isinstance(self.classroom_id, Unset):
            classroom_id = UNSET
        else:
            classroom_id = self.classroom_id

        lesson_id: None | str | Unset
        if isinstance(self.lesson_id, Unset):
            lesson_id = UNSET
        else:
            lesson_id = self.lesson_id

        limit = self.limit

        offset: int | None | Unset
        if isinstance(self.offset, Unset):
            offset = UNSET
        else:
            offset = self.offset


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "userIds": user_ids,
        })
        if classroom_id is not UNSET:
            field_dict["classroomId"] = classroom_id
        if lesson_id is not UNSET:
            field_dict["lessonId"] = lesson_id
        if limit is not UNSET:
            field_dict["limit"] = limit
        if offset is not UNSET:
            field_dict["offset"] = offset

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        user_ids = cast(list[str], d.pop("userIds"))


        def _parse_classroom_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        classroom_id = _parse_classroom_id(d.pop("classroomId", UNSET))


        def _parse_lesson_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        lesson_id = _parse_lesson_id(d.pop("lessonId", UNSET))


        limit = d.pop("limit", UNSET)

        def _parse_offset(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        offset = _parse_offset(d.pop("offset", UNSET))


        get_student_chat_sessions_body = cls(
            user_ids=user_ids,
            classroom_id=classroom_id,
            lesson_id=lesson_id,
            limit=limit,
            offset=offset,
        )


        get_student_chat_sessions_body.additional_properties = d
        return get_student_chat_sessions_body

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
