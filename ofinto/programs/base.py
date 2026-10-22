from typing import Generic, TypeVar

InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")


class PromptProgram(Generic[InputT, OutputT]):
    """Pro Programm System-/Userprompt, Rückgabetyp und optionale Hooks definieren.

    Programme benötigen keine Konstruktorparameter. Hooks halten keinen Zustand
    zwischen Aufrufen.
    """

    system_prompt: str
    user_prompt: str = "{input}"
    return_type: type[OutputT]

    def prepare(self, value: InputT) -> InputT:
        """Eingabe vor der Darstellung aufbereiten."""
        return value

    def render_user_prompt(self, value: InputT) -> str:
        """Nur das Template formatieren; Klammern der Eingabe bleiben Daten."""
        return self.user_prompt.format(input=value)

    def postprocess(self, result: OutputT) -> OutputT:
        """Die validierte Modellantwort nachbereiten; Änderungen müssen gültig bleiben."""
        return result
