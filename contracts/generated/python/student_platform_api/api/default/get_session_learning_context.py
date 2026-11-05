from http import HTTPStatus
from typing import Any, cast

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.get_session_learning_context_body import GetSessionLearningContextBody
from ...models.platform_learning_context_v1 import PlatformLearningContextV1
from typing import cast



def _get_kwargs(
    *,
    body: GetSessionLearningContextBody,

) -> dict[str, Any]:
    headers: dict[str, Any] = {}






    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/internal/student/learning-context-v2",
    }

    _kwargs["json"] = body.to_dict()


    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs



def _parse_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Any | PlatformLearningContextV1 | None:
    if response.status_code == 200:
        response_200 = PlatformLearningContextV1.from_dict(response.json())



        return response_200

    if response.status_code == 403:
        response_403 = cast(Any, None)
        return response_403

    if response.status_code == 404:
        response_404 = cast(Any, None)
        return response_404

    if response.status_code == 409:
        response_409 = cast(Any, None)
        return response_409

    if response.status_code == 503:
        response_503 = cast(Any, None)
        return response_503

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Response[Any | PlatformLearningContextV1]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: GetSessionLearningContextBody,

) -> Response[Any | PlatformLearningContextV1]:
    """ Cookie BFF 已校验身份后的服务端学习上下文

    Args:
        body (GetSessionLearningContextBody):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | PlatformLearningContextV1]
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
    body: GetSessionLearningContextBody,

) -> Any | PlatformLearningContextV1 | None:
    """ Cookie BFF 已校验身份后的服务端学习上下文

    Args:
        body (GetSessionLearningContextBody):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | PlatformLearningContextV1
     """


    return sync_detailed(
        client=client,
body=body,

    ).parsed

async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: GetSessionLearningContextBody,

) -> Response[Any | PlatformLearningContextV1]:
    """ Cookie BFF 已校验身份后的服务端学习上下文

    Args:
        body (GetSessionLearningContextBody):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | PlatformLearningContextV1]
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
    body: GetSessionLearningContextBody,

) -> Any | PlatformLearningContextV1 | None:
    """ Cookie BFF 已校验身份后的服务端学习上下文

    Args:
        body (GetSessionLearningContextBody):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | PlatformLearningContextV1
     """


    return (await asyncio_detailed(
        client=client,
body=body,

    )).parsed
