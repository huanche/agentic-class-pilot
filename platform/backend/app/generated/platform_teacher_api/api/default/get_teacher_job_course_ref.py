from http import HTTPStatus
from typing import Any, cast

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.get_teacher_job_course_ref_kind import GetTeacherJobCourseRefKind
from ...models.get_teacher_job_course_ref_response_200 import GetTeacherJobCourseRefResponse200
from ...types import UNSET, Unset
from typing import cast



def _get_kwargs(
    job_id: str,
    *,
    kind: GetTeacherJobCourseRefKind | Unset = GetTeacherJobCourseRefKind.ARTIFACT,

) -> dict[str, Any]:




    params: dict[str, Any] = {}

    json_kind: str | Unset = UNSET
    if not isinstance(kind, Unset):
        json_kind = kind.value

    params["kind"] = json_kind


    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}


    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/api/internal/platform/course-space/jobs/{job_id}/course-ref".format(job_id=job_id,),
        "params": params,
    }


    return _kwargs



def _parse_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Any | GetTeacherJobCourseRefResponse200 | None:
    if response.status_code == 200:
        response_200 = GetTeacherJobCourseRefResponse200.from_dict(response.json())



        return response_200

    if response.status_code == 403:
        response_403 = cast(Any, None)
        return response_403

    if response.status_code == 404:
        response_404 = cast(Any, None)
        return response_404

    if response.status_code == 503:
        response_503 = cast(Any, None)
        return response_503

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Response[Any | GetTeacherJobCourseRefResponse200]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    job_id: str,
    *,
    client: AuthenticatedClient,
    kind: GetTeacherJobCourseRefKind | Unset = GetTeacherJobCourseRefKind.ARTIFACT,

) -> Response[Any | GetTeacherJobCourseRefResponse200]:
    """ Resolve a background job to its owning course

     Lets the platform scope job access without reading teacher job tables. kind selects the job family
    (artifact or graph).

    Args:
        job_id (str):
        kind (GetTeacherJobCourseRefKind | Unset):  Default: GetTeacherJobCourseRefKind.ARTIFACT.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | GetTeacherJobCourseRefResponse200]
     """


    kwargs = _get_kwargs(
        job_id=job_id,
kind=kind,

    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)

def sync(
    job_id: str,
    *,
    client: AuthenticatedClient,
    kind: GetTeacherJobCourseRefKind | Unset = GetTeacherJobCourseRefKind.ARTIFACT,

) -> Any | GetTeacherJobCourseRefResponse200 | None:
    """ Resolve a background job to its owning course

     Lets the platform scope job access without reading teacher job tables. kind selects the job family
    (artifact or graph).

    Args:
        job_id (str):
        kind (GetTeacherJobCourseRefKind | Unset):  Default: GetTeacherJobCourseRefKind.ARTIFACT.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | GetTeacherJobCourseRefResponse200
     """


    return sync_detailed(
        job_id=job_id,
client=client,
kind=kind,

    ).parsed

async def asyncio_detailed(
    job_id: str,
    *,
    client: AuthenticatedClient,
    kind: GetTeacherJobCourseRefKind | Unset = GetTeacherJobCourseRefKind.ARTIFACT,

) -> Response[Any | GetTeacherJobCourseRefResponse200]:
    """ Resolve a background job to its owning course

     Lets the platform scope job access without reading teacher job tables. kind selects the job family
    (artifact or graph).

    Args:
        job_id (str):
        kind (GetTeacherJobCourseRefKind | Unset):  Default: GetTeacherJobCourseRefKind.ARTIFACT.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | GetTeacherJobCourseRefResponse200]
     """


    kwargs = _get_kwargs(
        job_id=job_id,
kind=kind,

    )

    response = await client.get_async_httpx_client().request(
        **kwargs
    )

    return _build_response(client=client, response=response)

async def asyncio(
    job_id: str,
    *,
    client: AuthenticatedClient,
    kind: GetTeacherJobCourseRefKind | Unset = GetTeacherJobCourseRefKind.ARTIFACT,

) -> Any | GetTeacherJobCourseRefResponse200 | None:
    """ Resolve a background job to its owning course

     Lets the platform scope job access without reading teacher job tables. kind selects the job family
    (artifact or graph).

    Args:
        job_id (str):
        kind (GetTeacherJobCourseRefKind | Unset):  Default: GetTeacherJobCourseRefKind.ARTIFACT.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | GetTeacherJobCourseRefResponse200
     """


    return (await asyncio_detailed(
        job_id=job_id,
client=client,
kind=kind,

    )).parsed
