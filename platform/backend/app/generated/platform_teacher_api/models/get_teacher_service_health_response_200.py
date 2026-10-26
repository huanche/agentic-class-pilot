from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
  from ..models.get_teacher_service_health_response_200_capabilities import GetTeacherServiceHealthResponse200Capabilities





T = TypeVar("T", bound="GetTeacherServiceHealthResponse200")



@_attrs_define
class GetTeacherServiceHealthResponse200:
    """
        Attributes:
            capabilities (GetTeacherServiceHealthResponse200Capabilities):
            status (str):
            success (bool):
            version (str):
     """

    capabilities: GetTeacherServiceHealthResponse200Capabilities
    status: str
    success: bool
    version: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.get_teacher_service_health_response_200_capabilities import GetTeacherServiceHealthResponse200Capabilities
        capabilities = self.capabilities.to_dict()

        status = self.status

        success = self.success

        version = self.version


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "capabilities": capabilities,
            "status": status,
            "success": success,
            "version": version,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.get_teacher_service_health_response_200_capabilities import GetTeacherServiceHealthResponse200Capabilities
        d = dict(src_dict)
        capabilities = GetTeacherServiceHealthResponse200Capabilities.from_dict(d.pop("capabilities"))




        status = d.pop("status")

        success = d.pop("success")

        version = d.pop("version")

        get_teacher_service_health_response_200 = cls(
            capabilities=capabilities,
            status=status,
            success=success,
            version=version,
        )


        get_teacher_service_health_response_200.additional_properties = d
        return get_teacher_service_health_response_200

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
