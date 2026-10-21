from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
  from ..models.provision_teacher_course_response_200_course import ProvisionTeacherCourseResponse200Course





T = TypeVar("T", bound="ProvisionTeacherCourseResponse200")



@_attrs_define
class ProvisionTeacherCourseResponse200:
    """
        Attributes:
            course (ProvisionTeacherCourseResponse200Course):
            success (bool):
     """

    course: ProvisionTeacherCourseResponse200Course
    success: bool
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.provision_teacher_course_response_200_course import ProvisionTeacherCourseResponse200Course
        course = self.course.to_dict()

        success = self.success


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "course": course,
            "success": success,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.provision_teacher_course_response_200_course import ProvisionTeacherCourseResponse200Course
        d = dict(src_dict)
        course = ProvisionTeacherCourseResponse200Course.from_dict(d.pop("course"))




        success = d.pop("success")

        provision_teacher_course_response_200 = cls(
            course=course,
            success=success,
        )


        provision_teacher_course_response_200.additional_properties = d
        return provision_teacher_course_response_200

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
