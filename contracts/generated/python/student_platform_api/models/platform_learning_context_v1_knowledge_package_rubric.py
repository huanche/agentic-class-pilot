from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
  from ..models.platform_learning_context_v1_knowledge_package_rubric_knowledge_points_item import PlatformLearningContextV1KnowledgePackageRubricKnowledgePointsItem





T = TypeVar("T", bound="PlatformLearningContextV1KnowledgePackageRubric")



@_attrs_define
class PlatformLearningContextV1KnowledgePackageRubric:
    """
        Attributes:
            knowledge_points (list[PlatformLearningContextV1KnowledgePackageRubricKnowledgePointsItem]):
     """

    knowledge_points: list[PlatformLearningContextV1KnowledgePackageRubricKnowledgePointsItem]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.platform_learning_context_v1_knowledge_package_rubric_knowledge_points_item import PlatformLearningContextV1KnowledgePackageRubricKnowledgePointsItem
        knowledge_points = []
        for knowledge_points_item_data in self.knowledge_points:
            knowledge_points_item = knowledge_points_item_data.to_dict()
            knowledge_points.append(knowledge_points_item)




        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "knowledgePoints": knowledge_points,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.platform_learning_context_v1_knowledge_package_rubric_knowledge_points_item import PlatformLearningContextV1KnowledgePackageRubricKnowledgePointsItem
        d = dict(src_dict)
        knowledge_points = []
        _knowledge_points = d.pop("knowledgePoints")
        for knowledge_points_item_data in (_knowledge_points):
            knowledge_points_item = PlatformLearningContextV1KnowledgePackageRubricKnowledgePointsItem.from_dict(knowledge_points_item_data)



            knowledge_points.append(knowledge_points_item)


        platform_learning_context_v1_knowledge_package_rubric = cls(
            knowledge_points=knowledge_points,
        )


        platform_learning_context_v1_knowledge_package_rubric.additional_properties = d
        return platform_learning_context_v1_knowledge_package_rubric

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
