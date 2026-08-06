"""Standalone FastAPI assembly and process entry point."""

from __future__ import annotations

import argparse
import logging

import uvicorn
from fastapi import FastAPI

from omnigent_feishu.adapter import FeishuAdapter
from omnigent_feishu.auth import StaticBearerProvider
from omnigent_feishu.config import FeishuConfig
from omnigent_feishu.core_client import CoreClient
from omnigent_feishu.credentials import FeishuCredentialCipher
from omnigent_feishu.device_flow import FeishuPersonalAgentDeviceFlow
from omnigent_feishu.realtime import FeishuRealtimeRuntime
from omnigent_feishu.router import FeishuRouter
from omnigent_feishu.routes import create_feishu_router
from omnigent_feishu.store import FeishuStore
from omnigent_feishu.surface import BotSurfaceProvisioner


def create_app(
    config: FeishuConfig,
    *,
    store: FeishuStore | None = None,
    device_flow: FeishuPersonalAgentDeviceFlow | None = None,
    core_client: CoreClient | None = None,
    surface_provisioner: BotSurfaceProvisioner | None = None,
) -> FastAPI:
    provider_store = store or FeishuStore(config.database_path)
    core = core_client or CoreClient(
        config.server_url, StaticBearerProvider(config.core_bearer or "unconfigured")
    )
    router = FeishuRouter(provider_store, core, action_secret=config.action_secret)
    adapter = FeishuAdapter(
        router,
        provider_store,
        verification_token=config.verification_token,
        signature_secret=config.encrypt_key,
    )
    cipher = FeishuCredentialCipher(config.credential_key)
    realtime = FeishuRealtimeRuntime(
        provider_store, cipher, adapter, core, action_secret=config.action_secret
    )
    app = FastAPI(title="Omnigent Feishu", version="1")
    app.include_router(
        create_feishu_router(
            provider_store,
            device_flow or FeishuPersonalAgentDeviceFlow(),
            cipher,
            adapter,
            surface_provisioner=surface_provisioner,
            installation_connected=realtime.start_installation,
        )
    )

    @app.on_event("startup")
    async def startup() -> None:
        await provider_store.initialize()
        for key, value in config.runtime_settings().items():
            await provider_store.set_meta(f"feishu.runtime.{key}", value)
        config.database_path.parent.chmod(0o700)
        config.database_path.chmod(0o600)
        await realtime.start()

    @app.on_event("shutdown")
    async def shutdown() -> None:
        await core.close()

    return app


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the standalone Omnigent Feishu service")
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    args = parser.parse_args(argv)
    config = FeishuConfig()
    logging.basicConfig(level=getattr(logging, config.log_level.upper(), logging.INFO))
    uvicorn.run(
        create_app(config),
        host=args.host or config.host,
        port=args.port or config.port,
        log_level=config.log_level.lower(),
    )


__all__ = ["create_app", "main"]
