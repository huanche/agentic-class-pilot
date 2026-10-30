from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
  from ..models.get_student_classroom_view_response_200_scenes_item import GetStudentClassroomViewResponse200ScenesItem





T = TypeVar("T", bound="GetStudentClassroomViewResponse200")



@_attrs_define
class GetStudentClassroomViewResponse200:
    """
        Attributes:
            classroom_id (str):
            scenes (list[GetStudentClassroomViewResponse200ScenesItem]):
     """

    classroom_id: str
    scenes: list[GetStudentClassroomViewResponse200ScenesItem]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.get_student_classroom_view_response_200_scenes_item import GetStudentClassroomViewResponse200ScenesItem
        classroom_id = self.classroom_id

        scenes = []
        for scenes_item_data in self.scenes:
            scenes_item = scenes_item_data.to_dict()
            scenes.append(scenes_item)




        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "classroomId": classroom_id,
            "scenes": scenes,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.get_student_classroom_view_response_200_scenes_item import GetStudentClassroomViewResponse200ScenesItem
        d = dict(src_dict)
        classroom_id = d.pop("classroomId")

        scenes = []
        _scenes = d.pop("scenes")
        for scenes_item_data in (_scenes):
            scenes_item = GetStudentClassroomViewResponse200ScenesItem.from_dict(scenes_item_data)



            scenes.append(scenes_item)


        get_student_classroom_view_response_200 = cls(
            classroom_id=classroom_id,
            scenes=scenes,
        )


        get_student_classroom_view_response_200.additional_properties = d
        return get_student_classroom_view_response_200

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
