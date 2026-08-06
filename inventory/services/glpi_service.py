"""Servicio de consulta en tiempo real a la base de datos MariaDB de GLPI.
Permite visualizar activos, filtrar, generar códigos QR de redirección directa a GLPI y KPIs."""
from __future__ import annotations

import base64
import io
from typing import Any, Dict, List, Optional
import qrcode
from django.conf import settings
from django.db import connections


TABLE_MAPPING = [
    ("glpi_computers", "PC", "computer.form.php"),
    ("glpi_monitors", "MONITOR", "monitor.form.php"),
    ("glpi_printers", "IMPRESORA", "printer.form.php"),
    ("glpi_networkequipments", "RED", "networkequipment.form.php"),
    ("glpi_peripherals", "PERIFERICO", "peripheral.form.php"),
    ("glpi_phones", "TELEFONO", "phone.form.php"),
]


def _generate_qr_data_url(url: str) -> str:
    """Genera una imagen PNG del código QR codificado en Base64 Data URL (50x50px)."""
    qr = qrcode.QRCode(version=1, box_size=2, border=1)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img = img.resize((  50, 50))  # Ajustar tamaño a 90x90 píxeles
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    b64_str = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{b64_str}"


class GLPIInventoryService:
    """Consulta la base de datos MariaDB (alias 'glpi' en settings.DATABASES)
    en modo solo lectura para la gestión y visualización del inventario."""

    def __init__(self, db_alias: str = "glpi"):
        self.db_alias = db_alias

    def _dictfetchall(self, cursor) -> List[Dict[str, Any]]:
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def list_assets(
        self,
        search: Optional[str] = None,
        category: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        """Lista todos los activos desde MariaDB combinando las tablas de GLPI."""
        results: List[Dict[str, Any]] = []
        connection = connections[self.db_alias]
        glpi_base_url = getattr(settings, "GLPI_BASE_URL", "https://glpi.cmm.uchile.cl").rstrip("/")

        with connection.cursor() as cursor:
            for table_name, cat_code, form_page in TABLE_MAPPING:
                if category and category.upper() != cat_code and category.upper() != "ALL":
                    if category.upper() == "PC" and cat_code not in ("PC", "LAPTOP"):
                        continue
                    elif category.upper() != cat_code:
                        continue

                sql = f"""
                    SELECT 
                        t.id,
                        t.name,
                        t.serial,
                        t.otherserial AS legacy_id,
                        t.comment,
                        t.contact,
                        m.name AS brand,
                        st.name AS status,
                        l.completename AS location,
                        '{cat_code}' AS category,
                        t.date_mod
                    FROM {table_name} t
                    LEFT JOIN glpi_manufacturers m ON t.manufacturers_id = m.id
                    LEFT JOIN glpi_states st ON t.states_id = st.id
                    LEFT JOIN glpi_locations l ON t.locations_id = l.id
                    WHERE t.is_deleted = 0
                """
                params: list = []

                if status:
                    sql += " AND LOWER(st.name) LIKE %s"
                    params.append(f"%{status.lower()}%")

                if search:
                    sql += """ AND (
                        LOWER(t.name) LIKE %s OR 
                        LOWER(t.serial) LIKE %s OR 
                        LOWER(t.otherserial) LIKE %s OR 
                        LOWER(t.contact) LIKE %s OR 
                        LOWER(l.completename) LIKE %s OR 
                        LOWER(m.name) LIKE %s
                    )"""
                    search_pattern = f"%{search.lower()}%"
                    params.extend([search_pattern] * 6)

                sql += f" ORDER BY t.id DESC LIMIT {limit}"

                cursor.execute(sql, params)
                rows = self._dictfetchall(cursor)
                for r in rows:
                    r["id_str"] = f"{cat_code.lower()}_{r['id']}"
                    r["code"] = f"GLPI-{cat_code}-{r['id']}"
                    r["glpi_url"] = f"{glpi_base_url}/front/{form_page}?id={r['id']}"
                    r["qr_code_data"] = _generate_qr_data_url(r["glpi_url"])

                results.extend(rows)

        # Ordenar por fecha de modificación / id
        results.sort(key=lambda x: str(x.get("date_mod") or ""), reverse=True)
        return results[:limit]

    def get_dashboard_summary(self) -> Dict[str, Any]:
        """Calcula los KPIs agregados del inventario consultando MariaDB."""
        connection = connections[self.db_alias]
        by_category: Dict[str, int] = {}
        by_status: Dict[str, int] = {}
        top_locations: Dict[str, int] = {}
        total = 0

        with connection.cursor() as cursor:
            for table_name, cat_code, _ in TABLE_MAPPING:
                # Total por categoría
                cursor.execute(f"SELECT COUNT(*) FROM {table_name} WHERE is_deleted = 0")
                count = cursor.fetchone()[0]
                by_category[cat_code] = count
                total += count

                # Estados
                cursor.execute(
                    f"""
                    SELECT COALESCE(st.name, 'Sin Estado') AS status_name, COUNT(*) 
                    FROM {table_name} t
                    LEFT JOIN glpi_states st ON t.states_id = st.id
                    WHERE t.is_deleted = 0
                    GROUP BY st.name
                """
                )
                for st_name, st_count in cursor.fetchall():
                    by_status[st_name] = by_status.get(st_name, 0) + st_count

                # Ubicaciones top
                cursor.execute(
                    f"""
                    SELECT COALESCE(l.completename, 'Sin Ubicación') AS loc_name, COUNT(*) 
                    FROM {table_name} t
                    LEFT JOIN glpi_locations l ON t.locations_id = l.id
                    WHERE t.is_deleted = 0 AND l.completename IS NOT NULL AND l.completename != ''
                    GROUP BY l.completename
                """
                )
                for loc_name, loc_count in cursor.fetchall():
                    top_locations[loc_name] = top_locations.get(loc_name, 0) + loc_count

        sorted_locations = dict(sorted(top_locations.items(), key=lambda item: item[1], reverse=True)[:10])

        return {
            "total": total,
            "by_category": by_category,
            "by_status": by_status,
            "top_locations": sorted_locations,
        }
