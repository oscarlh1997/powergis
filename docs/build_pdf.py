#!/usr/bin/env python3
"""Genera el PDF de integración front (WordPress) ↔ back (motor PowerGIS).

Se renderiza con WeasyPrint desde HTML + CSS de impresión, que es exactamente
el mismo camino que usa el exportador a PDF del propio motor.
"""

from __future__ import annotations

import html
from datetime import date
from pathlib import Path

import weasyprint

OUT = Path("/home/claude/PowerGIS-Integracion-Front-Back.pdf")
HOY = date(2026, 8, 20).strftime("%d/%m/%Y")


def esc(value) -> str:
    return html.escape(str(value if value is not None else ""))


def table(headers, rows, cls="", widths=None):
    colgroup = ""
    if widths:
        colgroup = "<colgroup>" + "".join(f'<col style="width:{w}">' for w in widths) + "</colgroup>"
    head = "".join(f"<th>{h}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows
    )
    return (
        f'<table class="{cls}">{colgroup}<thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table>"
    )


OK = '<span class="tag tag--ok">Confirmado</span>'
VER = '<span class="tag tag--warn">Verificar</span>'
NEW = '<span class="tag tag--new">Nuevo</span>'
FIX = '<span class="tag tag--fix">Corregido</span>'

CSS = """
@page {
  size: A4; margin: 20mm 16mm 18mm 16mm;
  @top-right { content: "PowerGIS · Integración front ↔ back";
               font-size: 7.5pt; color: #94a3b8; }
  @bottom-center { content: counter(page) " / " counter(pages);
                   font-size: 7.5pt; color: #94a3b8; }
}
@page :first { @top-right { content: ""; } @bottom-center { content: ""; } }

* { box-sizing: border-box; }
body { font-family: "DejaVu Sans", sans-serif; font-size: 9pt; line-height: 1.5;
       color: #0f172a; }

h1 { font-size: 17pt; margin: 0 0 3mm; letter-spacing: -0.3pt; }
h2 { font-size: 12.5pt; margin: 9mm 0 2.5mm; padding-bottom: 1.5mm;
     border-bottom: 1.6pt solid #1e293b; page-break-after: avoid; }
h3 { font-size: 10pt; margin: 5mm 0 1.5mm; color: #334155; page-break-after: avoid; }
h4 { font-size: 9pt; margin: 4mm 0 1mm; color: #475569; page-break-after: avoid; }
p  { margin: 0 0 2.5mm; }
ul, ol { margin: 0 0 3mm; padding-left: 5mm; }
li { margin-bottom: 1mm; }
code { font-family: "DejaVu Sans Mono", monospace; font-size: 7.8pt;
       background: #f1f5f9; padding: 0.3mm 1mm; border-radius: 1mm; }
pre  { font-family: "DejaVu Sans Mono", monospace; font-size: 7.4pt;
       background: #f8fafc; border-left: 2pt solid #cbd5e1; padding: 2.5mm 3mm;
       margin: 2mm 0 3mm; white-space: pre-wrap; line-height: 1.4;
       page-break-inside: avoid; }

/* ---------- portada ---------- */
.cover { page-break-after: always; padding-top: 55mm; }
.cover .brand { font-size: 8pt; letter-spacing: 2pt; text-transform: uppercase;
                color: #64748b; margin-bottom: 6mm; }
.cover h1 { font-size: 27pt; line-height: 1.15; margin-bottom: 5mm; }
.cover .sub { font-size: 11pt; color: #475569; margin-bottom: 16mm; }
.cover .meta { border-top: 1.5pt solid #1e293b; padding-top: 4mm; font-size: 8.5pt;
               color: #475569; }
.cover .meta div { margin-bottom: 1.4mm; }
.cover .meta strong { color: #0f172a; display: inline-block; width: 34mm; }

/* ---------- tablas ---------- */
table { width: 100%; border-collapse: collapse; margin: 2mm 0 4mm; font-size: 7.8pt;
        page-break-inside: auto; }
thead { display: table-header-group; }
tr { page-break-inside: avoid; }
th { background: #1e293b; color: #fff; text-align: left; padding: 1.6mm 2mm;
     font-weight: 600; font-size: 7.6pt; }
td { border-bottom: 0.4pt solid #e2e8f0; padding: 1.4mm 2mm; vertical-align: top; }
tbody tr:nth-child(even) td { background: #f8fafc; }
table.compact td, table.compact th { padding: 1.1mm 1.6mm; font-size: 7.2pt; }

/* ---------- avisos ---------- */
.box { padding: 3mm 3.5mm; border-radius: 1.5mm; margin: 3mm 0 4mm; font-size: 8.4pt;
       page-break-inside: avoid; }
.box--info  { background: #f1f5f9; border-left: 2.5pt solid #475569; }
.box--warn  { background: #fffbeb; border-left: 2.5pt solid #f59e0b; }
.box--risk  { background: #fef2f2; border-left: 2.5pt solid #dc2626; }
.box--ok    { background: #f0fdf4; border-left: 2.5pt solid #16a34a; }
.box p:last-child { margin-bottom: 0; }
.box strong { display: block; margin-bottom: 1mm; }

.tag { font-size: 6.6pt; padding: 0.4mm 1.6mm; border-radius: 1mm; white-space: nowrap;
       font-weight: 600; }
.tag--ok   { background: #dcfce7; color: #166534; }
.tag--warn { background: #fef3c7; color: #92400e; }
.tag--new  { background: #dbeafe; color: #1e40af; }
.tag--fix  { background: #fce7f3; color: #9d174d; }

.lead { font-size: 9.5pt; color: #334155; margin-bottom: 4mm; }
.muted { color: #64748b; font-size: 8pt; }
.pagebreak { page-break-before: always; }

.toc { font-size: 9pt; }
.toc div { padding: 1.2mm 0; border-bottom: 0.3pt dotted #cbd5e1; }
.toc span { color: #64748b; display: inline-block; width: 8mm; }
"""


def build_html() -> str:
    parts: list[str] = [
        "<!DOCTYPE html><html lang='es'><head><meta charset='utf-8'>",
        "<title>PowerGIS · Integración front ↔ back</title></head><body>",
    ]

    # ------------------------------------------------------------------ #
    # Portada
    # ------------------------------------------------------------------ #
    parts.append(f"""
<div class="cover">
  <div class="brand">PowerGIS · Documento técnico</div>
  <h1>Integración y operaciones<br>Front WordPress ↔ Motor de informes</h1>
  <div class="sub">Contrato de datos, shortcodes, endpoints y puesta en marcha</div>
  <div class="meta">
    <div><strong>Versión</strong> 1.0</div>
    <div><strong>Fecha</strong> {HOY}</div>
    <div><strong>Front</strong> powergis.es · WordPress 6 · OceanWP · Elementor Pro · JetFormBuilder</div>
    <div><strong>Motor</strong> PowerGIS Engine 1.0.0 · FastAPI + Celery + PostgreSQL/PostGIS</div>
    <div><strong>Ámbito</strong> Fases 0 a 8 · CPT <code>project</code> · tiers básico y avanzado</div>
  </div>
  <p class="muted" style="margin-top:14mm">
    El inventario del front de este documento se ha obtenido inspeccionando
    powergis.es a través de su API REST pública y de las páginas publicadas.
    Cada dato lleva su etiqueta de confianza: <span class="tag tag--ok">Confirmado</span>
    (leído directamente del sitio) o <span class="tag tag--warn">Verificar</span>
    (deducido del formulario renderizado, pendiente de confirmar con sesión
    de administrador). El procedimiento exacto de confirmación está al final de
    la sección 4.
  </p>
</div>""")

    # ------------------------------------------------------------------ #
    # Índice
    # ------------------------------------------------------------------ #
    toc = [
        "Resumen en una página",
        "Inventario del front encontrado en powergis.es",
        "Shortcodes",
        "El formulario, paso a paso",
        "Mapa de campos: formulario → motor",
        "Endpoints del contrato",
        "Flujo completo de un informe",
        "Básico → Avanzado",
        "PlaceRank y Match% del perfil",
        "Estructura del informe y origen de cada dato",
        "Estados, errores y reintentos",
        "Seguridad",
        "Qué hay que cambiar en el front actual",
        "Puesta en marcha: checklist",
    ]
    parts.append("<h2>Índice</h2><div class='toc'>")
    for i, item in enumerate(toc, start=1):
        parts.append(f"<div><span>{i}.</span>{esc(item)}</div>")
    parts.append("</div>")

    # ------------------------------------------------------------------ #
    # 1 · Resumen
    # ------------------------------------------------------------------ #
    parts.append("""
<h2>1 · Resumen en una página</h2>

<p class="lead">El informe no es un documento que se genera. Es una consulta
contra un almacén de indicadores que ya está precalculado.</p>

<p>Las «tablas avanzadas» del final de cada sección —todas las provincias de una
comunidad con sus totales por rango de edad— <strong>no son datos del proyecto
del usuario</strong>: son un recorte de una tabla de hechos idéntica para todos
los que pidan ese mismo ámbito. El proyecto solo aporta tres cosas: qué recorte
(ámbito), qué segmentos (edad, género) y qué pesos (perfil de negocio).</p>

<div class="box box--info">
<strong>Reparto de responsabilidades</strong>
<p><strong style="display:inline">WordPress</strong> capta, identifica, presenta
y vende. <strong style="display:inline">El motor</strong> ingiere, calcula,
almacena y exporta. WordPress nunca calcula un indicador ni llama al INE: el CPT
<code>project</code> es un puntero a un informe, no el informe.</p>
</div>""")

    parts.append(table(
        ["", "Generar informes", "Almacén + consulta"],
        [
            ["Informe básico", "2–5 min", "<strong>&lt; 3 s</strong>"],
            ["Coste marginal del gratuito", "real", "<strong>≈ 0</strong>"],
            ["Corregir un KPI", "regenerar N informes", "un <code>UPDATE</code>"],
            ["GeoLens y PlaceRank", "features nuevas y caras", "dos vistas más"],
            ["Upgrade básico → avanzado", "recalcular todo", "añadir lo que falta"],
        ],
        widths=["32%", "34%", "34%"],
    ))

    parts.append("""
<h3>Las tres decisiones que lo sostienen</h3>
<ol>
<li><strong>Almacén en estrella.</strong> <code>dim_geo</code> y
<code>dim_indicator</code> describen; <code>fact_indicator</code> mide. Una fila
por (geografía × indicador × periodo × segmento). Todo lo demás —tablas, KPIs,
top/bottom 3, GeoLens, PlaceRank— es un <code>SELECT</code> sobre esa tabla.</li>
<li><strong>Upgrade incremental.</strong> Un solo job, dos perfiles de ejecución.
El pago no recalcula la demografía: añade lo que faltaba.</li>
<li><strong>Nada de pago viaja al navegador.</strong> Las secciones bloqueadas
llegan como <code>{"available": false}</code> y sin datos dentro. No se ocultan
con CSS: no están.</li>
</ol>""")

    # ------------------------------------------------------------------ #
    # 2 · Inventario
    # ------------------------------------------------------------------ #
    parts.append('<div class="pagebreak"></div><h2>2 · Inventario del front encontrado en powergis.es</h2>')
    parts.append("<h3>Stack</h3>")
    parts.append(table(
        ["Componente", "Detalle", ""],
        [
            ["Tema", "OceanWP", OK],
            ["Maquetación", "Elementor Pro (+40 plantillas en <code>elementor_library</code>)", OK],
            ["Formularios", "JetFormBuilder", OK],
            ["Usuarios", "Ultimate Member (<code>um_form</code>, <code>um_directory</code>)", OK],
            ["Caché", "LiteSpeed Cache", OK],
            ["Otros", "Rank Math SEO, Code Snippets, Google Site Kit, Mailchimp (mc4wp)", OK],
        ],
        widths=["22%", "62%", "16%"],
    ))

    parts.append("<h3>Modelo de contenido</h3>")
    parts.append(table(
        ["Elemento", "Valor", ""],
        [
            ["CPT", "<code>project</code> · <code>rest_base: project</code>", OK],
            ["URL pública", "<code>/proyectos/{slug}/</code>", OK],
            ["Taxonomías", "<code>sector</code> · <code>project_type</code> · <code>location</code> · <code>report_tier</code>", OK],
            ["Términos de <code>report_tier</code>", "<code>basico</code> (ID 43) · <code>avanzado</code> (ID 44) — ambos con <code>count: 0</code>", OK],
            ["Términos de <code>sector</code> y <code>location</code>", "vacíos", OK],
            ["Proyectos existentes", "~25, publicados <strong>sin ningún término asignado</strong> y sin meta de negocio", OK],
        ],
        widths=["26%", "60%", "14%"],
    ))

    parts.append("""
<div class="box box--risk">
<strong>Hallazgo crítico 1 · el dato del informe vive dentro del HTML</strong>
<p>Los proyectos publicados no tienen ni un solo meta de negocio: en
<code>meta</code> solo aparecen claves de OceanWP y de JetSmartFilters. El
contenido del informe está incrustado en el HTML de Elementor. Mientras siga
así no hay GeoLens, ni PlaceRank, ni Excel, ni IA, porque no hay nada que
consultar. Es el bloqueo número uno.</p>
</div>

<div class="box box--risk">
<strong>Hallazgo crítico 2 · el CPT es público</strong>
<p><code>GET /wp-json/wp/v2/project</code> devuelve hoy los proyectos de todos
los usuarios a cualquiera que pida la URL. El plugin lo corrige poniendo el CPT
a <code>public =&gt; false</code> con un controlador REST que filtra por autor.</p>
</div>""")

    parts.append("<h3>Endpoints propios ya registrados</h3>")
    parts.append("<pre>POST /wp-json/saas/v1/projects/create\nPOST /wp-json/saas/v1/projects/save-draft\nPOST /wp-json/saas/v1/projects/callback\n\nPOST /wp-json/pg/v1/update-user | update-company | change-password\n     | reset-password | delete-account | update-account-type | upload-image</pre>")
    parts.append("""
<div class="box box--warn">
<strong>Hallazgo 3 · ninguna de esas rutas declara <code>args</code></strong>
<p>Sin esquema de argumentos no hay validación ni sanitización declarativa. Y
hay que revisar el <code>permission_callback</code> de cada una: en WordPress,
omitirlo —o devolver <code>__return_true</code>— deja el endpoint abierto a
internet. <code>projects/callback</code> en particular tiene que verificar
<strong>firma</strong>, no un token en la query string.</p>
</div>""")

    parts.append("<h3>Páginas del flujo</h3>")
    parts.append(table(
        ["ID", "URL", "Papel", ""],
        [
            ["2905", "<code>/nuevo-proyecto/</code>", "Entrada al formulario (requiere sesión)", OK],
            ["1698", "<code>/crear-proyecto/</code>", "Completar perfil antes del proyecto", OK],
            ["2591", "<code>/crear-proyecto-geolocalizado/</code>", "<strong>El formulario multipaso real</strong>", OK],
            ["2610", "<code>/mis-proyectos/</code>", "Listado con filtros Todos · Recientes · Avanzados · Generales", OK],
            ["2293", "<code>/ejemplo-estudio/</code>", "Informe de ejemplo completo (la maqueta objetivo)", OK],
            ["7586", "<code>/powergis-command-center/</code>", "Panel restringido", OK],
        ],
        widths=["8%", "34%", "48%", "10%"],
    ))

    parts.append("""
<div class="box box--info">
<strong>El filtro «Avanzados / Generales» ya existe en «Mis proyectos»</strong>
<p>La distinción de tier ya está en la interfaz. Lo que falta es que la
alimente un dato real: el término de <code>report_tier</code> que asigna el
callback del motor.</p>
</div>""")

    # ------------------------------------------------------------------ #
    # 3 · Shortcodes
    # ------------------------------------------------------------------ #
    parts.append('<div class="pagebreak"></div><h2>3 · Shortcodes</h2>')
    parts.append("<h3>3.1 · Formularios de JetFormBuilder ya existentes</h3>")
    parts.append("<p>IDs leídos del sitio. La sintaxis del shortcode es la estándar de JetFormBuilder.</p>")
    parts.append(table(
        ["ID", "Nombre", "Uso", ""],
        [
            ["<strong>3118</strong>", "<strong>Crear Proyecto</strong>", "<strong>El formulario del estudio. Es el que importa.</strong>", OK],
            ["2438", "formulario de crear proyecto actualización de perfil", "Completar perfil antes de crear", OK],
            ["5388", "formulario de actualización de perfil", "Editar perfil de usuario", OK],
            ["3055", "Asesoramiento profesional", "Upsell «+35 €» del formulario", OK],
            ["5238", "Página de contacto", "Contacto general", OK],
            ["5406", "newsletter", "Captación", OK],
            ["7065", "Agendar una llamada", "Agenda comercial", OK],
            ["3479 · 3489 · 3493 · 3447", "Captación · IA · Web · Posicionamiento", "Formularios de servicios", OK],
        ],
        widths=["16%", "30%", "44%", "10%"],
    ))
    parts.append("""
<pre>[jet_fb_form form_id="3118"
             submit_type="reload"
             required_mark="*"
             fields_layout="column"
             enable_progress=""
             fields_label_tag="div"]</pre>
<p class="muted">Los atributos secundarios dependen de cómo esté insertado el
formulario en Elementor; <code>form_id</code> es el único imprescindible.</p>""")

    parts.append("<h3>3.2 · Shortcodes que aporta el plugin PowerGIS Connector</h3>")
    parts.append(table(
        ["Shortcode", "Qué hace", ""],
        [
            ["<code>[powergis_report]</code>",
             "Renderiza el informe desde el payload JSON: KPIs, gráficos (ECharts), tablas avanzadas, GeoLens (MapLibre) y PlaceRank. Se inyecta solo en el CPT <code>project</code>; el shortcode sirve para colocarlo en otra plantilla.", NEW],
            ["<code>[powergis_my_projects]</code>",
             "Listado «Mis proyectos» con el estado de cada informe y el CTA de desbloqueo.", NEW],
            ["<code>[powergis_form]</code>",
             "Formulario nativo de creación de proyecto. Sirve para probar el circuito sin JetFormBuilder y como documentación viva del contrato.", NEW],
        ],
        widths=["27%", "63%", "10%"],
    ))

    parts.append("""
<div class="box box--info">
<strong>Una sola plantilla, no 60 widgets</strong>
<p>El informe se renderiza con <strong>una</strong> plantilla de Elementor con
contenedores vacíos marcados con <code>data-pg-*</code> y un bundle JS que los
rellena desde el payload. Añadir un gráfico al informe es añadir un indicador al
catálogo del motor: la plantilla no se toca.</p>
<p>Por eso <strong>Graphina queda fuera del informe</strong>: guarda los datos de
cada gráfico dentro de los <em>settings</em> del widget, en el meta
<code>_elementor_data</code> del post. Con 30–60 gráficos por informe habría que
escribir JSON de Elementor por programa en cada proyecto: frágil, imposible de
versionar y de rendimiento pésimo. En la web comercial puede quedarse.</p>
</div>""")

    # ------------------------------------------------------------------ #
    # 4 · Formulario paso a paso
    # ------------------------------------------------------------------ #
    parts.append('<div class="pagebreak"></div><h2>4 · El formulario, paso a paso</h2>')
    parts.append("""<p>Formulario multipaso de 4 pasos publicado en
<code>/crear-proyecto-geolocalizado/</code>. Estructura, etiquetas y opciones
leídas del formulario renderizado.</p>""")

    parts.append("<h3>Paso 1 · Negocio</h3>")
    parts.append(table(
        ["Campo", "Tipo", "Opciones / formato", ""],
        [
            ["<code>project_title</code>", "texto", "Título del proyecto / nombre del estudio", VER],
            ["<code>geographic_scope</code>", "radio", "Nacional · Comunidad Autónoma · Provincia · Municipio", VER],
            ["<code>autonomous_community</code><br><code>province</code> · <code>city</code>", "select en cascada", "Se muestran según el alcance elegido", VER],
            ["<code>economic_sector</code><br><code>economic_activity</code> · <code>activity_code</code>", "select", "Clasificación CNAE", VER],
            ["<code>average_ticket</code>", "radio", "Micro &lt;10 € · Bajo 10–50 € · Medio 51–200 € · Alto 1.001–5.000 € · Lujo &gt;5.000 €", VER],
        ],
        widths=["30%", "16%", "44%", "10%"],
    ))

    parts.append("<h3>Paso 2 · Cliente objetivo</h3>")
    parts.append(table(
        ["Campo", "Tipo", "Opciones", ""],
        [
            ["<code>age_range[]</code>", "checkbox", "18-24 · 25-34 · 35-44 · 45-54 · 55-64 · 65+ · Indiferente", VER],
            ["<code>gender</code>", "radio", "Indiferente · Femenino · Masculino", VER],
            ["<code>family_status</code>", "select", "Indiferente · Soltero(a) · Pareja sin hijos · Nido lleno · Nido adolescentes · Nido vacío · Monoparental", VER],
            ["<code>education_level</code>", "select", "Indiferente · Sin estudios · Secundaria · Técnico superior · Universitario · Postgrado", VER],
            ["<code>nationality</code>", "select", "Indiferente · nacionalidades", VER],
            ["<code>nse[]</code>", "checkbox", "A/B alta · C+ media-alta · C media · D+ media-baja · D/E baja", VER],
            ["<code>annual_income</code>", "select", "Indiferente · &lt;12k · 12-24k · 24-45k · 45-75k · 75-150k · &gt;150k €", VER],
            ["<code>monthly_available_income</code>", "select", "Indiferente · &lt;300 · 301-800 · 801-2500 · &gt;2500 €", VER],
        ],
        widths=["27%", "13%", "50%", "10%"],
    ))

    parts.append("<h3>Paso 3 · Competencia</h3>")
    parts.append(table(
        ["Campo", "Tipo", "Contenido", ""],
        [
            ["<code>direct_competition</code>", "checkbox", "Presencia de competencia directa", VER],
            ["<code>indirect_competition_high[]</code><br><code>indirect_competition_medium[]</code>", "multi", "Competencia indirecta por nivel", VER],
            ["<code>traffic_generators_high[]</code><br><code>traffic_generators_medium[]</code>", "checkbox", "Centros comerciales · Supermercados · Universidades · Hospitales · Estaciones…", VER],
        ],
        widths=["33%", "13%", "44%", "10%"],
    ))

    parts.append("<h3>Paso 4 · Entorno y factores externos</h3>")
    parts.append(table(
        ["Campo", "Tipo", "Opciones", ""],
        [
            ["<code>climate[]</code>", "checkbox", "Indiferente · Cálido · Templado · Frío · Seco · Húmedo", VER],
            ["<code>pedestrian_traffic</code>", "select", "Indiferente · Muy alto · Alto · Medio · Bajo", VER],
            ["<code>vehicular_traffic</code>", "select", "Indiferente · Muy alto · Alto · Medio · Bajo", VER],
            ["<code>comments</code>", "textarea", "«¿Algún comentario que tengamos que saber…?»", VER],
        ],
        widths=["27%", "13%", "50%", "10%"],
    ))
    parts.append('<p class="muted">Botón final: <strong>«Realizar proyecto»</strong>. '
                 "El paso 4 no incluye elección de tier ni pasarela de pago: el informe "
                 "se crea siempre como básico y el upgrade ocurre después, desde «Mis proyectos».</p>")

    parts.append("""
<div class="box box--warn">
<strong>Los nombres de campo están pendientes de confirmar</strong>
<p>La estructura, las etiquetas y las opciones están leídas del formulario
publicado. Los atributos <code>name=</code> exactos no: JetFormBuilder a veces
envuelve los campos, así que el mapeador del plugin acepta
<strong>varios alias por campo</strong> y funciona igual. Para fijarlos de
forma definitiva, con sesión de administrador:</p>
<pre style="margin-top:2mm">GET /wp-json/jet-form-builder/v1/3118/fields</pre>
<p>y añadir el alias que falte en <code>class-form-mapper.php</code>. No hay que
tocar nada más.</p>
</div>""")

    # ------------------------------------------------------------------ #
    # 5 · Mapa de campos
    # ------------------------------------------------------------------ #
    parts.append('<div class="pagebreak"></div><h2>5 · Mapa de campos: formulario → motor</h2>')
    parts.append("""
<p>El plugin normaliza el formulario y produce el cuerpo de
<code>POST /v1/reports</code>. Hay una distinción que importa mucho:</p>
<ul>
<li><strong>Segmentación</strong> (edad, género) — es lo que se le pide al INE.</li>
<li><strong>Perfil objetivo</strong> (NSE, renta, formación, familia, clima,
tráfico) — <strong>no</strong> es segmentación: es criterio de comparación.</li>
</ul>
<p>Mezclarlos daría tablas vacías, porque el INE no publica «población de 18 a 35
años de clase media-alta con estudios superiores». La segmentación filtra; el
perfil puntúa.</p>""")

    parts.append(table(
        ["Campo del formulario", "Destino en el motor", "Para qué se usa"],
        [
            ["<code>project_title</code>", "título del CPT", "Nombre del proyecto"],
            ["<code>geographic_scope</code>", "<code>scope.level</code>", "Nacional → <code>pais</code>, CCAA → <code>ccaa</code>…"],
            ["<code>autonomous_community</code> / <code>province</code> / <code>city</code>", "<code>scope.ine_code</code>", "Código INE del ámbito"],
            ["—", "<code>scope.children_level</code>", "Nivel de las filas de las tablas. Por defecto, el inmediato inferior"],
            ["<code>age_range[]</code>", "<code>segments.age</code> + <code>target.age_range</code>", "Filtra el padrón <em>y</em> puntúa el match"],
            ["<code>gender</code>", "<code>segments.sex</code>", "«Indiferente» = ambos, no ninguno"],
            ["<code>economic_sector</code> / <code>activity_code</code>", "<code>business.sector</code>", "Elige el perfil de pesos del PlaceRank"],
            ["<code>average_ticket</code>", "<code>business.avg_ticket</code> + <code>target.average_ticket</code>", "Punto medio del tramo como número; el tramo completo puntúa"],
            ["<code>family_status</code>", "<code>target.family_status</code>", "→ % hogares con hijos / unipersonales / 65+"],
            ["<code>education_level</code>", "<code>target.education_level</code>", "→ % universitarios, posgrado, sin estudios"],
            ["<code>nse[]</code>", "<code>target.nse</code>", "→ % clase alta / media-alta / media…"],
            ["<code>annual_income</code>", "<code>target.annual_income</code>", "→ intervalo sobre renta media del hogar (ADRH)"],
            ["<code>monthly_available_income</code>", "<code>target.monthly_available_income</code>", "→ intervalo sobre renta disponible"],
            ["<code>climate[]</code>", "<code>target.climate</code>", "→ intervalo de temperatura media o días de lluvia"],
            ["<code>pedestrian_traffic</code> / <code>vehicular_traffic</code>", "<code>target.*_traffic</code>", "→ índices relativos de tráfico"],
            ["<code>traffic_generators_*[]</code>", "<code>target.traffic_generators_*</code>", "→ índice de atracción de zona"],
            ["<code>direct_competition</code>", "<code>target.direct_competition</code>", "Si es «no», menos densidad competitiva puntúa mejor"],
            ["<code>comments</code>", "meta <code>_pg_form_raw</code>", "Se conserva íntegro; no entra en el cálculo"],
        ],
        cls="compact",
        widths=["30%", "30%", "40%"],
    ))

    parts.append("""
<h3>Cuerpo resultante</h3>
<pre>{
  "project_uuid": "9f1c…",
  "wp_user_id": 42,
  "wp_post_id": 7818,
  "tier": "basico",
  "scope":    { "level": "ccaa", "ine_code": "09", "children_level": "provincia" },
  "segments": { "age": ["25-34","35-44"], "sex": ["F","M"] },
  "business": { "sector": "restauracion", "avg_ticket": 125 },
  "target":   { "education_level": "Universitario", "nse": ["A/B","C+"],
                "annual_income": "45-75k", "climate": ["Templado"],
                "pedestrian_traffic": "Alto", "direct_competition": false },
  "callback_url": "https://powergis.es/wp-json/saas/v1/projects/callback"
}</pre>""")

    # ------------------------------------------------------------------ #
    # 6 · Endpoints
    # ------------------------------------------------------------------ #
    parts.append('<div class="pagebreak"></div><h2>6 · Endpoints del contrato</h2>')
    parts.append("<h3>6.1 · WordPress (lo consume el navegador)</h3>")
    parts.append(table(
        ["Método y ruta", "Autenticación", "Qué hace"],
        [
            ["<code>POST saas/v1/projects/create</code>", "sesión + nonce + límite", "Crea el CPT y encola el informe"],
            ["<code>POST saas/v1/projects/save-draft</code>", "sesión + nonce", "Guarda un borrador sin generar"],
            ["<code>GET saas/v1/projects/{id}/status</code>", "sesión + propiedad", "Estado, tier y versión"],
            ["<code>GET saas/v1/projects/{id}/report</code>", "sesión + propiedad", "Proxy del payload. El <code>project_uuid</code> nunca llega al navegador"],
            ["<code>POST saas/v1/projects/{id}/placerank</code>", "sesión + propiedad + tier", "Recalcula el ranking con pesos nuevos"],
            ["<code>GET saas/v1/projects/{id}/export/{kind}</code>", "sesión + propiedad", "xlsx · pdf · pptx, de servidor a servidor"],
            ["<code>POST saas/v1/checkout</code>", "sesión + propiedad", "Crea la sesión de Stripe Checkout"],
            ["<code>POST saas/v1/stripe/webhook</code>", "firma de Stripe", "<strong>Único sitio donde se desbloquea el informe</strong>"],
            ["<code>POST saas/v1/projects/callback</code>", "HMAC del motor", "El motor avisa de que el informe está listo"],
            ["<code>GET saas/v1/geo/search</code>", "sesión", "Autocompletado del formulario"],
        ],
        cls="compact",
        widths=["36%", "22%", "42%"],
    ))

    parts.append("<h3>6.2 · Motor (solo lo llama WordPress, siempre firmado)</h3>")
    parts.append(table(
        ["Método y ruta", "Qué hace"],
        [
            ["<code>POST /v1/reports</code>", "Crea (o reutiliza) una ejecución. Idempotente por <code>Idempotency-Key</code>"],
            ["<code>GET /v1/reports/{uuid}</code>", "Payload del informe según el tier <em>contratado</em>, no el pedido"],
            ["<code>POST /v1/reports/{uuid}/upgrade</code>", "Promueve a avanzado. Lo dispara el webhook de Stripe"],
            ["<code>POST /v1/reports/{uuid}/downgrade</code>", "Reembolso o disputa: retira el acceso"],
            ["<code>POST /v1/reports/{uuid}/placerank/rebalance</code>", "Ranking con pesos nuevos, sin tocar la base de datos"],
            ["<code>GET /v1/reports/{uuid}/export/{kind}</code>", "Excel · PDF · PowerPoint"],
            ["<code>GET /v1/geo/search</code> · <code>/v1/geo/{level}/{code}/children</code>", "Geografías para el formulario"],
            ["<code>GET /health</code> · <code>/ready</code>", "Sondas de vida y de preparación"],
            ["<code>POST /internal/*</code>", "Operación (ETL manual, catálogo). Clave interna, nunca público"],
        ],
        cls="compact",
        widths=["44%", "56%"],
    ))

    parts.append("""
<h3>6.3 · Firma HMAC</h3>
<p>La misma implementación en Python, PHP y bash. Verificada: las tres producen
firmas idénticas para la misma entrada.</p>
<pre># Escrituras (hay cuerpo)
payload = timestamp + "\\n" + cuerpo_crudo

# Lecturas (no hay cuerpo)
payload = timestamp + "\\n" + "GET" + "\\n" + ruta + "?" + query

firma     = hex( HMAC-SHA256(secreto, payload) )
cabeceras = X-PG-Timestamp, X-PG-Signature</pre>
<ul>
<li>Se firma el <strong>cuerpo crudo</strong>, nunca un JSON reserializado: dos
serializadores producen bytes distintos y la firma dejaría de casar.</li>
<li>Ventana de 300 s contra reenvío, en ambos sentidos del reloj.</li>
<li>Comparación en tiempo constante: <code>hash_equals</code> en PHP,
<code>hmac.compare_digest</code> en Python.</li>
</ul>""")

    # ------------------------------------------------------------------ #
    # 7 · Flujo
    # ------------------------------------------------------------------ #
    parts.append('<div class="pagebreak"></div><h2>7 · Flujo completo de un informe</h2>')
    parts.append("""<pre> 1. El usuario envía el formulario en WordPress
 2. saas/v1/projects/create → valida, crea el CPT en 'draft', firma y encola
 3. POST {MOTOR}/v1/reports          (HMAC-SHA256 + Idempotency-Key)
 4. FastAPI valida el esquema, persiste 'report_run' y encola en Celery
    → cola 'reports.basic' o 'reports.advanced' según el tier
 5. El worker resuelve el ámbito y mira qué indicadores ya están frescos
    · frescos → CERO llamadas externas          ← aquí está todo el ahorro
    · caducos → encola ETL y sigue con lo que hay (no bloquea al usuario)
 6. Compone secciones → KPIs → tablas → top/bottom 3 → GeoLens → PlaceRank
 7. Guarda 'report_snapshot' (JSONB versionado + versión de motor)
 8. Callback firmado a WordPress
 9. WordPress publica el CPT, asigna report_tier / sector / location,
    purga la caché de LiteSpeed
10. El front pide el payload y renderiza tablas, gráficos y mapa</pre>

<div class="box box--ok">
<strong>El paso 5 es el modelo de negocio</strong>
<p>El segundo usuario que pida «Cataluña, 25-44» no toca el INE: lee del
almacén. Por eso el informe básico puede ser gratis sin que cueste dinero, y
por eso es la mejor herramienta de captación que tienes.</p>
</div>""")

    # ------------------------------------------------------------------ #
    # 8 · Básico → Avanzado
    # ------------------------------------------------------------------ #
    parts.append("<h2>8 · Básico → Avanzado</h2>")
    parts.append("""
<p>Ni generar todo y ocultarlo, ni hacer dos llamadas independientes:
<strong>un solo job, dos perfiles de ejecución, acumulativo sobre el mismo
<code>project_uuid</code></strong>.</p>

<pre>run #1  perfil BASIC     → [demografía]                    → snapshot v1, tier=basico
   ↓  [webhook de Stripe]
run #2  perfil ADVANCED  → reutiliza la demografía del v1   → snapshot v2, tier=avanzado
                         + socioeconómico, competencia, clima,
                           tráfico, GeoLens, PlaceRank, IA</pre>""")

    parts.append(table(
        ["Alternativa", "Por qué no"],
        [
            ["Generar todo y ocultar con CSS",
             "Pagas el coste completo por cada usuario gratuito. El dato oculto se lee en "
             "<em>view-source</em> y en la REST API, así que estás publicando el producto de "
             "pago. Y si el usuario paga tres meses después, le entregas datos de hace tres meses."],
            ["Dos llamadas independientes",
             "Recalculas la demografía que ya tenías: trabajo duplicado, dos payloads y dos "
             "verdades posibles para el mismo proyecto."],
        ],
        widths=["28%", "72%"],
    ))

    parts.append("""
<p>La ejecución es <strong>idempotente y resumible</strong>:
<code>report_run.sections_done</code> permite que un fallo en «competencia» no
tire abajo las cuatro secciones ya calculadas. En «Mis proyectos», las secciones
bloqueadas se pintan como tarjetas de teaser generadas a partir de
<code>available: false</code>, sin ningún dato dentro. Además de ser lo correcto,
convierte mejor: enseñas <em>qué</em> hay, no un borrón.</p>""")

    # ------------------------------------------------------------------ #
    # 9 · PlaceRank
    # ------------------------------------------------------------------ #
    parts.append('<div class="pagebreak"></div><h2>9 · PlaceRank y Match% del perfil</h2>')
    parts.append("""
<pre>1. Selecciona los indicadores del sector (dim_indicator + sector_profile)
2. Normaliza cada uno a 0-100 por percentil DENTRO del ámbito consultado
3. Aplica el signo de dim_indicator.direction
4. Agrega por dimensión: económica · demográfica · ambiental · match
5. Score = Σ (dimensión × peso)        pesos por defecto 35 / 30 / 20 / 15
6. Categoría: 85-100 Óptima · 70-84 Excelente · 55-69 Buena
              40-54 Aceptable · 25-39 Deficiente · 0-24 Pésima</pre>

<h3>Las tres reglas que separan un ranking serio de uno decorativo</h3>
<ol>
<li><strong>Los pesos son datos, no código.</strong> Viven en la tabla
<code>sector_profile</code>. Cambiar el modelo de una farmacia no requiere
despliegue, y permite que el usuario mueva los pesos en la interfaz y vea el
ranking recalcularse en vivo. Es la demostración que vende el producto.</li>
<li><strong>Se normaliza dentro del ámbito consultado</strong>, no contra toda
España. Si comparas provincias de Galicia, el 100 es la mejor de Galicia. Si no,
todos los informes regionales salen en gris.</li>
<li><strong>Se guarda la contribución de cada indicador.</strong> Sin eso no
puedes explicar el resultado ni la IA puede escribir por qué una zona es buena.</li>
</ol>

<div class="box box--info">
<strong>Match% · la pieza que conecta el formulario con el ranking</strong>
<p>El formulario no pregunta solo <em>dónde</em>: pregunta <em>a quién</em>
—formación, NSE, renta, familia, clima, tráfico—. Eso es exactamente la columna
«Match% perfil» de la tabla del informe de ejemplo.</p>
<p>Cada preferencia declarada se traduce a un criterio medible sobre el almacén:
«Universitario» → percentil de <code>dem.edu.university_pct</code>; «45-75k» →
intervalo sobre la renta media del hogar; «sin competencia directa» → menos
densidad puntúa mejor. <strong>«Indiferente» no puntúa</strong>: el criterio se
descarta en lugar de meter ruido.</p>
</div>""")

    parts.append("<h4>Comprobado en ejecución: dos perfiles distintos, dos rankings distintos</h4>")
    parts.append("<p class='muted'>Mismo ámbito (Cataluña, provincias), mismo sector, mismos datos. Solo cambia el perfil declarado.</p>")
    parts.append(table(
        ["#", "Perfil A · universitario, 45-75k, sin competencia", "Match", "Perfil B · sin estudios, &lt;12k, nido vacío", "Match"],
        [
            ["1", "Tarragona", "58,4", "Girona", "46,1"],
            ["2", "Lleida", "47,9", "Barcelona", "72,1"],
            ["3", "Barcelona", "82,3", "Tarragona", "38,2"],
            ["4", "Girona", "55,1", "Lleida", "25,7"],
        ],
        cls="compact",
        widths=["6%", "34%", "12%", "36%", "12%"],
    ))

    # ------------------------------------------------------------------ #
    # 10 · Estructura del informe
    # ------------------------------------------------------------------ #
    parts.append('<div class="pagebreak"></div><h2>10 · Estructura del informe y origen de cada dato</h2>')
    parts.append(table(
        ["Sección", "Subsecciones", "Fuente", "Tier"],
        [
            ["Demográfico", "Edad · Género · Estado civil y hogares · Formación · Nacionalidades",
             "INE Padrón continuo y Censo (Tempus3)", "<strong>Básico</strong>"],
            ["Socioeconómico", "NSE · Renta bruta · Renta disponible · Consumo",
             "<strong>INE ADRH</strong> (municipio, distrito y sección censal)", "Avanzado"],
            ["Competencia", "Competencia directa e indirecta · Anclas y atractivos · Saturación comercial",
             "OpenStreetMap · Catastro · INE/DIRCE", "Avanzado"],
            ["Climatología", "Temperaturas · Precipitaciones · Confort · Estacionalidad",
             "AEMET OpenData, normales 1991-2020", "Avanzado"],
            ["Tráfico", "Peatonal · Vehicular",
             "OSM — <strong>índice relativo, no aforo</strong>", "Avanzado"],
            ["GeoLens", "Capas conmutables sobre el mapa",
             "Los mismos hechos + geometrías del IGN", "Avanzado"],
            ["PlaceRank", "Ranking ponderado + Match% del perfil",
             "Derivado del almacén", "Avanzado"],
        ],
        cls="compact",
        widths=["17%", "34%", "34%", "15%"],
    ))

    parts.append("""
<h3>Tres correcciones al planteamiento inicial</h3>
<div class="box box--warn">
<p><strong style="display:inline">1 · Overpass no da datos económicos</strong>, da
POIs de OpenStreetMap. La renta sale del <strong>Atlas de Distribución de Renta
de los Hogares del INE</strong>, que además llega a sección censal.</p>
<p style="margin-top:2mm"><strong style="display:inline">2 · La instancia pública
de Overpass no aguanta carga comercial</strong> (orientativamente &lt;10.000
consultas/día, HTTP 429 al pasarse). En producción: extracto de España de
Geofabrik cargado en tu propio PostGIS, actualizado semanalmente. Consultas
locales, instantáneas y sin límites.</p>
<p style="margin-top:2mm"><strong style="display:inline">3 · El ADRH no publica
en municipios pequeños</strong> por secreto estadístico. Un hueco se guarda como
<code>NULL</code> y se muestra como «no disponible». Pintar un cero ahí es vender
un análisis falso; hay tests que lo impiden.</p>
</div>

<h3>Riesgo legal que hay que resolver antes de construir</h3>
<div class="box box--risk">
<strong>Valoraciones y reseñas de competidores</strong>
<p>La maqueta muestra «valoración media», «nº de reseñas» y «% de competidores
por debajo de 3,5 estrellas». Eso solo sale de Google Places, y los Términos de
Servicio de Google Maps Platform restringen fuertemente el almacenamiento y la
reutilización de ese contenido fuera de un mapa de Google. Vender informes con
esos datos incrustados es un riesgo contractual real.</p>
<p><strong style="display:inline">El código no las calcula:</strong> la sección de
competencia se construye solo con OpenStreetMap. <strong>Consúltalo con un
abogado antes de añadirlas.</strong> El plan B —número y densidad de
competidores desde OSM— sí es viable.</p>
</div>

<p><strong>OpenStreetMap es ODbL:</strong> obliga a atribución visible («©
Colaboradores de OpenStreetMap») en el mapa y en el informe, y la cláusula de
compartir-igual entra si se <em>redistribuye</em> la base de datos derivada. Un
informe con recuentos agregados es normalmente <em>produced work</em>; exportar
un Excel con la lista completa de POIs se acerca a redistribuir datos. Por eso
el exportador saca agregados, no listados.</p>""")

    # ------------------------------------------------------------------ #
    # 11 · Estados
    # ------------------------------------------------------------------ #
    parts.append('<div class="pagebreak"></div><h2>11 · Estados, errores y reintentos</h2>')
    parts.append(table(
        ["Estado", "Significa", "Qué ve el usuario"],
        [
            ["<code>queued</code>", "En cola", "«Estamos calculando tu informe»"],
            ["<code>running</code>", "El worker está trabajando", "Igual, con sondeo cada 2 s (creciente)"],
            ["<code>partial</code>", "Algunas secciones sin datos suficientes", "El informe, con avisos explícitos"],
            ["<code>done</code>", "Completado", "El informe"],
            ["<code>failed</code>", "Error irrecuperable", "Mensaje de error y reintento automático"],
        ],
        cls="compact",
        widths=["16%", "40%", "44%"],
    ))

    parts.append(table(
        ["Código", "HTTP", "Cuándo"],
        [
            ["<code>invalid_signature</code>", "401", "El secreto no coincide en los dos lados"],
            ["<code>stale_request</code>", "401", "Petición fuera de la ventana de 300 s"],
            ["<code>not_owner</code>", "403", "El proyecto es de otro usuario"],
            ["<code>tier_not_allowed</code>", "403", "Se pide una sección de pago sin haberla contratado"],
            ["<code>report_not_ready</code>", "409", "Todavía se está generando. El front reintenta"],
            ["<code>validation_error</code>", "422", "El formulario manda un campo mal. La respuesta dice cuál"],
            ["<code>rate_limited</code>", "429", "Límite de informes gratuitos"],
        ],
        cls="compact",
        widths=["28%", "10%", "62%"],
    ))

    parts.append("""
<div class="box box--info">
<strong>Redes de seguridad</strong>
<p><strong style="display:inline">Callback perdido:</strong> WordPress sondea cada
hora los proyectos en <code>queued</code>/<code>running</code> y los recupera. Un
callback perdido no puede dejar a un cliente mirando «generando…» para siempre.</p>
<p><strong style="display:inline">Worker muerto a media tarea:</strong> una tarea
periódica reencola las ejecuciones colgadas más de dos horas.</p>
<p><strong style="display:inline">Upgrade fallido tras cobrar:</strong> se
reintenta en un minuto y se deja constancia. El pago ya está hecho: eso no se
puede perder.</p>
</div>""")

    # ------------------------------------------------------------------ #
    # 12 · Seguridad
    # ------------------------------------------------------------------ #
    parts.append("<h2>12 · Seguridad</h2>")
    parts.append(table(
        ["Medida", "Detalle", ""],
        [
            ["Firma en escrituras", "HMAC-SHA256 sobre el cuerpo crudo, ventana de 300 s, comparación en tiempo constante", OK],
            ["Firma en lecturas",
             "<code>GET /v1/reports/{uuid}</code> exige HMAC sobre <code>GET\\nruta?query</code>. "
             "Sin ella, <code>wp_user_id</code> lo pondría quien llama y bastaría conocer un UUID "
             "para leer el informe de pago de otro cliente", FIX],
            ["Validación", "Un solo esquema (Pydantic) en el motor. Un campo mal da 422 con el detalle, no un 500", FIX],
            ["Propiedad", "Segunda barrera: el proyecto tiene que ser del usuario que lo pide", OK],
            ["CPT privado", "<code>public =&gt; false</code> + controlador REST que filtra por autor", FIX],
            ["<code>permission_callback</code>", "Nonce + sesión + propiedad en cada ruta. CI falla si aparece un <code>__return_true</code> fuera del webhook de Stripe", FIX],
            ["Idempotencia", "<code>Idempotency-Key</code> al crear y <code>event.id</code> de Stripe al cobrar", OK],
            ["Secretos", "Variables de entorno y <code>wp-config.php</code>. Nunca en la tabla <code>options</code>", OK],
            ["Stripe", "El desbloqueo lo hace el <strong>webhook</strong>, nunca <code>success_url</code>: esa URL la puede visitar cualquiera sin pagar", OK],
            ["Arranque seguro", "El motor se niega a arrancar en producción con secretos por defecto o <code>DEBUG</code> activo", OK],
        ],
        cls="compact",
        widths=["20%", "68%", "12%"],
    ))

    # ------------------------------------------------------------------ #
    # 13 · Cambios en el front
    # ------------------------------------------------------------------ #
    parts.append('<div class="pagebreak"></div><h2>13 · Qué hay que cambiar en el front actual</h2>')
    parts.append(table(
        ["Nº", "Cambio", "Por qué", "Esfuerzo"],
        [
            ["1", "CPT <code>project</code> a no público",
             "Hoy <code>/wp-json/wp/v2/project</code> lista los proyectos de todos", "Bajo"],
            ["2", "Endurecer <code>saas/v1</code>: <code>args</code> + <code>permission_callback</code> + HMAC en el callback",
             "Ninguna ruta declara esquema hoy", "Bajo"],
            ["3", "Sacar el contenido del informe del HTML de Elementor",
             "Sin dato estructurado no hay GeoLens, PlaceRank, Excel ni IA", "<strong>Alto</strong>"],
            ["4", "Una sola plantilla del CPT con contenedores <code>data-pg-*</code>",
             "Sustituye a los 30–60 widgets de Graphina por informe", "Medio"],
            ["5", "Sustituir Graphina por ECharts en el informe",
             "Graphina guarda los datos dentro del widget: no escala", "Medio"],
            ["6", "MapLibre GL + PMTiles en lugar de Leaflet + GeoJSON",
             "Con 8.100 municipios, Leaflet se arrastra", "Medio"],
            ["7", "Cobro con Stripe Checkout propio, no con la pasarela de JetFormBuilder",
             "Hace falta un flujo con estado, reintentable e idempotente", "Medio"],
            ["8", "GeoLens deja de ser un HTML estático subido a <code>/uploads/</code>",
             "Pasa a generarse desde las capas del payload", "Medio"],
            ["9", "Conectar el formulario 3118 a <code>saas/v1/projects/create</code>",
             "Es el único punto de entrada del motor", "Bajo"],
        ],
        cls="compact",
        widths=["6%", "36%", "44%", "14%"],
    ))

    parts.append("""
<div class="box box--ok">
<strong>Lo que NO hay que cambiar</strong>
<p>Ultimate Member como identidad, Elementor para la maquetación, OceanWP,
LiteSpeed, el CPT y sus cuatro taxonomías, y JetFormBuilder para capturar el
formulario. La estructura que ya tienes es correcta; lo que cambia es de dónde
salen los datos.</p>
</div>""")

    # ------------------------------------------------------------------ #
    # 14 · Checklist
    # ------------------------------------------------------------------ #
    parts.append("<h2>14 · Puesta en marcha: checklist</h2>")
    parts.append("""
<h3>Motor (VPS Hostinger KVM 4 · 4 vCPU / 16 GB / 200 GB NVMe)</h3>
<pre>□ docker compose up -d --build
□ alembic upgrade head
□ powergis sync-catalog
□ powergis seed                     # geografías del INE/IGN
□ powergis ingest ine --level municipio
□ powergis derive --level provincia
□ powergis check-config             # se niega a arrancar si algo es inseguro
□ probar la restauración del backup — al menos una vez</pre>

<h3>WordPress</h3>
<pre>□ copiar wordpress/powergis-connector/ a wp-content/plugins/ y activar
□ wp-config.php:
     define( 'POWERGIS_ENGINE_URL',            'https://motor.powergis.es' );
     define( 'POWERGIS_HMAC_SECRET',           '…el MISMO que HMAC_SECRET del motor…' );
     define( 'POWERGIS_STRIPE_SECRET',         'sk_live_…' );
     define( 'POWERGIS_STRIPE_WEBHOOK_SECRET', 'whsec_…' );
     define( 'POWERGIS_STRIPE_PRICE_ID',       'price_…' );
□ webhook de Stripe → /wp-json/saas/v1/stripe/webhook
     eventos: checkout.session.completed, async_payment_succeeded,
              async_payment_failed, charge.refunded, charge.dispute.created
□ Proyectos → Diagnóstico: todo en verde
□ confirmar los name= del formulario 3118 y ajustar class-form-mapper.php
□ NUNCA definir POWERGIS_DEV_MODE en producción</pre>

<div class="box box--risk">
<strong>El primer sitio donde mirar cuando «no funciona»</strong>
<p>Con sesión de administrador, abre
<code>/wp-json/saas/v1/dev/ping-engine</code> (solo en desarrollo). Dice en una
respuesta si el motor contesta y si los dos lados comparten el mismo secreto.
El 90 % de los fallos de integración de este tipo son un <code>HMAC_SECRET</code>
que no coincide.</p>
</div>

<h3>Orden recomendado</h3>
<ol>
<li><strong>Fases 0–3</strong> (cimientos, almacén demográfico, motor de
informes, Stripe): producto vendible en 6–9 semanas.</li>
<li><strong>Fase 4</strong>: secciones avanzadas con datos reales.</li>
<li><strong>Fases 5–8</strong>: GeoLens, PlaceRank, IA y exportaciones.</li>
</ol>
<p class="muted" style="margin-top:6mm">Este documento describe el estado del
front a {fecha} y el contrato de la versión 1.0.0 del motor. Las etiquetas
«Verificar» marcan lo que conviene confirmar con sesión de administrador antes
de dar el mapeo por definitivo.</p>""".replace("{fecha}", HOY))

    parts.append("</body></html>")
    return "".join(parts)


if __name__ == "__main__":
    document = weasyprint.HTML(string=build_html())
    document.write_pdf(OUT, stylesheets=[weasyprint.CSS(string=CSS)])
    print(f"PDF escrito: {OUT} ({OUT.stat().st_size / 1024:.0f} kB)")
