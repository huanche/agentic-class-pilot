from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..types import UNSET, Unset
from typing import cast






T = TypeVar("T", bound="GetStudentLearningContextBody")



@_attrs_define
class GetStudentLearningContextBody:
    """
        Attributes:
            launch_token (str):
            lesson_id (None | str | Unset): 可选；选定的已发布课时 ID
     """

    launch_token: str
    lesson_id: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        launch_token = self.launch_token

        lesson_id: None | str | Unset
        if isinstance(self.lesson_id, Unset):
            lesson_id = UNSET
        else:
            lesson_id = self.lesson_id


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "launch_token": launch_token,
        })
        if lesson_id is not UNSET:
            field_dict["lesson_id"] = lesson_id

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        launch_token = d.pop("launch_token")

        def _parse_lesson_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        lesson_id = _parse_lesson_id(d.pop("lesson_id", UNSET))


        get_student_learning_context_body = cls(
            launch_token=launch_token,
            lesson_id=lesson_id,
        )


        get_student_learning_context_body.additional_properties = d
        return get_student_learning_context_body

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
