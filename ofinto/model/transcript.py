from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

class TranscriptSignals(BaseModel):
    """Die fünf Pflichtfelder der Gesprächsauswertung."""

    model_config = ConfigDict(extra="forbid")

    gespraechstyp: Literal[
        "Verkaufsgespräch", "Reklamation", "Information", "Sonstiges",
    ] = Field(description=(
        """Art des Gesprächs nach dessen Hauptzweck. Verkaufsgespräche bleiben auch bei Einwänden Verkaufsgespräche. 
        Nur wenn die Reklamation den Hauptzweck bildet, als Reklamation klassifizieren."""
    ))
    kaufzeitpunkt: Literal[
        "0-3 Monate", "3-6 Monate", "6-12 Monate", ">12 Monate", "unklar",
    ] = Field(description=(
        """Geplanter Kauf-/Bestellzeitpunkt relativ zum Datum im Transkript, nicht zum
        heutigen Datum. Bei expliziter Bestellung diesen Zeitpunkt verwenden, sonst
        den genannten Realisierungszeitraum. Bei fehlender oder nicht eindeutig
        einer Klasse zuordenbarer Zeitangabe: unklar. Ungeklärte Freigaben nicht
        als sicheren Termin interpretieren."""
    ))
    arbeitsplaetze: int | None = Field(ge=0, strict=True, description=(
        """Anzahl im aktuellen Vorhaben neu auszustattender Arbeitsplätze, auch beim 
        Ersatz alter Arbeitsplätze. Keine Mitarbeiterzahl, historischen Käufe, 
        Kabinen, Akustikprodukte oder einzelnen Ersatzstühle zählen. Letzte 
        konkretisierte Menge verwenden; optionale spätere Etappen nicht addieren. 
        Bei Bandbreiten oder unbestimmter Menge None statt erfundenem Punktwert. 
        Bei ausdrücklich ausgeschlossenen neuen Arbeitsplätzen 0; bei reinem 
        Akustik-/Kabinenprojekt ohne bestimmbare Arbeitsplatzanzahl None."""
    ))
    wettbewerber: list[str] = Field(description=(
        """Anbieter, mit denen ofinto beim aktuellen Vorhaben konkret im Wettbewerb 
        steht. Historische Lieferanten, beiläufige Marken und ofinto ausschließen. 
        Ohne konkrete Wettbewerber leere Liste."""
    ))
    einwaende: list[str] = Field(description=(
        """Nur ausdrücklich genannte kundenseitige Bedenken oder Kaufbedingungen.
        Keine blossen Rückfragen, Wünsche, Terminangaben oder verneinten Bedenken.
        Frühere Probleme nur bei aktueller Kaufrelevanz. Pro Thema ein allgemeines
        deutsches Stichwort, z.B. Design/Optik statt Eichenfarbe, Bemusterung statt
        Teststuhl. Weitere Stichworte sind erlaubt. Gleichartige Einwände zusammenfassen,
        keine ganzen Sätze. Ohne belegte Einwände: leere Liste."""
    ))
