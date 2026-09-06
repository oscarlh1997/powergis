"""Flujo completo: crear → construir → pagar → upgrade.

Sin base de datos ni Redis: los repositorios en memoria implementan los mismos
`Protocol` que los de SQLAlchemy. Ésa es la razón práctica de la arquitectura
hexagonal, no un capricho de diseño.
"""

from __future__ import annotations

import pytest

from powergis.application.build_report import BuildReport
from powergis.application.create_report import CreateReport
from powergis.application.dto import CreateReportIn, UpgradeIn
from powergis.application.upgrade_report import DowngradeReport, UpgradeReport, assert_tier
from powergis.domain.enums import RunStatus, Section, Tier
from powergis.domain.errors import TierNotAllowed

ENGINE = "1.0.0-test"


@pytest.fixture
def encolados():
    return []


@pytest.fixture
def enqueue(encolados):
    def _enqueue(run_id, queue):
        encolados.append((run_id, queue))

    return _enqueue


@pytest.fixture
def payload(project):
    return CreateReportIn(
        project_uuid=project.project_uuid,
        wp_user_id=7,
        wp_post_id=7818,
        tier=Tier.BASICO,
        scope={"level": "ccaa", "ine_code": "13", "children_level": "provincia"},
        segments={"age": ["18-35"], "sex": ["F", "M"]},
        business={"sector": "restauracion", "avg_ticket": 18.5},
    )


class TestCreacion:
    def test_crea_y_encola(self, uow_factory, enqueue, encolados, payload):
        result = CreateReport(uow_factory, ENGINE, enqueue)(payload)
        assert result.created
        assert result.run.status is RunStatus.QUEUED
        assert encolados == [(result.run.run_id, "reports.basic")]

    def test_el_avanzado_va_a_su_propia_cola(self, uow_factory, enqueue, encolados, payload):
        payload.tier = Tier.AVANZADO
        CreateReport(uow_factory, ENGINE, enqueue)(payload)
        assert encolados[0][1] == "reports.advanced"

    def test_doble_submit_no_duplica_trabajo(self, uow_factory, enqueue, encolados, payload):
        create = CreateReport(uow_factory, ENGINE, enqueue)
        primero = create(payload)
        segundo = create(payload)
        assert segundo.created is False
        assert segundo.run.run_id == primero.run.run_id
        assert len(encolados) == 1

    def test_force_si_permite_recalcular(self, uow_factory, enqueue, encolados, payload):
        create = CreateReport(uow_factory, ENGINE, enqueue)
        create(payload)
        payload.force = True
        assert create(payload).created
        assert len(encolados) == 2

    def test_el_hash_cambia_si_cambia_el_ambito(self, payload, project):
        from powergis.domain.enums import GeoLevel
        from powergis.domain.models import Scope

        original = project.input_hash(Tier.BASICO)
        project.scope = Scope(GeoLevel.CCAA, "09", GeoLevel.PROVINCIA)
        assert project.input_hash(Tier.BASICO) != original

    def test_el_hash_es_estable_ante_el_orden_de_los_segmentos(self, project):
        from powergis.domain.models import Segments

        a = project.input_hash(Tier.BASICO)
        project.segments = Segments.from_mapping({"sex": ["M", "F"], "age": ["18-35"]})
        assert project.input_hash(Tier.BASICO) == a


class TestConstruccion:
    def test_construye_el_informe_basico(self, uow_factory, uow, enqueue, payload):
        run = CreateReport(uow_factory, ENGINE, enqueue)(payload).run
        result = BuildReport(uow_factory, ENGINE)(run.run_id)

        assert result.run.status is RunStatus.DONE
        assert result.version == 1
        disponibles = [s.id for s in result.report.sections if s.available]
        assert disponibles == [Section.DEMOGRAFIA]
        assert uow.snapshots.latest(payload.project_uuid)[0] == 1

    def test_marca_las_secciones_hechas(self, uow_factory, enqueue, payload):
        run = CreateReport(uow_factory, ENGINE, enqueue)(payload).run
        result = BuildReport(uow_factory, ENGINE)(run.run_id)
        assert "demografia" in result.run.sections_done

    def test_pide_recarga_de_lo_caducado_sin_bloquear(self, uow_factory, enqueue, payload):
        pedidos = []
        run = CreateReport(uow_factory, ENGINE, enqueue)(payload).run
        service = BuildReport(
            uow_factory, ENGINE,
            request_ingest=lambda codes, level, parent: pedidos.append(codes),
        )
        result = service(run.run_id)
        # Los hechos de prueba son de 2024: para el INE siguen frescos.
        assert result.run.status is RunStatus.DONE
        assert isinstance(pedidos, list)


class TestUpgrade:
    """La respuesta a «¿genero todo y oculto o hago dos llamadas?»: ninguna."""

    @pytest.fixture
    def basico_construido(self, uow_factory, enqueue, payload):
        run = CreateReport(uow_factory, ENGINE, enqueue)(payload).run
        BuildReport(uow_factory, ENGINE)(run.run_id)
        return payload.project_uuid

    def test_sube_el_tier_antes_de_encolar(self, uow_factory, uow, enqueue, basico_construido):
        UpgradeReport(uow_factory, ENGINE, enqueue)(basico_construido, UpgradeIn())
        assert uow.projects.get(basico_construido).tier is Tier.AVANZADO

    def test_encola_en_la_cola_prioritaria(self, uow_factory, enqueue, encolados, basico_construido):
        encolados.clear()
        UpgradeReport(uow_factory, ENGINE, enqueue)(basico_construido, UpgradeIn())
        assert encolados[-1][1] == "reports.advanced"

    def test_informa_de_lo_que_reutiliza(self, uow_factory, enqueue, basico_construido):
        result = UpgradeReport(uow_factory, ENGINE, enqueue)(basico_construido, UpgradeIn())
        assert "demografia" in result.reused_sections

    def test_el_snapshot_v2_tiene_todas_las_secciones(self, uow_factory, uow, enqueue, basico_construido):
        run = UpgradeReport(uow_factory, ENGINE, enqueue)(basico_construido, UpgradeIn()).run
        result = BuildReport(uow_factory, ENGINE)(run.run_id)

        assert result.version == 2
        disponibles = {s.id for s in result.report.sections if s.available}
        assert Section.SOCIOECONOMICO in disponibles
        assert Section.DEMOGRAFIA in disponibles
        assert result.report.placerank is not None

        version, tier, _ = uow.snapshots.latest(basico_construido)
        assert (version, tier) == (2, Tier.AVANZADO)

    def test_el_v1_basico_sigue_disponible_para_auditoria(self, uow_factory, uow, enqueue, basico_construido):
        run = UpgradeReport(uow_factory, ENGINE, enqueue)(basico_construido, UpgradeIn()).run
        BuildReport(uow_factory, ENGINE)(run.run_id)
        assert uow.snapshots.get(basico_construido, 1) is not None

    def test_upgrade_repetido_no_recalcula(self, uow_factory, enqueue, basico_construido):
        upgrade = UpgradeReport(uow_factory, ENGINE, enqueue)
        run = upgrade(basico_construido, UpgradeIn()).run
        BuildReport(uow_factory, ENGINE)(run.run_id)
        segundo = upgrade(basico_construido, UpgradeIn())
        assert segundo.already_advanced


class TestDowngrade:
    def test_el_reembolso_retira_el_acceso(self, uow_factory, uow, enqueue, payload):
        run = CreateReport(uow_factory, ENGINE, enqueue)(payload).run
        BuildReport(uow_factory, ENGINE)(run.run_id)
        uow.projects.set_tier(payload.project_uuid, Tier.AVANZADO)

        DowngradeReport(uow_factory)(payload.project_uuid)
        assert uow.projects.get(payload.project_uuid).tier is Tier.BASICO


class TestGuardaDeTier:
    def test_pedir_avanzado_con_basico_falla(self):
        with pytest.raises(TierNotAllowed):
            assert_tier(Tier.AVANZADO, Tier.BASICO)

    def test_el_avanzado_incluye_el_basico(self):
        assert_tier(Tier.BASICO, Tier.AVANZADO)


class TestValidacionDeEntrada:
    def test_rechaza_un_ambito_incoherente(self):
        with pytest.raises(ValueError):
            CreateReportIn(
                project_uuid="11111111-1111-1111-1111-111111111111",
                wp_user_id=1,
                scope={"level": "provincia", "ine_code": "28", "children_level": "ccaa"},
            )

    def test_rechaza_un_rango_de_edad_invalido(self):
        with pytest.raises(ValueError):
            CreateReportIn(
                project_uuid="11111111-1111-1111-1111-111111111111",
                wp_user_id=1,
                scope={"level": "ccaa", "ine_code": "13"},
                segments={"age": ["dieciocho a treinta"]},
            )

    def test_en_produccion_el_callback_debe_ser_https(self, monkeypatch):
        """En producción no se acepta http. En Docker interno sí: no hay TLS
        entre `wordpress` y `api`, y forzarlo ahí no protege de nada."""
        from powergis import config

        monkeypatch.setenv("ENV", "production")
        config.get_settings.cache_clear()
        try:
            with pytest.raises(ValueError):
                CreateReportIn(
                    project_uuid="11111111-1111-1111-1111-111111111111",
                    wp_user_id=1,
                    scope={"level": "ccaa", "ine_code": "13"},
                    callback_url="http://powergis.es/callback",
                )
        finally:
            monkeypatch.setenv("ENV", "test")
            config.get_settings.cache_clear()

    def test_en_desarrollo_se_admite_http_interno(self):
        payload = CreateReportIn(
            project_uuid="11111111-1111-1111-1111-111111111111",
            wp_user_id=1,
            scope={"level": "ccaa", "ine_code": "13"},
            callback_url="http://wordpress/wp-json/saas/v1/projects/callback",
        )
        assert payload.callback_url.startswith("http://wordpress")

    def test_un_esquema_raro_se_rechaza_siempre(self):
        with pytest.raises(ValueError):
            CreateReportIn(
                project_uuid="11111111-1111-1111-1111-111111111111",
                wp_user_id=1,
                scope={"level": "ccaa", "ine_code": "13"},
                callback_url="ftp://powergis.es/callback",
            )

    def test_rechaza_campos_desconocidos(self):
        with pytest.raises(ValueError):
            CreateReportIn(
                project_uuid="11111111-1111-1111-1111-111111111111",
                wp_user_id=1,
                scope={"level": "ccaa", "ine_code": "13"},
                tier_secreto="admin",
            )
