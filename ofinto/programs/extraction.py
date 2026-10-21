"""Pflichtsignale aus deutschen und französischen Verkaufstranskripten."""

from ..model.transcript import TranscriptSignals
from .base import PromptProgram


class ExtractionProgram(PromptProgram[str, TranscriptSignals]):
    """Ein Transkript analysieren; Labels und Firmenstamm gehören nicht zum Input."""

    return_type = TranscriptSignals
    system_prompt = """Du wertest Gesprächstranskripte für einen Büromöbelanbieter aus.
    Extrahiere die im Ausgabeschema definierten Signale.
    Die Gespräche sind auf Deutsch oder Französisch, die Ausgabekategorien auf Deutsch.
    Nutze nur das vorgelegte Gespräch einschließlich seines Datums. Beachte Korrekturen,
    Verneinungen, Bedingungen und den Unterschied zwischen Kunden- und Verkäuferaussagen.
    Spracherkennungsfehler dürfen bei eindeutigem Kontext normalisiert werden.
    """
    user_prompt = "Transkript:\n\n{input}"

    def prepare(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Das Transkript ist leer")
        return value

    def postprocess(self, result: TranscriptSignals) -> TranscriptSignals:
        """Listen ohne semantische Ergänzungen vereinheitlichen."""
        objections = {}
        for value in result.einwaende:
            keyword = " ".join(value.split())
            if keyword:
                objections.setdefault(keyword.casefold(), keyword)
        return result.model_copy(update={
            "wettbewerber": sorted({name.strip() for name in result.wettbewerber if name.strip()}),
            "einwaende": sorted(objections.values(), key=str.casefold),
        })
