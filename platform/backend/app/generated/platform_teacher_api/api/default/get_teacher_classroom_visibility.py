from http import HTTPStatus
from typing import Any, cast

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.get_teacher_classroom_visibility_response_200 import GetTeacherClassroomVisibilityResponse200
from typing import cast



def _get_kwargs(
    classroom_id: str,

) -> dict[str, Any]:






    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/api/internal/platform/classrooms/{classroom_id}/visibility".format(classroom_id=classroom_id,),
    }


    return _kwargs



def _parse_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Any | GetTeacherClassroomVisibilityResponse200 | None:
    if response.status_code == 200:
        response_200 = GetTeacherClassroomVisibilityResponse200.from_dict(response.json())



        return response_200

    if response.status_code == 403:
        response_403 = cast(Any, None)
        return response_403

    if response.status_code == 503:
        response_503 = cast(Any, None)
        return response_503

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Response[Any | GetTeacherClassroomVisibilityResponse200]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    classroom_id: str,
    *,
    client: AuthenticatedClient,

) -> Response[Any | GetTeacherClassroomVisibilityResponse200]:
    """ Whether a classroom is the current published classroom of an active course

     Teacher-owned half of the student player authorization. courseId is the teacher service's own course
    reference; the platform resolves it to the enrollment record. Classroom→course linkage requires the
    teacher course database, like the legacy authorize queries.

    Args:
        classroom_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | GetTeacherClassroomVisibilityResponse200]
     """


    kwargs = _get_kwargs(
        classroom_id=classroom_id,

    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)

def sync(
    classroom_id: str,
    *,
    client: AuthenticatedClient,

) -> Any | GetTeacherClassroomVisibilityResponse200 | None:
    """ Whether a classroom is the current published classroom of an active course

     Teacher-owned half of the student player authorization. courseId is the teacher service's own course
    reference; the platform resolves it to the enrollment record. Classroom→course linkage requires the
    teacher course database, like the legacy authorize queries.

    Args:
        classroom_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | GetTeacherClassroomVisibilityResponse200
     """


    return sync_detailed(
        classroom_id=classroom_id,
client=client,

    ).parsed

async def asyncio_detailed(
    classroom_id: str,
    *,
    client: AuthenticatedClient,

) -> Response[Any | GetTeacherClassroomVisibilityResponse200]:
    """ Whether a classroom is the current published classroom of an active course

     Teacher-owned half of the student player authorization. courseId is the teacher service's own course
    reference; the platform resolves it to the enrollment record. Classroom→course linkage requires the
    teacher course database, like the legacy authorize queries.

    Args:
        classroom_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | GetTeacherClassroomVisibilityResponse200]
     """


    kwargs = _get_kwargs(
        classroom_id=classroom_id,

    )

    response = await client.get_async_httpx_client().request(
        **kwargs
    )

    return _build_response(client=client, response=response)

async def asyncio(
    classroom_id: str,
    *,
    client: AuthenticatedClient,

) -> Any | GetTeacherClassroomVisibilityResponse200 | None:
    """ Whether a classroom is the current published classroom of an active course

     Teacher-owned half of the student player authorization. courseId is the teacher service's own course
    reference; the platform resolves it to the enrollment record. Classroom→course linkage requires the
    teacher course database, like the legacy authorize queries.

    Args:
        classroom_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | GetTeacherClassroomVisibilityResponse200
     """


    return (await asyncio_detailed(
        classroom_id=classroom_id,
client=client,

    )).parsed
