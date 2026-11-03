from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
  from ..models.published_classroom_view_scenes_item import PublishedClassroomViewScenesItem





T = TypeVar("T", bound="PublishedClassroomView")



@_attrs_define
class PublishedClassroomView:
    """
        Attributes:
            id (str):
            scenes (list[PublishedClassroomViewScenesItem]):
            title (str):
     """

    id: str
    scenes: list[PublishedClassroomViewScenesItem]
    title: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.published_classroom_view_scenes_item import PublishedClassroomViewScenesItem
        id = self.id

        scenes = []
        for scenes_item_data in self.scenes:
            scenes_item = scenes_item_data.to_dict()
            scenes.append(scenes_item)



        title = self.title


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "id": id,
            "scenes": scenes,
            "title": title,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.published_classroom_view_scenes_item import PublishedClassroomViewScenesItem
        d = dict(src_dict)
        id = d.pop("id")

        scenes = []
        _scenes = d.pop("scenes")
        for scenes_item_data in (_scenes):
            scenes_item = PublishedClassroomViewScenesItem.from_dict(scenes_item_data)



            scenes.append(scenes_item)


        title = d.pop("title")

        published_classroom_view = cls(
            id=id,
            scenes=scenes,
            title=title,
        )


        published_classroom_view.additional_properties = d
        return published_classroom_view

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
