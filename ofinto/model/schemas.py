CLIENTS_TABLE = "firmenkunden"
ENRICHMENT_TABLE = "firmendaten_anreicherung"
ORDERS_TABLE = "bestellungen"
ORDER_ITEMS_TABLE = "bestellpositionen"
COMPANY_PROFILES_TABLE = "company_profiles"


SCHEMAS = {
    CLIENTS_TABLE: {
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
    ENRICHMENT_TABLE: {
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
    ORDERS_TABLE: {
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
    ORDER_ITEMS_TABLE: {
        "order_id": "VARCHAR",
        "produkt": "VARCHAR",
        "kategorie": "VARCHAR",
        "menge": "BIGINT",
        "stueckpreis_netto": "DECIMAL(18,2)",
        "waehrung": "VARCHAR",
    },
}
