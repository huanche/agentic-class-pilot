from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..types import UNSET, Unset
from typing import cast
from uuid import UUID






T = TypeVar("T", bound="GetSessionLearningContextBody")



@_attrs_define
class GetSessionLearningContextBody:
    """
        Attributes:
            course_id (UUID):
            user_id (UUID):
            lesson_id (None | str | Unset):
     """

    course_id: UUID
    user_id: UUID
    lesson_id: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        course_id = str(self.course_id)

        user_id = str(self.user_id)

        lesson_id: None | str | Unset
        if isinstance(self.lesson_id, Unset):
            lesson_id = UNSET
        else:
            lesson_id = self.lesson_id


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "course_id": course_id,
            "user_id": user_id,
        })
        if lesson_id is not UNSET:
            field_dict["lesson_id"] = lesson_id

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        course_id = UUID(d.pop("course_id"))




        user_id = UUID(d.pop("user_id"))




        def _parse_lesson_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        lesson_id = _parse_lesson_id(d.pop("lesson_id", UNSET))


        get_session_learning_context_body = cls(
            course_id=course_id,
            user_id=user_id,
            lesson_id=lesson_id,
        )


        get_session_learning_context_body.additional_properties = d
        return get_session_learning_context_body

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
