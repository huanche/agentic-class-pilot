from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
  from ..models.get_teacher_publication_verdict_response_200_publication_type_1 import GetTeacherPublicationVerdictResponse200PublicationType1





T = TypeVar("T", bound="GetTeacherPublicationVerdictResponse200")



@_attrs_define
class GetTeacherPublicationVerdictResponse200:
    """
        Attributes:
            publication (GetTeacherPublicationVerdictResponse200PublicationType1 | None):
            published (bool):
     """

    publication: GetTeacherPublicationVerdictResponse200PublicationType1 | None
    published: bool
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.get_teacher_publication_verdict_response_200_publication_type_1 import GetTeacherPublicationVerdictResponse200PublicationType1
        publication: dict[str, Any] | None
        if isinstance(self.publication, GetTeacherPublicationVerdictResponse200PublicationType1):
            publication = self.publication.to_dict()
        else:
            publication = self.publication

        published = self.published


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "publication": publication,
            "published": published,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.get_teacher_publication_verdict_response_200_publication_type_1 import GetTeacherPublicationVerdictResponse200PublicationType1
        d = dict(src_dict)
        def _parse_publication(data: object) -> GetTeacherPublicationVerdictResponse200PublicationType1 | None:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                publication_type_1 = GetTeacherPublicationVerdictResponse200PublicationType1.from_dict(data)



                return publication_type_1
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(GetTeacherPublicationVerdictResponse200PublicationType1 | None, data)

        publication = _parse_publication(d.pop("publication"))


        published = d.pop("published")

        get_teacher_publication_verdict_response_200 = cls(
            publication=publication,
            published=published,
        )


        get_teacher_publication_verdict_response_200.additional_properties = d
        return get_teacher_publication_verdict_response_200

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
