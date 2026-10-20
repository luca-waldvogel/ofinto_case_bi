from enum import StrEnum


class Tables(StrEnum):
    CLIENTS = "firmenkunden"
    ENRICHEMENT = "firmendaten_anreicherung"
    ORDERS = "bestellungen"
    ORDER_ITEMS = "bestellpositionen"


SCHEMAS = {
    Tables.CLIENTS: {
        "account_id": "VARCHAR",
        "firmenname": "VARCHAR",
        "ort": "VARCHAR",
        "plz": "VARCHAR",
        "land_rechnung": "VARCHAR",
        "region": "VARCHAR",
        "sprache": "VARCHAR",
        "branche": "VARCHAR",
        "verantwortlich": "VARCHAR",
        "erstkontakt": "VARCHAR",
        "erste_bestellung": "DATE",
    },
    Tables.ENRICHEMENT: {
        "account_id": "VARCHAR",
        "gefundener_name": "VARCHAR",
        "ort_register": "VARCHAR",
        "uid_register": "VARCHAR",
        "match_score": "DOUBLE",
        "mitarbeitende": "BIGINT",
        "mitarbeitende_bezug": "VARCHAR",
        "standorte": "BIGINT",
        "noga_code": "VARCHAR",
        "gruendungsjahr": "INTEGER",
        "stand": "DATE",
    },
    Tables.ORDERS: {
        "order_id": "VARCHAR",
        "account_id": "VARCHAR",
        "bestelldatum": "DATE",
        "shop": "VARCHAR",
        "waehrung": "VARCHAR",
        "bestellwert_netto": "DECIMAL(18,2)",
        "status": "VARCHAR",
        "retourenwert": "DECIMAL(18,2)",
        "kanal": "VARCHAR",
    },
    Tables.ORDER_ITEMS: {
        "order_id": "VARCHAR",
        "produkt": "VARCHAR",
        "kategorie": "VARCHAR",
        "menge": "BIGINT",
        "stueckpreis_netto": "DECIMAL(18,2)",
        "waehrung": "VARCHAR",
    },
}
