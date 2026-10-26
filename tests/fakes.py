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


class FakeConsole:
    """Answers questions, input boxes and menus from a queue, in the order asked."""

    def __init__(self, *answers: object) -> None:
        self.answers = list(answers)
        self.questions: list[str] = []
        self.messages: list[str] = []
        self.boxes: list[tuple[str, str]] = []  # (title, text shown first)
        self.menus: list[list[tuple[str, str]]] = []

    def message(self, text: str) -> None:
        self.messages.append(text)

    def ask(self, question: str) -> bool | None:
        self.questions.append(question)
        return self.answers.pop(0)

    def gets(self, title: str, text: str = "", *, kind: str = "") -> str | None:
        self.boxes.append((title, text))
        return self.answers.pop(0)

    def menu(self, items, *, title: str = ""):
        self.menus.append(list(items))
        return self.answers.pop(0)
