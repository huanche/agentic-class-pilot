from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast






T = TypeVar("T", bound="GetStudentCourseRosterProgressResponse200AssessmentsItem")



@_attrs_define
class GetStudentCourseRosterProgressResponse200AssessmentsItem:
    """
        Attributes:
            evidence (None | str):
            lesson_id (str):
            point_id (str):
            stars (int):
            status (str):
            title (str):
     """

    evidence: None | str
    lesson_id: str
    point_id: str
    stars: int
    status: str
    title: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        evidence: None | str
        evidence = self.evidence

        lesson_id = self.lesson_id

        point_id = self.point_id

        stars = self.stars

        status = self.status

        title = self.title


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "evidence": evidence,
            "lessonId": lesson_id,
            "pointId": point_id,
            "stars": stars,
            "status": status,
            "title": title,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        def _parse_evidence(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        evidence = _parse_evidence(d.pop("evidence"))


        lesson_id = d.pop("lessonId")

        point_id = d.pop("pointId")

        stars = d.pop("stars")

        status = d.pop("status")

        title = d.pop("title")

        get_student_course_roster_progress_response_200_assessments_item = cls(
            evidence=evidence,
            lesson_id=lesson_id,
            point_id=point_id,
            stars=stars,
            status=status,
            title=title,
        )


        get_student_course_roster_progress_response_200_assessments_item.additional_properties = d
        return get_student_course_roster_progress_response_200_assessments_item

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
