from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
  from ..models.report_student_learning_progress_response_200_progress import ReportStudentLearningProgressResponse200Progress





T = TypeVar("T", bound="ReportStudentLearningProgressResponse200")



@_attrs_define
class ReportStudentLearningProgressResponse200:
    """
        Attributes:
            ok (bool):
            progress (ReportStudentLearningProgressResponse200Progress):
            pushed_to_teacher (bool):
     """

    ok: bool
    progress: ReportStudentLearningProgressResponse200Progress
    pushed_to_teacher: bool
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.report_student_learning_progress_response_200_progress import ReportStudentLearningProgressResponse200Progress
        ok = self.ok

        progress = self.progress.to_dict()

        pushed_to_teacher = self.pushed_to_teacher


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "ok": ok,
            "progress": progress,
            "pushedToTeacher": pushed_to_teacher,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.report_student_learning_progress_response_200_progress import ReportStudentLearningProgressResponse200Progress
        d = dict(src_dict)
        ok = d.pop("ok")

        progress = ReportStudentLearningProgressResponse200Progress.from_dict(d.pop("progress"))




        pushed_to_teacher = d.pop("pushedToTeacher")

        report_student_learning_progress_response_200 = cls(
            ok=ok,
            progress=progress,
            pushed_to_teacher=pushed_to_teacher,
        )


        report_student_learning_progress_response_200.additional_properties = d
        return report_student_learning_progress_response_200

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
