from http import HTTPStatus
from typing import Any, cast

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.get_teacher_publication_counts_response_200 import GetTeacherPublicationCountsResponse200
from typing import cast



def _get_kwargs(
    course_id: str,

) -> dict[str, Any]:






    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/api/internal/platform/courses/{course_id}/publication-counts".format(course_id=course_id,),
    }


    return _kwargs



def _parse_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Any | GetTeacherPublicationCountsResponse200 | None:
    if response.status_code == 200:
        response_200 = GetTeacherPublicationCountsResponse200.from_dict(response.json())



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


def _build_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Response[Any | GetTeacherPublicationCountsResponse200]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    course_id: str,
    *,
    client: AuthenticatedClient,

) -> Response[Any | GetTeacherPublicationCountsResponse200]:
    """ Teacher-owned published classroom and artifact counts

     Counts published artifacts with a classroom ID, including archived course history, matching the
    platform's existing analytics queries.

    Args:
        course_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | GetTeacherPublicationCountsResponse200]
     """


    kwargs = _get_kwargs(
        course_id=course_id,

    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)

def sync(
    course_id: str,
    *,
    client: AuthenticatedClient,

) -> Any | GetTeacherPublicationCountsResponse200 | None:
    """ Teacher-owned published classroom and artifact counts

     Counts published artifacts with a classroom ID, including archived course history, matching the
    platform's existing analytics queries.

    Args:
        course_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | GetTeacherPublicationCountsResponse200
     """


    return sync_detailed(
        course_id=course_id,
client=client,

    ).parsed

async def asyncio_detailed(
    course_id: str,
    *,
    client: AuthenticatedClient,

) -> Response[Any | GetTeacherPublicationCountsResponse200]:
    """ Teacher-owned published classroom and artifact counts

     Counts published artifacts with a classroom ID, including archived course history, matching the
    platform's existing analytics queries.

    Args:
        course_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | GetTeacherPublicationCountsResponse200]
     """


    kwargs = _get_kwargs(
        course_id=course_id,

    )

    response = await client.get_async_httpx_client().request(
        **kwargs
    )

    return _build_response(client=client, response=response)

async def asyncio(
    course_id: str,
    *,
    client: AuthenticatedClient,

) -> Any | GetTeacherPublicationCountsResponse200 | None:
    """ Teacher-owned published classroom and artifact counts

     Counts published artifacts with a classroom ID, including archived course history, matching the
    platform's existing analytics queries.

    Args:
        course_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | GetTeacherPublicationCountsResponse200
     """


    return (await asyncio_detailed(
        course_id=course_id,
client=client,

    )).parsed
