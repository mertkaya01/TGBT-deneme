"""Router'ları doğru sırayla toplar (komutlar önce, yakalayıcı en son)."""

from aiogram import Router

from app.handlers import (
    account_panel,
    admin,
    auto_message,
    dm,
    exceptions,
    fallback,
    inline_reply,
    login_handler,
    other_features,
    reply_filters,
    start,
)


def build_root_router() -> Router:
    root = Router(name="root")
    root.include_routers(
        start.router,
        admin.router,
        login_handler.router,
        account_panel.router,
        auto_message.router,
        other_features.router,
        dm.router,
        reply_filters.router,
        exceptions.router,
        inline_reply.router,
        fallback.router,
    )
    return root
