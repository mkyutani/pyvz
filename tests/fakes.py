"""Stand-ins shared by the tests."""


class FakeTerminal:
    """Gives the loop bytes as if typed. Each item arrives in one read.

    None stands for a pause longer than the ESC delay.
    """

    def __init__(self, *chunks: bytes | None) -> None:
        self.chunks = list(chunks)
        self.output: list[str] = []

    def size(self) -> tuple[int, int]:
        return 40, 10

    def take_resized(self) -> bool:
        return False

    def read(self, timeout: float | None) -> bytes | None:
        if not self.chunks:
            if timeout is not None:
                return None
            raise AssertionError("the loop waits for more keys")
        chunk = self.chunks.pop(0)
        if chunk is None and timeout is None:
            return self.read(timeout)
        return chunk

    def write(self, text: str) -> None:
        self.output.append(text)
