"""API HTTP real, con TestClient.

Aquí se comprueba lo que de verdad expone el motor a internet. El test que
más importa es `test_lectura_sin_firma_se_rechaza`: sin él, conocer un UUID
bastaría para leer el informe de pago de otro usuario.
"""

from __future__ import annotations

import json
from typing import ClassVar
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from powergis.api import security
from powergis.api.main import create_app

SECRET = "secreto-de-pruebas-suficientemente-largo-1234"


@pytest.fixture
def client(uow, monkeypatch):
    """App real con el almacén en memoria enchufado por los puertos."""
    import powergis.api.deps as deps
    import powergis.api.routers.reports as reports_router

    encolados: list[tuple[int, str]] = []
    monkeypatch.setattr(deps, "enqueue_report", lambda rid, q: encolados.append((rid, q)))
    monkeypatch.setattr(reports_router, "uow_factory", lambda: uow)
    monkeypatch.setattr(deps, "uow_factory", lambda: uow)

    from powergis.application.create_report import CreateReport
    from powergis.application.upgrade_report import UpgradeReport

    app = create_app()
    app.dependency_overrides[deps.get_create_report] = lambda: CreateReport(
        lambda: uow, "1.0.0-test", lambda rid, q: encolados.append((rid, q))
    )
    app.dependency_overrides[deps.get_upgrade_report] = lambda: UpgradeReport(
        lambda: uow, "1.0.0-test", lambda rid, q: encolados.append((rid, q))
    )

    with TestClient(app, raise_server_exceptions=False) as test_client:
        test_client.encolados = encolados  # type: ignore[attr-defined]
        yield test_client


def signed_post(client: TestClient, path: str, payload: dict, **kwargs):
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    headers = {"Content-Type": "application/json", **security.sign(body, SECRET).as_dict()}
    headers.update(kwargs.pop("headers", {}))
    return client.post(path, content=body, headers=headers, **kwargs)


def signed_get(client: TestClient, path: str, query: str = ""):
    headers = security.sign_get(path, query, SECRET).as_dict()
    url = f"{path}?{query}" if query else path
    return client.get(url, headers=headers)


@pytest.fixture
def created(client, project):
    payload = {
        "project_uuid": str(project.project_uuid),
        "wp_user_id": 7,
        "wp_post_id": 7818,
        "tier": "basico",
        "scope": {"level": "ccaa", "ine_code": "13", "children_level": "provincia"},
        "segments": {"age": ["18-35"], "sex": ["F", "M"]},
        "business": {"sector": "restauracion", "avg_ticket": 18.5},
    }
    response = signed_post(client, "/v1/reports", payload)
    assert response.status_code == 202, response.text
    return project.project_uuid


# --------------------------------------------------------------------------- #


class TestSalud:
    def test_health_responde_siempre(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_ready_comprueba_dependencias(self, client):
        # Sin Postgres ni Redis reales, readiness DEBE decir que no está listo.
        response = client.get("/ready")
        assert response.status_code == 503
        assert response.json()["status"] == "degraded"


class TestFirmaEnEscritura:
    def test_crear_sin_firma_se_rechaza(self, client, project):
        response = client.post("/v1/reports", json={"project_uuid": str(project.project_uuid)})
        assert response.status_code == 401
        assert response.json()["code"] == "invalid_signature"

    def test_crear_con_firma_valida(self, client, created):
        assert client.encolados[0][1] == "reports.basic"

    def test_cuerpo_alterado_tras_firmar_se_rechaza(self, client, project):
        payload = {
            "project_uuid": str(project.project_uuid),
            "wp_user_id": 7,
            "scope": {"level": "ccaa", "ine_code": "13"},
        }
        body = json.dumps(payload, separators=(",", ":")).encode()
        headers = security.sign(body, SECRET).as_dict()
        alterado = body.replace(b'"wp_user_id":7', b'"wp_user_id":9')
        response = client.post(
            "/v1/reports", content=alterado,
            headers={"Content-Type": "application/json", **headers},
        )
        assert response.status_code == 401

    def test_esquema_invalido_da_422_con_detalle(self, client):
        response = signed_post(client, "/v1/reports", {
            "project_uuid": str(uuid4()), "wp_user_id": 1,
            "scope": {"level": "provincia", "ine_code": "28", "children_level": "ccaa"},
        })
        assert response.status_code == 422
        assert response.json()["code"] == "validation_error"
        assert response.json()["context"]["errors"]


class TestFirmaEnLectura:
    """El agujero que había: `wp_user_id` lo pone quien llama."""

    def test_lectura_sin_firma_se_rechaza(self, client, created):
        response = client.get(f"/v1/reports/{created}?wp_user_id=7")
        assert response.status_code == 401, "un UUID filtrado abriría el informe"

    def test_firma_de_otra_ruta_no_sirve(self, client, created):
        otro = uuid4()
        headers = security.sign_get(f"/v1/reports/{otro}", "wp_user_id=7", SECRET).as_dict()
        response = client.get(f"/v1/reports/{created}?wp_user_id=7", headers=headers)
        assert response.status_code == 401

    def test_cambiar_el_wp_user_id_invalida_la_firma(self, client, created):
        """La firma cubre la query completa: el id no se puede tocar."""
        headers = security.sign_get(f"/v1/reports/{created}", "wp_user_id=7", SECRET).as_dict()
        response = client.get(f"/v1/reports/{created}?wp_user_id=99", headers=headers)
        assert response.status_code == 401


class TestLecturaDelInforme:
    def _build(self, uow, project_uuid):
        from powergis.application.build_report import BuildReport

        run = uow.runs.latest_for(project_uuid)
        BuildReport(lambda: uow, "1.0.0-test")(run.run_id)

    def test_antes_de_construirse_devuelve_409(self, client, created):
        response = signed_get(client, f"/v1/reports/{created}", "wp_user_id=7")
        assert response.status_code == 409
        assert response.json()["code"] == "report_not_ready"

    def test_despues_devuelve_el_payload(self, client, uow, created):
        self._build(uow, created)
        response = signed_get(client, f"/v1/reports/{created}", "wp_user_id=7")
        assert response.status_code == 200
        payload = response.json()
        assert payload["tier"] == "basico"
        assert payload["scope"]["name"] == "Comunidad de Madrid"

    def test_el_basico_no_filtra_secciones_de_pago(self, client, uow, created):
        self._build(uow, created)
        payload = signed_get(client, f"/v1/reports/{created}", "wp_user_id=7").json()
        bloqueadas = [s for s in payload["sections"] if not s["available"]]
        assert len(bloqueadas) == 4
        assert all(set(s) == {"id", "title", "available", "locked_reason"} for s in bloqueadas)
        assert payload["placerank"] is None
        assert "eco.income.household.mean" not in json.dumps(payload)

    def test_un_usuario_ajeno_recibe_403(self, client, uow, created):
        self._build(uow, created)
        response = signed_get(client, f"/v1/reports/{created}", "wp_user_id=99")
        assert response.status_code == 403
        assert response.json()["code"] == "not_owner"

    def test_proyecto_inexistente_da_404(self, client):
        response = signed_get(client, f"/v1/reports/{uuid4()}", "wp_user_id=7")
        assert response.status_code == 404


class TestUpgrade:
    def test_upgrade_firmado_encola_en_la_cola_prioritaria(self, client, uow, created):
        from powergis.application.build_report import BuildReport

        run = uow.runs.latest_for(created)
        BuildReport(lambda: uow, "1.0.0-test")(run.run_id)

        client.encolados.clear()
        response = signed_post(client, f"/v1/reports/{created}/upgrade", {})
        assert response.status_code == 202, response.text
        assert client.encolados[-1][1] == "reports.advanced"
        assert uow.projects.get(created).tier.value == "avanzado"

    def test_upgrade_sin_firma_se_rechaza(self, client, created):
        response = client.post(f"/v1/reports/{created}/upgrade", json={})
        assert response.status_code == 401


class TestCatalogoPublico:
    def test_el_catalogo_basico_solo_lista_demografia(self, client):
        response = client.get("/v1/reports/catalog/basico")
        assert response.status_code == 200
        disponibles = [s["id"] for s in response.json()["sections"] if s["available"]]
        assert disponibles == ["demografia"]

    def test_el_catalogo_avanzado_lista_las_cinco(self, client):
        disponibles = [
            s["id"] for s in client.get("/v1/reports/catalog/avanzado").json()["sections"]
            if s["available"]
        ]
        assert len(disponibles) == 5


class TestEndpointsInternos:
    def test_sin_clave_interna_se_rechaza(self, client):
        assert client.get("/internal/coverage").status_code == 401

    def test_con_clave_interna_responde(self, client):
        response = client.get(
            "/internal/coverage", headers={"X-Internal-Key": "clave-interna-de-pruebas"}
        )
        assert response.status_code in (200, 500)  # 500 si no hay BD: la clave pasó


class TestCabecerasDeSeguridad:
    def test_se_envian_cabeceras_defensivas(self, client):
        headers = client.get("/health").headers
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["X-Frame-Options"] == "DENY"


class TestFirmaEnPlaceRank:
    """El rebalanceo devuelve el ranking COMPLETO: zonas, puntuaciones,
    dimensiones y contribuciones. Es producto de pago, así que la ruta va
    firmada como cualquier otra lectura.

    Se escapó en la primera pasada de seguridad porque «rebalance» suena a
    cálculo y no a lectura. Devuelve más datos que el propio informe.
    """

    SNAPSHOT: ClassVar[dict] = {
        "version": 1,
        "tier": "avanzado",
        "scope": {"code": "13", "level": "ccaa"},
        "sections": [],
        "placerank": {
            "method": "percentil",
            "weights": {"economico": 0.35, "demografico": 0.30,
                        "ambiental": 0.20, "match": 0.15},
            "rows": [
                {"geo_code": "28", "geo_name": "Madrid", "score": 87.4,
                 "category": "Óptima", "rank": 1,
                 "dimensions": {"economico": 91.0, "demografico": 84.0,
                                "ambiental": 77.0, "match": 88.0},
                 "contributions": {"eco.income.household.mean": 12.3}},
            ],
        },
    }

    PESOS: ClassVar[dict] = {"economico": 0.4, "demografico": 0.3, "ambiental": 0.2, "match": 0.1}

    def _preparar(self, uow, project_uuid):
        from powergis.domain.enums import Tier

        project = uow.projects.get(project_uuid)
        project.tier = Tier.AVANZADO
        uow.projects.save(project)
        uow.snapshots.save(project_uuid, 1, Tier.AVANZADO, self.SNAPSHOT)
        uow.commit()

    def test_sin_firma_no_devuelve_el_ranking(self, client, created, uow):
        self._preparar(uow, created)

        response = client.post(
            f"/v1/reports/{created}/placerank/rebalance", json=self.PESOS
        )

        assert response.status_code == 401, (
            "FUGA: el ranking de pago se sirve sin autenticar a quien "
            "conozca el UUID"
        )
        assert response.json()["code"] == "invalid_signature"

    def test_con_firma_valida_recalcula(self, client, created, uow):
        self._preparar(uow, created)

        response = signed_post(
            client, f"/v1/reports/{created}/placerank/rebalance", self.PESOS
        )

        assert response.status_code == 200, response.text
        assert response.json()["rows"][0]["geo_name"] == "Madrid"

    def test_los_pesos_alterados_tras_firmar_se_rechazan(self, client, created, uow):
        self._preparar(uow, created)

        body = json.dumps(self.PESOS, separators=(",", ":")).encode()
        headers = security.sign(body, SECRET).as_dict()
        otros = json.dumps(
            {"economico": 1.0, "demografico": 0.0, "ambiental": 0.0, "match": 0.0},
            separators=(",", ":"),
        ).encode()

        response = client.post(
            f"/v1/reports/{created}/placerank/rebalance",
            content=otros,
            headers={"Content-Type": "application/json", **headers},
        )

        assert response.status_code == 401


class TestPreparacionReal:
    """`/ready` decide si el proxy manda tráfico. Conectar no es estar listo.

    Comprobado en un entorno real: una base de datos recién creada y sin
    migrar responde al ping perfectamente, `/ready` devolvía «ok», y sin
    embargo toda consulta fallaba con:

        relation "dim_geo" does not exist

    En producción eso significa que Traefik enruta hacia un motor que
    devuelve 500 en todo, sin que ninguna sonda se queje.
    """

    def test_sin_esquema_no_esta_listo(self, client, monkeypatch):
        import powergis.api.routers.health as health

        monkeypatch.setattr(health, "db_ping", lambda: True)
        monkeypatch.setattr(
            health, "schema_ready", lambda: "faltan tablas: dim_geo — ejecuta las migraciones"
        )

        response = client.get("/ready")

        assert response.status_code == 503
        cuerpo = response.json()
        assert cuerpo["status"] == "degraded"
        assert cuerpo["database"] is False, "conectar sin tablas no cuenta como base lista"
        assert any("dim_geo" in p for p in cuerpo["checks"]["config_problems"])

    def test_con_esquema_si_esta_listo(self, client, monkeypatch):
        import powergis.api.routers.health as health

        monkeypatch.setattr(health, "db_ping", lambda: True)
        monkeypatch.setattr(health, "schema_ready", lambda: None)
        monkeypatch.setattr(health, "get_cache", lambda: type("C", (), {"ping": lambda self: True})())

        response = client.get("/ready")

        assert response.status_code == 200
        assert response.json()["database"] is True

    def test_liveness_sigue_respondiendo_sin_base_de_datos(self, client):
        """`/health` es liveness: contesta aunque todo lo demás esté caído.
        Si devolviera 503, el orquestador reiniciaría un proceso sano."""
        assert client.get("/health").status_code == 200
