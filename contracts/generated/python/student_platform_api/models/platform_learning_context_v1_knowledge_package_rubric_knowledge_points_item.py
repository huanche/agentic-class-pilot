from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast






T = TypeVar("T", bound="PlatformLearningContextV1KnowledgePackageRubricKnowledgePointsItem")



@_attrs_define
class PlatformLearningContextV1KnowledgePackageRubricKnowledgePointsItem:
    """
        Attributes:
            expected_concepts (list[str]):
            id (str):
            title (str):
     """

    expected_concepts: list[str]
    id: str
    title: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        expected_concepts = self.expected_concepts



        id = self.id

        title = self.title


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "expectedConcepts": expected_concepts,
            "id": id,
            "title": title,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        expected_concepts = cast(list[str], d.pop("expectedConcepts"))


        id = d.pop("id")

        title = d.pop("title")

        platform_learning_context_v1_knowledge_package_rubric_knowledge_points_item = cls(
            expected_concepts=expected_concepts,
            id=id,
            title=title,
        )


        platform_learning_context_v1_knowledge_package_rubric_knowledge_points_item.additional_properties = d
        return platform_learning_context_v1_knowledge_package_rubric_knowledge_points_item

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
