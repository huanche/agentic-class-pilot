from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..types import UNSET, Unset
from typing import cast

if TYPE_CHECKING:
  from ..models.learning_context_v1_action import LearningContextV1Action





T = TypeVar("T", bound="LearningContextV1Scene")



@_attrs_define
class LearningContextV1Scene:
    """
        Attributes:
            actions (list[LearningContextV1Action] | Unset):
            id (str | Unset):
            order (int | Unset):
            title (str | Unset):
     """

    actions: list[LearningContextV1Action] | Unset = UNSET
    id: str | Unset = UNSET
    order: int | Unset = UNSET
    title: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.learning_context_v1_action import LearningContextV1Action
        actions: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.actions, Unset):
            actions = []
            for actions_item_data in self.actions:
                actions_item = actions_item_data.to_dict()
                actions.append(actions_item)



        id = self.id

        order = self.order

        title = self.title


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
        })
        if actions is not UNSET:
            field_dict["actions"] = actions
        if id is not UNSET:
            field_dict["id"] = id
        if order is not UNSET:
            field_dict["order"] = order
        if title is not UNSET:
            field_dict["title"] = title

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.learning_context_v1_action import LearningContextV1Action
        d = dict(src_dict)
        _actions = d.pop("actions", UNSET)
        actions: list[LearningContextV1Action] | Unset = UNSET
        if _actions is not UNSET:
            actions = []
            for actions_item_data in _actions:
                actions_item = LearningContextV1Action.from_dict(actions_item_data)



                actions.append(actions_item)


        id = d.pop("id", UNSET)

        order = d.pop("order", UNSET)

        title = d.pop("title", UNSET)

        learning_context_v1_scene = cls(
            actions=actions,
            id=id,
            order=order,
            title=title,
        )


        learning_context_v1_scene.additional_properties = d
        return learning_context_v1_scene

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
