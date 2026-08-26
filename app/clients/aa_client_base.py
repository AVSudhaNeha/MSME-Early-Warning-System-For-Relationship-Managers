from abc import ABC, abstractmethod


class AAConnectionError(Exception):
    """
    Raised when the Account Aggregator call fails or times out.
    The scoring engine can catch this error and use fallback data.
    """
    pass


class AAClient(ABC):

    @abstractmethod
    def fetch_aa_data(self, borrower_id: str, cycle: int) -> dict:
        """
        Fetch Account Aggregator data for a borrower.

        Both MockAAClient and LiveAAClient must return data
        using the same structure.
        """
        raise NotImplementedError