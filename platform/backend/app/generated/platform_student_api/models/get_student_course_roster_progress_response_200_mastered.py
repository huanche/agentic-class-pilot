from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
  from ..models.get_student_course_roster_progress_response_200_mastered_additional_property import GetStudentCourseRosterProgressResponse200MasteredAdditionalProperty





T = TypeVar("T", bound="GetStudentCourseRosterProgressResponse200Mastered")



@_attrs_define
class GetStudentCourseRosterProgressResponse200Mastered:
    """
     """

    additional_properties: dict[str, GetStudentCourseRosterProgressResponse200MasteredAdditionalProperty] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.get_student_course_roster_progress_response_200_mastered_additional_property import GetStudentCourseRosterProgressResponse200MasteredAdditionalProperty

        field_dict: dict[str, Any] = {}
        for prop_name, prop in self.additional_properties.items():
            field_dict[prop_name] = prop.to_dict()


        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.get_student_course_roster_progress_response_200_mastered_additional_property import GetStudentCourseRosterProgressResponse200MasteredAdditionalProperty
        d = dict(src_dict)
        get_student_course_roster_progress_response_200_mastered = cls(
        )


        additional_properties = {}
        for prop_name, prop_dict in d.items():
            additional_property = GetStudentCourseRosterProgressResponse200MasteredAdditionalProperty.from_dict(prop_dict)



            additional_properties[prop_name] = additional_property

        get_student_course_roster_progress_response_200_mastered.additional_properties = additional_properties
        return get_student_course_roster_progress_response_200_mastered

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> GetStudentCourseRosterProgressResponse200MasteredAdditionalProperty:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: GetStudentCourseRosterProgressResponse200MasteredAdditionalProperty) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
