from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
  from ..models.get_student_classroom_view_response_200_scenes_item_actions_item import GetStudentClassroomViewResponse200ScenesItemActionsItem





T = TypeVar("T", bound="GetStudentClassroomViewResponse200ScenesItem")



@_attrs_define
class GetStudentClassroomViewResponse200ScenesItem:
    """
        Attributes:
            actions (list[GetStudentClassroomViewResponse200ScenesItemActionsItem]):
            id (str):
            order (float):
            title (str):
            type_ (str):
            visible_text (list[str]):
     """

    actions: list[GetStudentClassroomViewResponse200ScenesItemActionsItem]
    id: str
    order: float
    title: str
    type_: str
    visible_text: list[str]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.get_student_classroom_view_response_200_scenes_item_actions_item import GetStudentClassroomViewResponse200ScenesItemActionsItem
        actions = []
        for actions_item_data in self.actions:
            actions_item = actions_item_data.to_dict()
            actions.append(actions_item)



        id = self.id

        order = self.order

        title = self.title

        type_ = self.type_

        visible_text = self.visible_text




        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "actions": actions,
            "id": id,
            "order": order,
            "title": title,
            "type": type_,
            "visibleText": visible_text,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.get_student_classroom_view_response_200_scenes_item_actions_item import GetStudentClassroomViewResponse200ScenesItemActionsItem
        d = dict(src_dict)
        actions = []
        _actions = d.pop("actions")
        for actions_item_data in (_actions):
            actions_item = GetStudentClassroomViewResponse200ScenesItemActionsItem.from_dict(actions_item_data)



            actions.append(actions_item)


        id = d.pop("id")

        order = d.pop("order")

        title = d.pop("title")

        type_ = d.pop("type")

        visible_text = cast(list[str], d.pop("visibleText"))


        get_student_classroom_view_response_200_scenes_item = cls(
            actions=actions,
            id=id,
            order=order,
            title=title,
            type_=type_,
            visible_text=visible_text,
        )


        get_student_classroom_view_response_200_scenes_item.additional_properties = d
        return get_student_classroom_view_response_200_scenes_item

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
