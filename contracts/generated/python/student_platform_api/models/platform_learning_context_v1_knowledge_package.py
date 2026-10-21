from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..types import UNSET, Unset
from typing import cast

if TYPE_CHECKING:
  from ..models.platform_learning_context_v1_knowledge_package_entries_item import PlatformLearningContextV1KnowledgePackageEntriesItem





T = TypeVar("T", bound="PlatformLearningContextV1KnowledgePackage")



@_attrs_define
class PlatformLearningContextV1KnowledgePackage:
    """
        Attributes:
            entries (list[PlatformLearningContextV1KnowledgePackageEntriesItem] | Unset):
            summary (str | Unset):
            title (str | Unset):
     """

    entries: list[PlatformLearningContextV1KnowledgePackageEntriesItem] | Unset = UNSET
    summary: str | Unset = UNSET
    title: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.platform_learning_context_v1_knowledge_package_entries_item import PlatformLearningContextV1KnowledgePackageEntriesItem
        entries: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.entries, Unset):
            entries = []
            for entries_item_data in self.entries:
                entries_item = entries_item_data.to_dict()
                entries.append(entries_item)



        summary = self.summary

        title = self.title


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
        })
        if entries is not UNSET:
            field_dict["entries"] = entries
        if summary is not UNSET:
            field_dict["summary"] = summary
        if title is not UNSET:
            field_dict["title"] = title

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.platform_learning_context_v1_knowledge_package_entries_item import PlatformLearningContextV1KnowledgePackageEntriesItem
        d = dict(src_dict)
        _entries = d.pop("entries", UNSET)
        entries: list[PlatformLearningContextV1KnowledgePackageEntriesItem] | Unset = UNSET
        if _entries is not UNSET:
            entries = []
            for entries_item_data in _entries:
                entries_item = PlatformLearningContextV1KnowledgePackageEntriesItem.from_dict(entries_item_data)



                entries.append(entries_item)


        summary = d.pop("summary", UNSET)

        title = d.pop("title", UNSET)

        platform_learning_context_v1_knowledge_package = cls(
            entries=entries,
            summary=summary,
            title=title,
        )


        platform_learning_context_v1_knowledge_package.additional_properties = d
        return platform_learning_context_v1_knowledge_package

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
