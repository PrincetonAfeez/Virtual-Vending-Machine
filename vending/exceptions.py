"""Domain exceptions for the vending machine."""


class VendingError(Exception):
    """Base class for all vending machine errors."""


class InsufficientFundsError(VendingError):
    """Raised when the current balance cannot buy the selected item."""


class OutOfStockError(VendingError):
    """Raised when a selected product has no remaining inventory."""


class InvalidCoinError(VendingError):
    """Raised when an inserted denomination is unsupported or not accepted."""


class InvalidSlotError(VendingError):
    """Raised when a slot code is malformed or absent from the inventory."""


class CannotMakeChangeError(VendingError):
    """Raised when the machine cannot produce the required change."""


class ServiceModeRequiredError(VendingError):
    """Raised when an operator command is attempted outside service mode."""


class AccessDeniedError(VendingError):
    """Raised when a PIN or mode check fails."""

