from http import HTTPStatus
from typing import Any, cast

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.get_user_model_config_response_200 import GetUserModelConfigResponse200
from typing import cast
from uuid import UUID



def _get_kwargs(
    user_id: UUID,

) -> dict[str, Any]:






    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/internal/user/{user_id}/model-config".format(user_id=user_id,),
    }


    return _kwargs



def _parse_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Any | GetUserModelConfigResponse200 | None:
    if response.status_code == 200:
        response_200 = GetUserModelConfigResponse200.from_dict(response.json())



        return response_200

    if response.status_code == 403:
        response_403 = cast(Any, None)
        return response_403

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Response[Any | GetUserModelConfigResponse200]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    user_id: UUID,
    *,
    client: AuthenticatedClient,

) -> Response[Any | GetUserModelConfigResponse200]:
    """ 读取用户解密后的模型配置（BYOK，服务端使用，禁止记录响应内容）

     无记录时返回空对象；配置键由用户保存时决定。

    Args:
        user_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | GetUserModelConfigResponse200]
     """


    kwargs = _get_kwargs(
        user_id=user_id,

    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)

def sync(
    user_id: UUID,
    *,
    client: AuthenticatedClient,

) -> Any | GetUserModelConfigResponse200 | None:
    """ 读取用户解密后的模型配置（BYOK，服务端使用，禁止记录响应内容）

     无记录时返回空对象；配置键由用户保存时决定。

    Args:
        user_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | GetUserModelConfigResponse200
     """


    return sync_detailed(
        user_id=user_id,
client=client,

    ).parsed

async def asyncio_detailed(
    user_id: UUID,
    *,
    client: AuthenticatedClient,

) -> Response[Any | GetUserModelConfigResponse200]:
    """ 读取用户解密后的模型配置（BYOK，服务端使用，禁止记录响应内容）

     无记录时返回空对象；配置键由用户保存时决定。

    Args:
        user_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | GetUserModelConfigResponse200]
     """


    kwargs = _get_kwargs(
        user_id=user_id,

    )

    response = await client.get_async_httpx_client().request(
        **kwargs
    )

    return _build_response(client=client, response=response)

async def asyncio(
    user_id: UUID,
    *,
    client: AuthenticatedClient,

) -> Any | GetUserModelConfigResponse200 | None:
    """ 读取用户解密后的模型配置（BYOK，服务端使用，禁止记录响应内容）

     无记录时返回空对象；配置键由用户保存时决定。

    Args:
        user_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | GetUserModelConfigResponse200
     """


    return (await asyncio_detailed(
        user_id=user_id,
client=client,

    )).parsed
