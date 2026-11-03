from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
  from ..models.published_classroom_view import PublishedClassroomView





T = TypeVar("T", bound="GetTeacherClassroomContentResponse200")



@_attrs_define
class GetTeacherClassroomContentResponse200:
    """
        Attributes:
            classroom (None | PublishedClassroomView):
     """

    classroom: None | PublishedClassroomView
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.published_classroom_view import PublishedClassroomView
        classroom: dict[str, Any] | None
        if isinstance(self.classroom, PublishedClassroomView):
            classroom = self.classroom.to_dict()
        else:
            classroom = self.classroom


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "classroom": classroom,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.published_classroom_view import PublishedClassroomView
        d = dict(src_dict)
        def _parse_classroom(data: object) -> None | PublishedClassroomView:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                classroom_type_1 = PublishedClassroomView.from_dict(data)



                return classroom_type_1
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | PublishedClassroomView, data)

        classroom = _parse_classroom(d.pop("classroom"))


        get_teacher_classroom_content_response_200 = cls(
            classroom=classroom,
        )


        get_teacher_classroom_content_response_200.additional_properties = d
        return get_teacher_classroom_content_response_200

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
