class BotException(Exception):
    """Base exception class for the bot."""
    pass

class PlayerNotFoundException(BotException):
    """Raised when a player cannot be found."""
    pass

class StatsNotFoundException(BotException):
    """Raised when stats for a player cannot be found."""
    pass

class ApiError(BotException):
    """Raised when there is an error with the API request."""
    def __init__(self, message="An error occurred while fetching data from the API."):
        self.message = message
        super().__init__(self.message)
