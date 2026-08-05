"""HD Tickets mode package."""

__all__ = ["HDTicketsModeHandler", "get_hd_tickets_handler"]


def __getattr__(name):
    if name in {"HDTicketsModeHandler", "get_hd_tickets_handler"}:
        from .handler import HDTicketsModeHandler, get_hd_tickets_handler

        exports = {
            "HDTicketsModeHandler": HDTicketsModeHandler,
            "get_hd_tickets_handler": get_hd_tickets_handler,
        }
        return exports[name]
    raise AttributeError(name)
