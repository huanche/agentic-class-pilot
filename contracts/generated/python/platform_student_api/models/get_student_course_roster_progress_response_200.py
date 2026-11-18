from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
  from ..models.get_student_course_roster_progress_response_200_active_item import GetStudentCourseRosterProgressResponse200ActiveItem
  from ..models.get_student_course_roster_progress_response_200_mastered import GetStudentCourseRosterProgressResponse200Mastered
  from ..models.get_student_course_roster_progress_response_200_assessments_item import GetStudentCourseRosterProgressResponse200AssessmentsItem
  from ..models.get_student_course_roster_progress_response_200_totals import GetStudentCourseRosterProgressResponse200Totals





T = TypeVar("T", bound="GetStudentCourseRosterProgressResponse200")



@_attrs_define
class GetStudentCourseRosterProgressResponse200:
    """
        Attributes:
            active (list[GetStudentCourseRosterProgressResponse200ActiveItem]):
            assessments (list[GetStudentCourseRosterProgressResponse200AssessmentsItem]):
            mastered (GetStudentCourseRosterProgressResponse200Mastered):
            totals (GetStudentCourseRosterProgressResponse200Totals):
     """

    active: list[GetStudentCourseRosterProgressResponse200ActiveItem]
    assessments: list[GetStudentCourseRosterProgressResponse200AssessmentsItem]
    mastered: GetStudentCourseRosterProgressResponse200Mastered
    totals: GetStudentCourseRosterProgressResponse200Totals
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.get_student_course_roster_progress_response_200_active_item import GetStudentCourseRosterProgressResponse200ActiveItem
        from ..models.get_student_course_roster_progress_response_200_mastered import GetStudentCourseRosterProgressResponse200Mastered
        from ..models.get_student_course_roster_progress_response_200_assessments_item import GetStudentCourseRosterProgressResponse200AssessmentsItem
        from ..models.get_student_course_roster_progress_response_200_totals import GetStudentCourseRosterProgressResponse200Totals
        active = []
        for active_item_data in self.active:
            active_item = active_item_data.to_dict()
            active.append(active_item)



        assessments = []
        for assessments_item_data in self.assessments:
            assessments_item = assessments_item_data.to_dict()
            assessments.append(assessments_item)



        mastered = self.mastered.to_dict()

        totals = self.totals.to_dict()


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "active": active,
            "assessments": assessments,
            "mastered": mastered,
            "totals": totals,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.get_student_course_roster_progress_response_200_active_item import GetStudentCourseRosterProgressResponse200ActiveItem
        from ..models.get_student_course_roster_progress_response_200_mastered import GetStudentCourseRosterProgressResponse200Mastered
        from ..models.get_student_course_roster_progress_response_200_assessments_item import GetStudentCourseRosterProgressResponse200AssessmentsItem
        from ..models.get_student_course_roster_progress_response_200_totals import GetStudentCourseRosterProgressResponse200Totals
        d = dict(src_dict)
        active = []
        _active = d.pop("active")
        for active_item_data in (_active):
            active_item = GetStudentCourseRosterProgressResponse200ActiveItem.from_dict(active_item_data)



            active.append(active_item)


        assessments = []
        _assessments = d.pop("assessments")
        for assessments_item_data in (_assessments):
            assessments_item = GetStudentCourseRosterProgressResponse200AssessmentsItem.from_dict(assessments_item_data)



            assessments.append(assessments_item)


        mastered = GetStudentCourseRosterProgressResponse200Mastered.from_dict(d.pop("mastered"))




        totals = GetStudentCourseRosterProgressResponse200Totals.from_dict(d.pop("totals"))




        get_student_course_roster_progress_response_200 = cls(
            active=active,
            assessments=assessments,
            mastered=mastered,
            totals=totals,
        )


        get_student_course_roster_progress_response_200.additional_properties = d
        return get_student_course_roster_progress_response_200

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
