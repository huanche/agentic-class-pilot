from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..types import UNSET, Unset
from typing import cast

if TYPE_CHECKING:
  from ..models.platform_learning_context_v1_knowledge_package_entries_item_scope import PlatformLearningContextV1KnowledgePackageEntriesItemScope





T = TypeVar("T", bound="PlatformLearningContextV1KnowledgePackageEntriesItem")



@_attrs_define
class PlatformLearningContextV1KnowledgePackageEntriesItem:
    """
        Attributes:
            id (str):
            content (str | Unset):
            resource_type (str | Unset):
            scope (PlatformLearningContextV1KnowledgePackageEntriesItemScope | Unset):
            title (str | Unset):
     """

    id: str
    content: str | Unset = UNSET
    resource_type: str | Unset = UNSET
    scope: PlatformLearningContextV1KnowledgePackageEntriesItemScope | Unset = UNSET
    title: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.platform_learning_context_v1_knowledge_package_entries_item_scope import PlatformLearningContextV1KnowledgePackageEntriesItemScope
        id = self.id

        content = self.content

        resource_type = self.resource_type

        scope: dict[str, Any] | Unset = UNSET
        if not isinstance(self.scope, Unset):
            scope = self.scope.to_dict()

        title = self.title


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "id": id,
        })
        if content is not UNSET:
            field_dict["content"] = content
        if resource_type is not UNSET:
            field_dict["resourceType"] = resource_type
        if scope is not UNSET:
            field_dict["scope"] = scope
        if title is not UNSET:
            field_dict["title"] = title

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.platform_learning_context_v1_knowledge_package_entries_item_scope import PlatformLearningContextV1KnowledgePackageEntriesItemScope
        d = dict(src_dict)
        id = d.pop("id")

        content = d.pop("content", UNSET)

        resource_type = d.pop("resourceType", UNSET)

        _scope = d.pop("scope", UNSET)
        scope: PlatformLearningContextV1KnowledgePackageEntriesItemScope | Unset
        if isinstance(_scope,  Unset):
            scope = UNSET
        else:
            scope = PlatformLearningContextV1KnowledgePackageEntriesItemScope.from_dict(_scope)




        title = d.pop("title", UNSET)

        platform_learning_context_v1_knowledge_package_entries_item = cls(
            id=id,
            content=content,
            resource_type=resource_type,
            scope=scope,
            title=title,
        )


        platform_learning_context_v1_knowledge_package_entries_item.additional_properties = d
        return platform_learning_context_v1_knowledge_package_entries_item

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
