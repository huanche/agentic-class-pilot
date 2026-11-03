from http import HTTPStatus
from typing import Any, cast

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.get_teacher_published_lesson_response_200 import GetTeacherPublishedLessonResponse200
from typing import cast



def _get_kwargs(
    artifact_id: str,

) -> dict[str, Any]:






    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/api/internal/platform/artifacts/{artifact_id}/published-lesson".format(artifact_id=artifact_id,),
    }


    return _kwargs



def _parse_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Any | GetTeacherPublishedLessonResponse200 | None:
    if response.status_code == 200:
        response_200 = GetTeacherPublishedLessonResponse200.from_dict(response.json())



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


def _build_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Response[Any | GetTeacherPublishedLessonResponse200]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    artifact_id: str,
    *,
    client: AuthenticatedClient,

) -> Response[Any | GetTeacherPublishedLessonResponse200]:
    """ The teacher-verified published lesson video and its classroom projection

     Serves the platform's published-lesson-knowledge registration without teacher-schema reads. reason
    mirrors the legacy failure messages: not-published and not-a-lesson-video surface as 409, classroom-
    missing as 404 on the platform side.

    Args:
        artifact_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | GetTeacherPublishedLessonResponse200]
     """


    kwargs = _get_kwargs(
        artifact_id=artifact_id,

    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)

def sync(
    artifact_id: str,
    *,
    client: AuthenticatedClient,

) -> Any | GetTeacherPublishedLessonResponse200 | None:
    """ The teacher-verified published lesson video and its classroom projection

     Serves the platform's published-lesson-knowledge registration without teacher-schema reads. reason
    mirrors the legacy failure messages: not-published and not-a-lesson-video surface as 409, classroom-
    missing as 404 on the platform side.

    Args:
        artifact_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | GetTeacherPublishedLessonResponse200
     """


    return sync_detailed(
        artifact_id=artifact_id,
client=client,

    ).parsed

async def asyncio_detailed(
    artifact_id: str,
    *,
    client: AuthenticatedClient,

) -> Response[Any | GetTeacherPublishedLessonResponse200]:
    """ The teacher-verified published lesson video and its classroom projection

     Serves the platform's published-lesson-knowledge registration without teacher-schema reads. reason
    mirrors the legacy failure messages: not-published and not-a-lesson-video surface as 409, classroom-
    missing as 404 on the platform side.

    Args:
        artifact_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | GetTeacherPublishedLessonResponse200]
     """


    kwargs = _get_kwargs(
        artifact_id=artifact_id,

    )

    response = await client.get_async_httpx_client().request(
        **kwargs
    )

    return _build_response(client=client, response=response)

async def asyncio(
    artifact_id: str,
    *,
    client: AuthenticatedClient,

) -> Any | GetTeacherPublishedLessonResponse200 | None:
    """ The teacher-verified published lesson video and its classroom projection

     Serves the platform's published-lesson-knowledge registration without teacher-schema reads. reason
    mirrors the legacy failure messages: not-published and not-a-lesson-video surface as 409, classroom-
    missing as 404 on the platform side.

    Args:
        artifact_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | GetTeacherPublishedLessonResponse200
     """


    return (await asyncio_detailed(
        artifact_id=artifact_id,
client=client,

    )).parsed
