from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..types import UNSET, Unset
from typing import cast






T = TypeVar("T", bound="GetStudentChatMessagesBody")



@_attrs_define
class GetStudentChatMessagesBody:
    """
        Attributes:
            user_ids (list[str]):
            limit (int | Unset):
            offset (int | Unset):
            phase (None | str | Unset):
     """

    user_ids: list[str]
    limit: int | Unset = UNSET
    offset: int | Unset = UNSET
    phase: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        user_ids = self.user_ids



        limit = self.limit

        offset = self.offset

        phase: None | str | Unset
        if isinstance(self.phase, Unset):
            phase = UNSET
        else:
            phase = self.phase


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "userIds": user_ids,
        })
        if limit is not UNSET:
            field_dict["limit"] = limit
        if offset is not UNSET:
            field_dict["offset"] = offset
        if phase is not UNSET:
            field_dict["phase"] = phase

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        user_ids = cast(list[str], d.pop("userIds"))


        limit = d.pop("limit", UNSET)

        offset = d.pop("offset", UNSET)

        def _parse_phase(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        phase = _parse_phase(d.pop("phase", UNSET))


        get_student_chat_messages_body = cls(
            user_ids=user_ids,
            limit=limit,
            offset=offset,
            phase=phase,
        )


        get_student_chat_messages_body.additional_properties = d
        return get_student_chat_messages_body

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
