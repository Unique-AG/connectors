class CaseNotFoundError(Exception):
    def __init__(self, *, case: str) -> None:
        super().__init__(f"No case matches {case}.")
        self.case: str = case
