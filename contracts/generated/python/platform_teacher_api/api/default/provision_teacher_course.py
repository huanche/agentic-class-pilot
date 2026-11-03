from http import HTTPStatus
from typing import Any, cast

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.provision_teacher_course_body import ProvisionTeacherCourseBody
from ...models.provision_teacher_course_response_200 import ProvisionTeacherCourseResponse200
from ...models.provision_teacher_course_response_201 import ProvisionTeacherCourseResponse201
from typing import cast



def _get_kwargs(
    *,
    body: ProvisionTeacherCourseBody,

) -> dict[str, Any]:
    headers: dict[str, Any] = {}






    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/api/course-space",
    }

    _kwargs["json"] = body.to_dict()


    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs



def _parse_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Any | ProvisionTeacherCourseResponse200 | ProvisionTeacherCourseResponse201 | None:
    if response.status_code == 200:
        response_200 = ProvisionTeacherCourseResponse200.from_dict(response.json())



        return response_200

    if response.status_code == 201:
        response_201 = ProvisionTeacherCourseResponse201.from_dict(response.json())



        return response_201

    if response.status_code == 400:
        response_400 = cast(Any, None)
        return response_400

    if response.status_code == 401:
        response_401 = cast(Any, None)
        return response_401

    if response.status_code == 403:
        response_403 = cast(Any, None)
        return response_403

    if response.status_code == 409:
        response_409 = cast(Any, None)
        return response_409

    if response.status_code == 502:
        response_502 = cast(Any, None)
        return response_502

    if response.status_code == 503:
        response_503 = cast(Any, None)
        return response_503

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Response[Any | ProvisionTeacherCourseResponse200 | ProvisionTeacherCourseResponse201]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: ProvisionTeacherCourseBody,

) -> Response[Any | ProvisionTeacherCourseResponse200 | ProvisionTeacherCourseResponse201]:
    """  Platform provisioning profile. The stable course id is required here to preserve idempotency; the
    general teacher UI supports additional fields.

    Args:
        body (ProvisionTeacherCourseBody):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | ProvisionTeacherCourseResponse200 | ProvisionTeacherCourseResponse201]
     """


    kwargs = _get_kwargs(
        body=body,

    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)

def sync(
    *,
    client: AuthenticatedClient,
    body: ProvisionTeacherCourseBody,

) -> Any | ProvisionTeacherCourseResponse200 | ProvisionTeacherCourseResponse201 | None:
    """  Platform provisioning profile. The stable course id is required here to preserve idempotency; the
    general teacher UI supports additional fields.

    Args:
        body (ProvisionTeacherCourseBody):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | ProvisionTeacherCourseResponse200 | ProvisionTeacherCourseResponse201
     """


    return sync_detailed(
        client=client,
body=body,

    ).parsed

async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: ProvisionTeacherCourseBody,

) -> Response[Any | ProvisionTeacherCourseResponse200 | ProvisionTeacherCourseResponse201]:
    """  Platform provisioning profile. The stable course id is required here to preserve idempotency; the
    general teacher UI supports additional fields.

    Args:
        body (ProvisionTeacherCourseBody):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | ProvisionTeacherCourseResponse200 | ProvisionTeacherCourseResponse201]
     """


    kwargs = _get_kwargs(
        body=body,

    )

    response = await client.get_async_httpx_client().request(
        **kwargs
    )

    return _build_response(client=client, response=response)

async def asyncio(
    *,
    client: AuthenticatedClient,
    body: ProvisionTeacherCourseBody,

) -> Any | ProvisionTeacherCourseResponse200 | ProvisionTeacherCourseResponse201 | None:
    """  Platform provisioning profile. The stable course id is required here to preserve idempotency; the
    general teacher UI supports additional fields.

    Args:
        body (ProvisionTeacherCourseBody):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | ProvisionTeacherCourseResponse200 | ProvisionTeacherCourseResponse201
     """


    return (await asyncio_detailed(
        client=client,
body=body,

    )).parsed
