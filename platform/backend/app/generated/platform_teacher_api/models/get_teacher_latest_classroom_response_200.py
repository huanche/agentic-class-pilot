from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast






T = TypeVar("T", bound="GetTeacherLatestClassroomResponse200")



@_attrs_define
class GetTeacherLatestClassroomResponse200:
    """
        Attributes:
            classroom_id (None | str):
     """

    classroom_id: None | str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        classroom_id: None | str
        classroom_id = self.classroom_id


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "classroomId": classroom_id,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        def _parse_classroom_id(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        classroom_id = _parse_classroom_id(d.pop("classroomId"))


        get_teacher_latest_classroom_response_200 = cls(
            classroom_id=classroom_id,
        )


        get_teacher_latest_classroom_response_200.additional_properties = d
        return get_teacher_latest_classroom_response_200

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
