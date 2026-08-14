"""Tests de las reglas de mapeo planilla legacy -> Asset (import_mapping.py).
Funciones puras, sin BD: cubren los casos reales encontrados en la
planilla de origen (tipos libres, fechas con distintos formatos,
oficinas numéricas vs con nombre, S/N marcado como 'sin dato')."""
from inventory.import_mapping import (
    map_category,
    map_location,
    map_status,
    parse_legacy_date,
    row_to_asset_fields,
)
from inventory.models import AssetCategory, AssetStatus


class TestMapCategory:
    def test_known_type_maps_to_fixed_category(self):
        assert map_category("Laptop") == AssetCategory.LAPTOP

    def test_matching_is_case_insensitive_and_trims_whitespace(self):
        assert map_category("  MONITOR  ") == AssetCategory.MONITOR

    def test_unknown_type_falls_back_to_otro(self):
        assert map_category("algo-nunca-visto") == AssetCategory.OTRO

    def test_empty_falls_back_to_otro(self):
        assert map_category("") == AssetCategory.OTRO


class TestMapStatus:
    def test_asignado_maps_to_activo(self):
        assert map_status("Asignado") == AssetStatus.ACTIVO

    def test_en_bodega_maps_to_bodega(self):
        assert map_status("En Bodega") == AssetStatus.BODEGA

    def test_unknown_status_falls_back_to_bodega(self):
        assert map_status("de baja") == AssetStatus.BODEGA


class TestMapLocation:
    def test_numeric_office_gets_prefixed(self):
        assert map_location("204") == "Oficina 204"

    def test_named_location_passes_through(self):
        assert map_location("U Concepcion") == "U Concepcion"

    def test_empty_returns_empty_string(self):
        assert map_location("") == ""
        assert map_location(None) == ""


class TestParseLegacyDate:
    def test_parses_dd_mm_yyyy(self):
        assert str(parse_legacy_date("15/03/2022")) == "2022-03-15"

    def test_parses_dd_dash_mm_dash_yyyy(self):
        assert str(parse_legacy_date("15-03-2022")) == "2022-03-15"

    def test_parses_iso_format(self):
        assert str(parse_legacy_date("2022-03-15")) == "2022-03-15"

    def test_empty_returns_none(self):
        assert parse_legacy_date("") is None
        assert parse_legacy_date(None) is None

    def test_malformed_date_returns_none_instead_of_raising(self):
        assert parse_legacy_date("no-es-una-fecha") is None


class TestRowToAssetFields:
    def test_maps_full_row(self):
        row = {
            "Decripción": "Notebook Dell",
            "Tipo": "Laptop",
            "Status": "Asignado",
            "Serial Number": "SN123",
            "Marca": "Dell",
            "Modelo": "Latitude",
            "Oficina": "204",
            "Fecha de Compra": "15/03/2022",
            "Empresa": "Proveedor SA",
            "Factura": "F-001",
            "Serie GLPI": "INV-42",
            "Comentario": "Sin uso",
            "Garantia": "2 años",
            "Valor?": "500000",
        }

        fields = row_to_asset_fields(row)

        assert fields["name"] == "Notebook Dell"
        assert fields["category"] == AssetCategory.LAPTOP
        assert fields["status"] == AssetStatus.ACTIVO
        assert fields["serial_number"] == "SN123"
        assert fields["location"] == "Oficina 204"
        assert fields["legacy_id"] == "INV-42"
        assert "Sin uso" in fields["notes"]
        assert "Garantía: 2 años" in fields["notes"]
        assert "Valor: 500000" in fields["notes"]

    def test_sn_placeholder_is_normalized_to_empty(self):
        row = {"Decripción": "x", "Serial Number": "S/N"}
        assert row_to_asset_fields(row)["serial_number"] == ""

    def test_missing_description_falls_back_to_default_name(self):
        row = {}
        assert row_to_asset_fields(row)["name"] == "Activo sin descripción"

    def test_accepts_either_description_column_spelling(self):
        """La planilla real tiene la columna mal tipeada ('Decripción')
        en algunas versiones y bien tipeada en otras."""
        assert row_to_asset_fields({"Descripción": "Con tilde bien"})["name"] == "Con tilde bien"
        assert row_to_asset_fields({"Decripción": "Con tilde mal"})["name"] == "Con tilde mal"
